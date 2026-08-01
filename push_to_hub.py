"""
Requirements:
    pip install huggingface_hub
Setup (one-time):
    1. Create a free account at https://huggingface.co/join
    2. Get an access token (with WRITE permission) from
       https://huggingface.co/settings/tokens
    3. Run: hf auth login (paste your token)
Run:
    python3 push_to_hub.py --repo_id yourusername/fortifyllm-classifier
"""

import argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo_id", required=True,
                         help="e.g. yourusername/fortifyllm-classifier")
    parser.add_argument("--model_dir", default="models/classifier")
    parser.add_argument("--private", action="store_true",
                         help="Make the Hub repo private (requires HF_TOKEN on Railway too)")
    args = parser.parse_args()

    model_path = Path(args.model_dir)
    if not model_path.exists():
        print(f"[ERROR] {args.model_dir} not found. Run fine_tune_classifier.py first.")
        raise SystemExit(1)

    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    print(f"Loading local model from {args.model_dir}...")
    tokenizer = AutoTokenizer.from_pretrained(args.model_dir)
    model = AutoModelForSequenceClassification.from_pretrained(args.model_dir)

    print(f"Pushing to HuggingFace Hub: {args.repo_id} (private={args.private})...")
    model.push_to_hub(args.repo_id, private=args.private)
    tokenizer.push_to_hub(args.repo_id, private=args.private)

    print(f"\nDone. Your model is now at: https://huggingface.co/{args.repo_id}")
    print(f"\nSet this in Railway's Variables tab:")
    print(f"  CLASSIFIER_MODEL_DIR={args.repo_id}")
    print(f"\n(Keep it as 'models/classifier' in your LOCAL .env — from_pretrained")
    print(f"handles both local paths and Hub repo IDs automatically.)")

if __name__ == "__main__":
    main()