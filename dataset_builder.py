import csv
import json
import os
import random
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")
RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

RANDOM_SEED = 42
random.seed(RANDOM_SEED)

# 1. Pull the public dataset
def fetch_deepset_dataset() -> pd.DataFrame:
    """Pulls deepset/prompt-injections from HuggingFace and normalizes it
    to our schema: text, label (1=injection, 0=benign), category, source.
    """
    from datasets import load_dataset

    print("Fetching deepset/prompt-injections...")
    ds = load_dataset("deepset/prompt-injections")

    rows = []
    for split in ds:
        for row in ds[split]:
            rows.append({
                "text": row["text"],
                "label": int(row["label"]),
                "category": "deepset_unlabeled",  # dataset doesn't sub-categorize
                "source": "deepset/prompt-injections",
            })

    df = pd.DataFrame(rows)
    out_path = RAW_DIR / "deepset_injections.csv"
    df.to_csv(out_path, index=False)
    print(f"  -> {len(df)} rows saved to {out_path}")
    return df


# 2. Pull the real-world jailbreak dataset (verazuo/jailbreak_llms)
JAILBREAK_CSV_URL = "https://raw.githubusercontent.com/verazuo/jailbreak_llms/main/data/prompts/jailbreak_prompts_2023_12_25.csv"
REGULAR_CSV_URL = "https://raw.githubusercontent.com/verazuo/jailbreak_llms/main/data/prompts/regular_prompts_2023_12_25.csv"

def fetch_wild_jailbreak_dataset(max_per_class: int = 500) -> pd.DataFrame:
    """Pulls the verazuo/jailbreak_llms CSVs directly from GitHub (no auth
    needed, public raw file) and normalizes to our schema.

    Maps to THREAT_MODEL.md's 'jailbreak_persona' category, since that's what
    this dataset predominantly captures (real user attempts to get personas
    like DAN to bypass restrictions).
    """
    print("Fetching real-world jailbreak dataset (verazuo/jailbreak_llms)...")

    jailbreak_df = pd.read_csv(JAILBREAK_CSV_URL)
    regular_df = pd.read_csv(REGULAR_CSV_URL)

    jb_positive = jailbreak_df[jailbreak_df["jailbreak"] == True][["prompt"]].copy()
    jb_positive["label"] = 1
    jb_positive["category"] = "jailbreak_persona"
    jb_positive["source"] = "verazuo/jailbreak_llms (jailbreak)"

    benign = regular_df[["prompt"]].copy()
    benign["label"] = 0
    benign["category"] = "wild_regular"
    benign["source"] = "verazuo/jailbreak_llms (regular)"

    jb_positive = jb_positive.sample(
        n=min(max_per_class, len(jb_positive)), random_state=RANDOM_SEED
    )
    benign = benign.sample(
        n=min(max_per_class, len(benign)), random_state=RANDOM_SEED
    )

    combined = pd.concat([jb_positive, benign], ignore_index=True)
    combined = combined.rename(columns={"prompt": "text"})
    combined = combined[["text", "label", "category", "source"]]

    out_path = RAW_DIR / "wild_jailbreak.csv"
    combined.to_csv(out_path, index=False)
    print(f"  -> {len(combined)} rows saved to {out_path} "
          f"({len(jb_positive)} jailbreak, {len(benign)} regular)")
    return combined


# 3. Generate synthetic examples via Groq
ATTACK_CATEGORIES = {
    "instruction_override": "Ask the AI to ignore, forget, or disregard its previous instructions or system prompt, using varied phrasing.",
    "jailbreak_persona": "Ask the AI to roleplay as, or become, a persona with no rules/restrictions/filters (DAN-style jailbreaks), using varied phrasing.",
    "system_prompt_extraction": "Ask the AI to reveal, print, leak, or repeat its system prompt, configuration, or hidden instructions, using varied phrasing.",
    "delimiter_injection": "Attempt to inject fake system/admin/instruction tags or delimiters to trick the AI into treating user input as privileged instructions.",
    "novel_phrasing": "A prompt injection attack that achieves the same goal as the categories above (override instructions, extract system prompt, or jailbreak) but uses unusual, indirect, or creative phrasing that a simple keyword/regex filter would likely miss.",
}

