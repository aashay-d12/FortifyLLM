import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Upstream LLM provider
UPSTREAM_URL = os.getenv("UPSTREAM_URL", "https://api.groq.com/openai/v1/chat/completions")
LLM_API_KEY = os.getenv("LLM_API_KEY")

if not LLM_API_KEY:
    print("FATAL: LLM_API_KEY is not set. Add it to your .env file.", file=sys.stderr)
    sys.exit(1)

# Firewall's own API auth
_raw_keys = os.getenv("FIREWALL_API_KEYS", "")
FIREWALL_API_KEYS = {k.strip() for k in _raw_keys.split(",") if k.strip()}
AUTH_ENABLED = len(FIREWALL_API_KEYS) > 0

# Request limits
MAX_PROMPT_LENGTH = int(os.getenv("MAX_PROMPT_LENGTH", "4000"))  # chars per message
MAX_MESSAGES = int(os.getenv("MAX_MESSAGES", "50"))              # per conversation

# Rate limiting
RATE_LIMIT = os.getenv("RATE_LIMIT", "30/minute")

# Logging
LOG_FILE = os.getenv("LOG_FILE", "logs/requests.jsonl")

# Heuristic detection patterns (Tier 1)
HEURISTIC_PATTERNS = [
    (1.0, r"(?i)ignore (all )?previous instructions"),
    (1.0, r"(?i)disregard (all )?(the )?(above|prior) instructions"),
    (0.9, r"(?i)(reveal|show|give me|tell me|print|output|leak|expose|share) (your |the )?system prompt"),
    (0.9, r"(?i)you are now (an? )?(unmoderated|jailbroken|unrestricted) AI"),
    (0.9, r"(?i)\bDAN\b.{0,20}(mode|prompt)"),
    (0.8, r"(?i)output the raw (configuration|system) (text|prompt)"),
    (0.8, r"(?i)reveal your (instructions|system prompt|guidelines)"),
    (0.7, r"(?i)pretend (you are|to be) .{0,30}(with no|without) (any )?(restrictions|filters|rules)"),
    (0.75, r"(?i)</?(system|admin|instructions)>"),
    (0.5, r"[A-Za-z0-9+/]{80,}={0,2}"),              # long base64-looking blob (obfuscation)
]
HEURISTIC_BLOCK_THRESHOLD = float(os.getenv("HEURISTIC_BLOCK_THRESHOLD", "0.7"))

# ML classifier (Tier 2)
CLASSIFIER_MODEL_DIR = os.getenv("CLASSIFIER_MODEL_DIR", "models/classifier")
ML_BLOCK_THRESHOLD = float(os.getenv("ML_BLOCK_THRESHOLD", "0.5"))

# Added greeting allowlist cuz "hello there" and "hi there" are getting blocked by the ML model for some reason.
GREETING_ALLOWLIST = {
    "hello", "hi", "hey", "hello there", "hey there", "hi there",
    "yo", "hey yo", "sup", "wassup", "what's up", "howdy",
    "morning", "good morning", "good afternoon", "good evening", "greetings",
}

# Public demo endpoint
DEMO_RATE_LIMIT = os.getenv("DEMO_RATE_LIMIT", "10/minute")
DEMO_MODEL = os.getenv("DEMO_MODEL", "llama-3.3-70b-versatile")  # fixed server-side

# Third-party analytics (Umami)
UMAMI_WEBSITE_ID = os.getenv("UMAMI_WEBSITE_ID", "")
