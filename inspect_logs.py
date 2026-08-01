"""
Quick inspector for classifier-layer decisions in logs/requests.jsonl.
Run after firing test traffic through the API to see actual scores,
which is what you need to tune ML_BLOCK_THRESHOLD based on real data
instead of guessing.

Usage:
    python3 inspect_logs.py
"""

import json
from pathlib import Path

import config

log_path = Path(config.LOG_FILE)

if not log_path.exists():
    print(f"No log file found at {log_path}. Run some requests through the API first.")
    raise SystemExit(1)

classifier_events = []
with open(log_path) as f:
    for line in f:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("layer") == "classifier":
            classifier_events.append(event)

if not classifier_events:
    print("No classifier-layer events found in the log yet.")
    print("Either the classifier isn't loaded, or nothing has been blocked by it so far.")
    raise SystemExit(0)

# Sort by score, highest first — makes it easy to eyeball where a good
# threshold cutoff would sit.
classifier_events.sort(key=lambda e: e.get("score", 0), reverse=True)

print(f"{'SCORE':>7}  {'REASON'}")
print("-" * 80)
for e in classifier_events:
    score = e.get("score", 0)
    reason = e.get("reason", "")
    print(f"{score:>7.3f}  {reason}")

print(f"\n{len(classifier_events)} classifier-blocked events total.")
print(f"Current threshold: {config.ML_BLOCK_THRESHOLD}")