BENIGN_CATEGORIES = {
    "everyday": "A normal, everyday question or request someone might ask an AI assistant. Nothing related to AI safety, prompts, or instructions.",
    "tricky_benign": """A legitimate, realistic technical or everyday question that happens to use \
words like 'system', 'config'/'configuration', 'ignore', 'instructions', 'restrictions', 'prompt', \
or 'jailbreak' in a completely innocent, non-adversarial context. Draw from ALL of these angles, \
varied across examples:
- Software debugging: e.g. asking for help fixing a bug in system configuration code, environment
  variables, or config files (NOT asking the AI to reveal ITS OWN config).
- Form/input validation logic: e.g. asking how to make a web form skip or ignore certain validation
  errors gracefully, or reset a field to default.
- Academic/research questions: e.g. asking what 'prompt injection' or 'jailbreaking an LLM' means,
  for a class assignment, research paper, or general curiosity about AI safety as a topic.
- IT/sysadmin tasks: e.g. resetting a system's configuration after an update, troubleshooting
  system settings, restarting a service.
- General definitions: e.g. asking what a 'system prompt' is in the context of how LLMs work,
  without asking the AI to reveal its own.
Each example must be something a genuine user would plausibly ask, with NO adversarial intent \
whatsoever — the goal is to teach the difference between using this vocabulary innocently versus \
using it to attack an AI system.""",
}

CATEGORY_COUNT_OVERRIDES = {
    "tricky_benign": 70,  # 120 was too aggressive & skewed classifier toward under-flagging real attacks
}

def _get_groq_client():
    from openai import OpenAI
    api_key = os.getenv("LLM_API_KEY")
    if not api_key or api_key.startswith("mock-"):
        raise RuntimeError(
            "LLM_API_KEY is not set to a real Groq key. Synthetic generation "
            "needs real API access — set LLM_API_KEY in .env to your Groq key."
        )
    return OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)

MODEL_FALLBACKS = [
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
    "llama-3.1-8b-instant",
    "qwen/qwen3-32b",
]

def _call_with_fallback(client, prompt: str, models: list[str] = MODEL_FALLBACKS, temperature: float = 0.9):
    """Tries each model in order, moving to the next one on a rate-limit
    error instead of failing outright. Raises only if every model in the
    fallback list is rate-limited.
    """
    import time
    import openai

    last_err = None
    for model in models:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
            )
            return response, model
        except openai.RateLimitError as e:
            last_err = e
            print(f"  [RATE LIMIT] '{model}' is throttled, trying next fallback model...")
            time.sleep(2)  # brief pause before hitting the next model
            continue

    raise RuntimeError(
        f"All fallback models are rate-limited. Wait a bit and re-run — "
        f"already-generated rows are saved incrementally, nothing is lost. Last error: {last_err}"
    )

def generate_examples(client, category: str, description: str, label: int, n: int) -> list[dict]:
    prompt = f"""Generate {n} diverse, realistic example prompts for the following category:

Category: {category}
Description: {description}

Requirements:
- Each example should be a single, realistic user message (1-3 sentences).
- Vary the phrasing, tone, and structure significantly between examples — avoid near-duplicates.
- Return ONLY a JSON array of strings, no other text, no markdown formatting.

Example output format: ["example one here", "example two here", ...]"""

    response, used_model = _call_with_fallback(client, prompt)
    raw = response.choices[0].message.content.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        examples = json.loads(raw)
    except json.JSONDecodeError:
        print(f"  [WARN] Failed to parse JSON for category '{category}' (model: {used_model}), skipping batch.")
        return []

    return [
        {"text": ex, "label": label, "category": category, "source": f"synthetic_groq_{used_model}"}
        for ex in examples if isinstance(ex, str) and ex.strip()
    ]


