import json
import os
import re
import time
from contextlib import asynccontextmanager
from typing import List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Header, Request, status
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

import config

# App lifecycle: reuse one HTTP client instead of creating one per request
@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(os.path.dirname(config.LOG_FILE) or ".", exist_ok=True)
    app.state.http_client = httpx.AsyncClient(timeout=30.0)
    yield
    await app.state.http_client.aclose()

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(
    title="FortifyLLM",
    description="Enterprise-grade security proxy for mitigating adversarial prompt injection.",
    version="1.0.0",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

#1. Schemas matching OpenAI Chat Completion Specs
class ChatMessage(BaseModel):
    role: str
    content: str = Field(..., max_length=config.MAX_PROMPT_LENGTH)

class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage] = Field(..., max_length=config.MAX_MESSAGES)
    temperature: Optional[float] = 1.0
    stream: Optional[bool] = False

#2. Auth (protects YOUR endpoint — separate from the OpenAI key you hold)
def verify_firewall_key(x_api_key: Optional[str] = Header(default=None)):
    if not config.AUTH_ENABLED:
        return  # auth disabled locally when FIREWALL_API_KEYS isn't set
    if x_api_key not in config.FIREWALL_API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key. Provide it via the X-API-Key header.",
        )


#3. Tiered Inspection Engine
def run_heuristic_check(prompt: str) -> tuple[bool, Optional[str], float]:
    """Tier 1: High-speed regex/weighted-signature matching."""
    score = 0.0
    matched = None
    for weight, pattern in config.HEURISTIC_PATTERNS:
        if re.search(pattern, prompt):
            score = max(score, weight)
            matched = pattern
            if score >= config.HEURISTIC_BLOCK_THRESHOLD:
                break
    is_blocked = score >= config.HEURISTIC_BLOCK_THRESHOLD
    reason = f"Matched heuristic signature: '{matched}' (score={score:.2f})" if matched else None
    return is_blocked, reason, score

async def run_ml_classifier_check(prompt: str) -> tuple[bool, Optional[str], float]:
    """Tier 2: Machine Learning Classification.
    Placeholder for the fine-tuned DistilBERT/Transformers model (Week 2).
    """
    # TODO: Week 2 - load local transformer weights and run inference here.
    is_malicious = False
    score = 0.0
    if is_malicious:
        return True, "ML Classifier flagged payload with high adversarial confidence.", score
    return False, None, score


#4. Logging (JSONL now; swap for Postgres/SQLite in Week 3 without
#   changing callers, since they only see this one function)
def log_event(event: dict):
    event["timestamp"] = time.time()
    try:
        with open(config.LOG_FILE, "a") as f:
            f.write(json.dumps(event) + "\n")
    except OSError as e:
        # Logging must never take down the request path.
        print(f"[WARN] Failed to write log: {e}")


#5. Interception Route (The Gateway)
@app.post("/v1/chat/completions", dependencies=[])
@limiter.limit(config.RATE_LIMIT)
async def secure_chat_completion(
    payload: ChatCompletionRequest,
    request: Request,
    x_api_key: Optional[str] = Header(default=None),
):
    verify_firewall_key(x_api_key)
    start_time = time.time()

    if not payload.messages:
        raise HTTPException(status_code=400, detail="Messages array cannot be empty.")

    if payload.stream:
        # SSE passthrough isn't implemented yet — reject explicitly rather than
        # silently breaking on `.json()` against a streamed response.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Streaming is not yet supported by this proxy.",
        )

    latest_user_prompt = payload.messages[-1].content
    client_ip = get_remote_address(request)

    #Tier 1: Heuristic check
    is_blocked, reason, h_score = run_heuristic_check(latest_user_prompt)
    if is_blocked:
        log_event({
            "event": "blocked", "layer": "heuristic", "reason": reason,
            "score": h_score, "client_ip": client_ip,
        })
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "Security Exception",
                "message": "Malicious activity detected.",
                "code": "PROMPT_INJECTION_TRIGGERED",
            },
        )

    #Tier 2: ML classifier check
    is_blocked, reason, ml_score = await run_ml_classifier_check(latest_user_prompt)
    if is_blocked:
        log_event({
            "event": "blocked", "layer": "classifier", "reason": reason,
            "score": ml_score, "client_ip": client_ip,
        })
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "Security Exception", "message": "Adversarial intent flagged."},
        )

    #Forward to upstream LLM provider
    headers = {
        "Authorization": f"Bearer {config.LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    client: httpx.AsyncClient = request.app.state.http_client
    try:
        upstream_response = await client.post(
            config.UPSTREAM_URL,
            json=payload.model_dump(),
            headers=headers,
        )
        if upstream_response.status_code != 200:
            # Deliberately NOT forwarding upstream's raw status code — 403 is
            # reserved exclusively for our own firewall block decisions, so
            # clients/logs/tests can always tell "we blocked this" apart from
            # "the upstream provider rejected/failed the request."
            log_event({
                "event": "upstream_error",
                "upstream_status": upstream_response.status_code,
                "client_ip": client_ip,
            })
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "error": "Upstream Error",
                    "message": "The upstream LLM provider rejected or failed the request.",
                    "upstream_status": upstream_response.status_code,
                },
            )

        latency_ms = (time.time() - start_time) * 1000
        log_event({
            "event": "allowed", "latency_ms": round(latency_ms, 2), "client_ip": client_ip,
        })
        return upstream_response.json()

    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to communicate with upstream LLM: {str(exc)}",
        )

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "FortifyLLM Proxy Engine"}
