import os
import sys
from dotenv import load_dotenv

load_dotenv()

# --- Upstream LLM provider ---
UPSTREAM_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    # Fail fast at startup instead of failing confusingly on the first request.
    # For local dev without a real key, set OPENAI_API_KEY=mock-key-for-local-testing
    # explicitly in your .env so it's clear you're intentionally mocking it.
    print("FATAL: OPENAI_API_KEY is not set. Add it to your .env file.", file=sys.stderr)
    sys.exit(1)

# --- Firewall's own API auth (protects YOUR endpoint, separate from OpenAI's key) ---
# Set FIREWALL_API_KEYS as a comma-separated list, e.g. "key1,key2"
# Leave unset locally if you want to skip auth during early dev.
_raw_keys = os.getenv("FIREWALL_API_KEYS", "")
FIREWALL_API_KEYS = {k.strip() for k in _raw_keys.split(",") if k.strip()}
AUTH_ENABLED = len(FIREWALL_API_KEYS) > 0

# --- Request limits ---
MAX_PROMPT_LENGTH = int(os.getenv("MAX_PROMPT_LENGTH", "4000"))  # chars, per message
MAX_MESSAGES = int(os.getenv("MAX_MESSAGES", "50"))              # per conversation

# --- Rate limiting ---
RATE_LIMIT = os.getenv("RATE_LIMIT", "30/minute")

# --- Logging ---
LOG_FILE = os.getenv("LOG_FILE", "logs/requests.jsonl")

# --- Heuristic detection patterns ---
# (weight, pattern) — weight lets you tune severity later without touching detection logic.
# This list is intentionally still small; expanding it is a Week 1 task, not done here.
HEURISTIC_PATTERNS = [
    (1.0, r"(?i)ignore (all )?previous instructions"),
    (1.0, r"(?i)disregard (all )?(the )?(above|prior) instructions"),
    (0.9, r"(?i)system prompt"),
    (0.9, r"(?i)you are now (an? )?(unmoderated|jailbroken|unrestricted) AI"),
    (0.9, r"(?i)\bDAN\b.{0,20}(mode|prompt)"),
    (0.8, r"(?i)output the raw (configuration|system) (text|prompt)"),
    (0.8, r"(?i)reveal your (instructions|system prompt|guidelines)"),
    (0.7, r"(?i)pretend (you are|to be) (an? )?(AI )?(with no|without) (restrictions|filters|rules)"),
    (0.6, r"(?i)</?(system|admin|instructions)>"),  # fake delimiter/tag injection
    (0.5, r"[A-Za-z0-9+/]{80,}={0,2}"),              # long base64-looking blob (obfuscation)
]
HEURISTIC_BLOCK_THRESHOLD = float(os.getenv("HEURISTIC_BLOCK_THRESHOLD", "0.7"))