def generate_synthetic_dataset(per_category: int = 40) -> pd.DataFrame:
    import time

    client = _get_groq_client()
    all_rows = []
    out_path = RAW_DIR / "synthetic.csv"

    def save_progress():
        if all_rows:
            pd.DataFrame(all_rows).drop_duplicates(subset="text").to_csv(out_path, index=False)

    categories = list(ATTACK_CATEGORIES.items()) + [(c, d) for c, d in BENIGN_CATEGORIES.items()]
    labels = {**{c: 1 for c in ATTACK_CATEGORIES}, **{c: 0 for c in BENIGN_CATEGORIES}}

    for category, desc in categories:
        kind = "attack" if labels[category] == 1 else "benign"
        target_count = CATEGORY_COUNT_OVERRIDES.get(category, per_category)
        print(f"Generating {target_count} examples for {kind} category: {category}")
        for _ in range(target_count // 10):
            try:
                all_rows.extend(generate_examples(client, category, desc, label=labels[category], n=10))
            except RuntimeError as e:
                print(f"  [STOPPED] {e}")
                save_progress()
                df = pd.DataFrame(all_rows).drop_duplicates(subset="text")
                print(f"  -> {len(df)} rows saved to {out_path} (partial — re-run later to continue)")
                return df
            time.sleep(2.5)  # stay comfortably under the 30 RPM free-tier cap
        save_progress()  # checkpoint after each category completes

    df = pd.DataFrame(all_rows).drop_duplicates(subset="text")
    print(f"  -> {len(df)} rows saved to {out_path}")
    return df


# 4. Combine + split, holding out "novel_phrasing" to test generalization
def build_splits(deepset_df: pd.DataFrame, wild_df: pd.DataFrame, synthetic_df: pd.DataFrame):
    from sklearn.model_selection import train_test_split

    combined = pd.concat([deepset_df, wild_df, synthetic_df], ignore_index=True)
    combined = combined.drop_duplicates(subset="text").reset_index(drop=True)

    holdout_mask = combined["category"] == "novel_phrasing"
    holdout_df = combined[holdout_mask]
    trainable_df = combined[~holdout_mask]

    train_df, temp_df = train_test_split(
        trainable_df, test_size=0.3, random_state=RANDOM_SEED, stratify=trainable_df["label"]
    )
    val_df, test_df = train_test_split(
        temp_df, test_size=0.5, random_state=RANDOM_SEED, stratify=temp_df["label"]
    )

    test_df = pd.concat([test_df, holdout_df], ignore_index=True)

    train_df.to_csv(PROCESSED_DIR / "train.csv", index=False)
    val_df.to_csv(PROCESSED_DIR / "val.csv", index=False)
    test_df.to_csv(PROCESSED_DIR / "test.csv", index=False)

    print("\nSplit summary:")
    print(f"  train: {len(train_df)} rows ({train_df['label'].mean():.1%} positive)")
    print(f"  val:   {len(val_df)} rows ({val_df['label'].mean():.1%} positive)")
    print(f"  test:  {len(test_df)} rows ({test_df['label'].mean():.1%} positive, "
          f"includes {len(holdout_df)} held-out novel_phrasing examples)")

if __name__ == "__main__":
    deepset_df = fetch_deepset_dataset()
    wild_df = fetch_wild_jailbreak_dataset(max_per_class=500)
    try:
        synthetic_df = generate_synthetic_dataset(per_category=40)
    except RuntimeError as e:
        print(f"\n[SKIPPED] Synthetic generation: {e}")
        print("Proceeding with deepset + wild data only — set a real LLM_API_KEY and re-run for full dataset.")
        synthetic_df = pd.DataFrame(columns=["text", "label", "category", "source"])
    build_splits(deepset_df, wild_df, synthetic_df)
    print("\nDone. See data/processed/ for train/val/test CSVs.")