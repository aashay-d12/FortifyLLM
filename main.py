import asyncio
import json
import os
import re
import time
from contextlib import asynccontextmanager
from typing import List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Header, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

import config
from classifier import classifier
from demo_ui import render_demo_html
from stats import compute_stats
from stats_ui import render_stats_html

@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(os.path.dirname(config.LOG_FILE) or ".", exist_ok=True)
    app.state.http_client = httpx.AsyncClient(timeout=30.0)

    try:
        classifier.load(config.CLASSIFIER_MODEL_DIR)
    except FileNotFoundError as e:
        print(f"[WARN] {e}")
        print("[WARN] Running in HEURISTIC-ONLY mode — Tier 2 ML checks are disabled.")
    except Exception as e:
        print(f"[WARN] Failed to load ML classifier ({e}). Running heuristic-only.")

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

class ChatMessage(BaseModel):
    role: str
    content: str = Field(..., max_length=config.MAX_PROMPT_LENGTH)
    
class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage] = Field(..., max_length=config.MAX_MESSAGES)
    temperature: Optional[float] = 1.0
    stream: Optional[bool] = False


# 2. Auth
def verify_firewall_key(x_api_key: Optional[str] = Header(default=None)):
    if not config.AUTH_ENABLED:
        return  # auth disabled locally when FIREWALL_API_KEYS isn't set
    if x_api_key not in config.FIREWALL_API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key. Provide it via the X-API-Key header.",
        )


# 3. Tiered Inspection Engine
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
    if not classifier.loaded:
        return False, None, 0.0
    score = await asyncio.to_thread(classifier.predict, prompt)
    is_blocked = score >= config.ML_BLOCK_THRESHOLD
    reason = (
        f"ML classifier flagged payload with adversarial confidence {score:.3f} "
        f"(threshold={config.ML_BLOCK_THRESHOLD})"
        if is_blocked else None
    )
    return is_blocked, reason, score


# 4. Shared detection pipeline, used by both the authenticated proxy route and the demo endpoint
async def run_detection_pipeline(prompt: str) -> dict:
    if prompt.strip().lower() in config.GREETING_ALLOWLIST:       # Skip heuristic/ML checks for common greetings 
        return {"blocked": False, "layer": "allowlist", "reason": None, "score": 0.0}

    is_blocked, reason, h_score = run_heuristic_check(prompt)
    if is_blocked:
        return {"blocked": True, "layer": "heuristic", "reason": reason, "score": h_score}

    is_blocked, reason, ml_score = await run_ml_classifier_check(prompt)
    if is_blocked:
        return {"blocked": True, "layer": "classifier", "reason": reason, "score": ml_score}

    return {"blocked": False, "layer": None, "reason": None, "score": ml_score}


# 5. Logging
def log_event(event: dict):
    event["timestamp"] = time.time()
    try:
        with open(config.LOG_FILE, "a") as f:
            f.write(json.dumps(event) + "\n")
    except OSError as e:
        # Logging must never take down the request path.
        print(f"[WARN] Failed to write log: {e}")


# Interception Route
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Streaming is not yet supported by this proxy.",
        )

    latest_user_prompt = payload.messages[-1].content
    client_ip = get_remote_address(request)

    verdict = await run_detection_pipeline(latest_user_prompt)
    if verdict["blocked"]:
        log_event({
            "event": "blocked", "layer": verdict["layer"], "reason": verdict["reason"],
            "score": verdict["score"], "client_ip": client_ip,
        })
        detail = (
            {
                "error": "Security Exception",
                "message": "Malicious activity detected.",
                "code": "PROMPT_INJECTION_TRIGGERED",
            }
            if verdict["layer"] == "heuristic"
            else {"error": "Security Exception", "message": "Adversarial intent flagged."}
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)

    # Forward to upstream LLM provider
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
    return {
        "status": "healthy",
        "service": "FortifyLLM Proxy Engine",
        "ml_classifier_loaded": classifier.loaded,
    }


# 6. Demo - No API key required (but rate-limited more strictly, and the model is fixed) 
class DemoChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(..., max_length=config.MAX_MESSAGES)

