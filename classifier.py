"""
Wraps the fine-tuned classifier (from fine_tune_classifier.py) for use in
the API's Tier 2 detection check. Loaded once at app startup, not per-request.
"""

class MLClassifier:
    def __init__(self):
        self.tokenizer = None
        self.model = None
        self.device = None
        self.loaded = False

    def load(self, model_dir: str):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model_dir)
            self.model = AutoModelForSequenceClassification.from_pretrained(model_dir)
        except OSError as e:
            raise FileNotFoundError(
                f"Could not load classifier from '{model_dir}' — tried both as a "
                f"local path and a HuggingFace Hub repo ID. Either run "
                f"fine_tune_classifier.py first (for local use), or push your "
                f"trained model to the Hub via push_to_hub.py and set "
                f"CLASSIFIER_MODEL_DIR to the resulting repo ID. Original error: {e}"
            )

        self.model.to(self.device)
        self.model.eval()
        self.loaded = True
        print(f"[INFO] ML classifier loaded from '{model_dir}' on device={self.device}")

    def predict(self, text: str, max_length: int = 256) -> float:
        import torch

        if not self.loaded:
            raise RuntimeError("Classifier not loaded — call .load() first.")

        inputs = self.tokenizer(text, truncation=True, max_length=max_length, return_tensors="pt").to(self.device)

        with torch.no_grad():
            logits = self.model(**inputs).logits
            probs = torch.softmax(logits, dim=-1)

        return probs[0][1].item()  # P(label == 1) i.e. P(injection)

classifier = MLClassifier()