import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from datasets import Dataset
from sklearn.metrics import precision_recall_fscore_support, accuracy_score
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
    DataCollatorWithPadding,
    EarlyStoppingCallback,
)

class WeightedTrainer(Trainer):
    """
    A Trainer that weights the loss by inverse class frequency, so class imbalance 
    in the training data (e.g. more benign than attack examples,or vice versa) 
    doesn't bias the model toward always predicting the majority class. 
    """
    def __init__(self, *args, class_weights=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.class_weights = class_weights

    def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
        labels = inputs.pop("labels")
        outputs = model(**inputs)
        logits = outputs.logits
        loss_fct = torch.nn.CrossEntropyLoss(weight=self.class_weights.to(logits.device))
        loss = loss_fct(logits.view(-1, model.config.num_labels), labels.view(-1))
        return (loss, outputs) if return_outputs else loss

DATA_DIR = Path("data/processed")
MODEL_OUT_DIR = Path("models/classifier")

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--model_name", default="distilbert-base-uncased",
                    help="Base model to fine-tune. DeBERTa-v3-small is a good "
                         "alternative if you want slightly higher accuracy at "
                         "similar latency: microsoft/deberta-v3-small")
    p.add_argument("--epochs", type=int, default=10,
                    help="Upper bound only — early stopping (patience=2 on val "
                         "F1) will halt training sooner in practice. Safe to "
                         "set high since overfitting is guarded against.")
    p.add_argument("--batch_size", type=int, default=16,
                    help="Lower this (e.g. 8) if you hit CUDA out-of-memory errors")
    p.add_argument("--max_length", type=int, default=256,
                    help="Prompts are usually short; 256 tokens covers almost all cases")
    p.add_argument("--learning_rate", type=float, default=2e-5)
    return p.parse_args()

def load_splits():
    train_df = pd.read_csv(DATA_DIR / "train.csv")
    val_df = pd.read_csv(DATA_DIR / "val.csv")
    test_df = pd.read_csv(DATA_DIR / "test.csv")

    for name, df in [("train", train_df), ("val", val_df), ("test", test_df)]:
        if len(df) < 20:
            print(f"[WARN] {name}.csv has only {len(df)} rows — this looks like a "
                  f"placeholder/test dataset, not a real training set. Make sure "
                  f"you ran dataset_builder.py with a real LLM_API_KEY first.")

    return train_df, val_df, test_df


def compute_metrics(eval_pred):
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)
    precision, recall, f1, _ = precision_recall_fscore_support(
        labels, preds, average="binary", zero_division=0
    )
    acc = accuracy_score(labels, preds)
    return {"accuracy": acc, "precision": precision, "recall": recall, "f1": f1}


def evaluate_slice(trainer, tokenizer, df: pd.DataFrame, max_length: int, label: str) -> dict:
    """Runs eval on an arbitrary dataframe slice and returns metrics dict."""
    if len(df) == 0:
        return {"note": f"no rows for slice '{label}'"}

    ds = Dataset.from_pandas(df[["text", "label"]].reset_index(drop=True))
    ds = ds.map(
        lambda batch: tokenizer(batch["text"], truncation=True, max_length=max_length),
        batched=True,
    )
    result = trainer.predict(ds)
    metrics = compute_metrics((result.predictions, result.label_ids))
    metrics["n"] = len(df)
    print(f"  [{label}] n={len(df)} | acc={metrics['accuracy']:.3f} "
          f"precision={metrics['precision']:.3f} recall={metrics['recall']:.3f} f1={metrics['f1']:.3f}")
    return metrics


def main():
    args = parse_args()
    MODEL_OUT_DIR.mkdir(parents=True, exist_ok=True)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")
    if device == "cpu":
        print("[WARN] No GPU detected — training will be slow. "
              "Check `nvidia-smi` if you expected a GPU to be used.")

    train_df, val_df, test_df = load_splits()

    print(f"\nLoading tokenizer + model: {args.model_name}")
    tokenizer = AutoTokenizer.from_pretrained(args.model_name)
    model = AutoModelForSequenceClassification.from_pretrained(args.model_name, num_labels=2)

    def to_hf_dataset(df):
        ds = Dataset.from_pandas(df[["text", "label"]].reset_index(drop=True))
        return ds.map(
            lambda batch: tokenizer(batch["text"], truncation=True, max_length=args.max_length),
            batched=True,
        )

    train_ds = to_hf_dataset(train_df)
    val_ds = to_hf_dataset(val_df)

    label_counts = train_df["label"].value_counts().sort_index()
    print(f"\nTrain label distribution: {label_counts.to_dict()}")
    total = label_counts.sum()
    n_classes = len(label_counts)
    class_weights = torch.tensor(
        [total / (n_classes * label_counts[i]) for i in range(n_classes)],
        dtype=torch.float,
    )
    print(f"Computed class weights: {class_weights.tolist()} (higher weight = rarer class)")

    data_collator = DataCollatorWithPadding(tokenizer=tokenizer)

    training_args_kwargs = dict(
        output_dir="models/checkpoints",
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="f1",
        logging_steps=10,
        fp16=torch.cuda.is_available(),  # mixed precision only helps on GPU
        report_to="none",  # skip auto-logging to wandb unless you set it up separately
    )
    try:
        training_args = TrainingArguments(eval_strategy="epoch", **training_args_kwargs)
    except TypeError:
        training_args = TrainingArguments(evaluation_strategy="epoch", **training_args_kwargs)

    trainer = WeightedTrainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        data_collator=data_collator,
        compute_metrics=compute_metrics,
        class_weights=class_weights,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=2)],
    )

    print("\nStarting fine-tuning...")
    trainer.train()

    print("\n=== Evaluation ===")
    overall = evaluate_slice(trainer, tokenizer, test_df, args.max_length, "test (overall)")

    results = {
        "model_name": args.model_name,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "learning_rate": args.learning_rate,
        "test_overall": overall,
    }

    if "category" in test_df.columns:
        novel_df = test_df[test_df["category"] == "novel_phrasing"]
        if len(novel_df) > 0:
            print("\n--- Held-out generalization slice ---")
            novel_metrics = evaluate_slice(trainer, tokenizer, novel_df, args.max_length, "novel_phrasing (held-out)")
            results["test_novel_phrasing_holdout"] = novel_metrics
        else:
            print("\n[INFO] No 'novel_phrasing' rows found in test set — "
                  "did dataset_builder.py's synthetic generation run successfully?")

    print(f"\nSaving model + tokenizer to {MODEL_OUT_DIR}")
    trainer.save_model(str(MODEL_OUT_DIR))
    tokenizer.save_pretrained(str(MODEL_OUT_DIR))

    metrics_path = MODEL_OUT_DIR / "metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved metrics to {metrics_path}")

if __name__ == "__main__":
    main()