@app.get("/demo", response_class=HTMLResponse)
def demo_page():
    return render_demo_html(config.UMAMI_WEBSITE_ID)

@app.post("/api/demo-chat")
@limiter.limit(config.DEMO_RATE_LIMIT)
async def demo_chat(payload: DemoChatRequest, request: Request):
    if not payload.messages:
        raise HTTPException(status_code=400, detail="Messages array cannot be empty.")

    latest_user_prompt = payload.messages[-1].content
    client_ip = get_remote_address(request)

    detection_start = time.time()
    verdict = await run_detection_pipeline(latest_user_prompt)
    detection_ms = round((time.time() - detection_start) * 1000, 1)

    if verdict["blocked"]:
        log_event({
            "event": "blocked", "layer": verdict["layer"], "reason": verdict["reason"],
            "score": verdict["score"], "client_ip": client_ip, "source": "demo",
            "detection_ms": detection_ms,
        })
        return JSONResponse(content={
            "blocked": True,
            "layer": verdict["layer"],
            "reason": verdict["reason"],
            "score": verdict["score"],
        })

    headers = {
        "Authorization": f"Bearer {config.LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": config.DEMO_MODEL,
        "messages": [m.model_dump() for m in payload.messages],
        "temperature": 1.0,
        "stream": False,
    }

    client: httpx.AsyncClient = request.app.state.http_client
    upstream_start = time.time()
    try:
        upstream_response = await client.post(config.UPSTREAM_URL, json=body, headers=headers)
        upstream_ms = round((time.time() - upstream_start) * 1000, 1)

        if upstream_response.status_code != 200:
            log_event({
                "event": "upstream_error", "upstream_status": upstream_response.status_code,
                "client_ip": client_ip, "source": "demo",
                "detection_ms": detection_ms, "upstream_ms": upstream_ms,
            })
            print(f"[TIMING] detection={detection_ms}ms  upstream={upstream_ms}ms  "
                  f"(non-200: {upstream_response.status_code})")
            return JSONResponse(content={
                "blocked": False,
                "reply": "(The upstream model is temporarily unavailable. Try again shortly.)",
            })

        try:
            data = upstream_response.json()
            reply_text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError):
            log_event({
                "event": "upstream_malformed_response", "client_ip": client_ip,
                "source": "demo", "raw_response": upstream_response.text[:500],
            })
            return JSONResponse(content={
                "blocked": False,
                "reply": "(Got an unexpected response from the upstream model. Try again.)",
            })
        total_ms = detection_ms + upstream_ms
        log_event({
            "event": "allowed", "client_ip": client_ip, "source": "demo",
            "detection_ms": detection_ms, "upstream_ms": upstream_ms, "total_ms": total_ms,
        })
        print(f"[TIMING] detection={detection_ms}ms  upstream(groq)={upstream_ms}ms  total={total_ms}ms")
        return {"blocked": False, "layer": verdict["layer"], "score": verdict["score"], "reply": reply_text}
    except httpx.RequestError:
        upstream_ms = round((time.time() - upstream_start) * 1000, 1)
        print(f"[TIMING] detection={detection_ms}ms  upstream FAILED after {upstream_ms}ms")
        return JSONResponse(content={
            "blocked": False,
            "reply": "(Could not reach the upstream model right now — try again shortly.)",
        })


# 7. Usage stats
@app.get("/api/public-stats")
async def public_stats():
    stats = compute_stats()
    return {
        "messages_screened": stats["total_events"],
        "attacks_blocked": stats["blocked"],
        "unique_visitors": stats["unique_client_ips"],
    }

@app.get("/stats", response_class=HTMLResponse)
async def stats_dashboard(key: Optional[str] = None, x_api_key: Optional[str] = Header(default=None)):
    provided_key = key or x_api_key
    if config.AUTH_ENABLED and provided_key not in config.FIREWALL_API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Provide a valid key via ?key=... or the X-API-Key header.",
        )
    return render_stats_html(compute_stats())
