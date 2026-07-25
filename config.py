import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Upstream LLM provider
UPSTREAM_URL = os.getenv("UPSTREAM_URL", "https://api.groq.com/openai/v1/chat/completions")
LLM_API_KEY = os.getenv("LLM_API_KEY")

if not LLM_API_KEY:
    # Fail fast at startup instead of failing confusingly on the first request.
    # For local dev without a real key, set LLM_API_KEY=mock-key-for-local-testing
    # explicitly in your .env so it's clear you're intentionally mocking it.
    print("FATAL: LLM_API_KEY is not set. Add it to your .env file.", file=sys.stderr)
    sys.exit(1)

# Firewall's own API auth (protects YOUR endpoint, separate from Groq's key)
# Set FIREWALL_API_KEYS as a comma-separated list, e.g. "key1,key2"
# Leave unset locally if you want to skip auth during early dev.
_raw_keys = os.getenv("FIREWALL_API_KEYS", "")
FIREWALL_API_KEYS = {k.strip() for k in _raw_keys.split(",") if k.strip()}
AUTH_ENABLED = len(FIREWALL_API_KEYS) > 0

MAX_PROMPT_LENGTH = int(os.getenv("MAX_PROMPT_LENGTH", "4000"))  # chars, per message
MAX_MESSAGES = int(os.getenv("MAX_MESSAGES", "50"))              # per conversation

RATE_LIMIT = os.getenv("RATE_LIMIT", "30/minute")

LOG_FILE = os.getenv("LOG_FILE", "logs/requests.jsonl")

# Heuristic detection patterns
# (weight, pattern) — weight lets you tune severity later without touching detection logic.
# This list is intentionally still small; expanding it is a Week 1 task, not done here.
HEURISTIC_PATTERNS = [
    (1.0, r"(?i)ignore (all )?previous instructions"),
    (1.0, r"(?i)disregard (all )?(the )?(above|prior) instructions"),
    (0.9, r"(?i)(reveal|show|give me|tell me|print|output|leak|expose|share) (your |the )?system prompt"),
    (0.9, r"(?i)you are now (an? )?(unmoderated|jailbroken|unrestricted) AI"),
    (0.9, r"(?i)\bDAN\b.{0,20}(mode|prompt)"),
    (0.8, r"(?i)output the raw (configuration|system) (text|prompt)"),
    (0.8, r"(?i)reveal your (instructions|system prompt|guidelines)"),
    (0.7, r"(?i)pretend (you are|to be) .{0,30}(with no|without) (any )?(restrictions|filters|rules)"),
    # Raised from 0.6 -> 0.75: fake system/admin delimiter tags are a strong
    # standalone signal and should clear the block threshold on their own, not just contribute partial score.
    (0.75, r"(?i)</?(system|admin|instructions)>"),
    (0.5, r"[A-Za-z0-9+/]{80,}={0,2}"),              # long base64-looking blob (obfuscation)
]
HEURISTIC_BLOCK_THRESHOLD = float(os.getenv("HEURISTIC_BLOCK_THRESHOLD", "0.7"))
