# MODEL_CARD.md — FortifyLLM ML Classifier Layer

## Model

- **Base:** `distilbert-base-uncased` (fine-tuned)
- **Task:** Binary classification — prompt injection / jailbreak (1) vs. benign (0)
- **Training:** 10 epoch ceiling with early stopping (patience=2 on val F1); class-weighted
  cross-entropy loss to correct for label imbalance in training data (see Training History)

## Training data

See `DATA.md` for full sourcing. Summary: `deepset/prompt-injections` + real-world jailbreak
prompts (`verazuo/jailbreak_llms`) + synthetic Groq-generated examples across 5 attack categories
and 2 benign categories, per `THREAT_MODEL.md` Section 3.

## Evaluation results (final)

| Metric    | Overall test set (n=327) | `novel_phrasing` held-out slice (n=40) |
| --------- | ------------------------ | ---------------------------------------- |
| Accuracy  | 0.893                    | 0.925                                    |
| Precision | 0.873                    | 1.00*                                    |
| Recall    | 0.9375                   | 0.925                                    |
| F1        | 0.904                    | 0.961                                    |

\* Precision on `novel_phrasing` isn't a fully meaningful number — this slice is constructed
entirely from attack examples (no true negatives), so precision is structurally guaranteed to
read as perfect regardless of model behavior. **Recall is the only number that reflects real
performance on this slice.**

**Why the held-out slice matters:** `novel_phrasing` examples were excluded from train/val
entirely. Recall here (0.925) reflects generalization to attack phrasing the model never saw
during training, not memorization — this is the primary number this project treats as "success"
per `THREAT_MODEL.md` Section 6, more than overall accuracy.

## Training history — a documented iteration, not a straight line

The first fine-tuning run scored well (novel_phrasing recall 0.925) but heuristic-layer
regression testing revealed 4 false positives on benign prompts using attack-adjacent vocabulary
(e.g. "reset my system's configuration", "ignore previous form validation errors").

**First fix attempt:** tripled the volume of hard-negative training examples in the
`tricky_benign` category (40 → 120) relative to all other categories. This eliminated the false
positives but **collapsed novel_phrasing recall to 0.55** — the model became overly conservative,
missing nearly half of real novel attacks in exchange for fixing 4 false positives. A clear
overcorrection, caught by checking the held-out metric rather than trusting the smaller
regression-test script alone (which showed a misleading 100% at this stage — see note below).

**Second fix (final):** moderated `tricky_benign` volume to 70, and replaced ad-hoc volume
tuning with **class-weighted loss** (inverse-frequency weighting computed from the actual
training label distribution at train time, via a custom `WeightedTrainer`). This let the model
compensate for imbalance mathematically rather than via trial-and-error generation counts, and
recovered novel_phrasing recall to 0.925 while keeping precision at a reasonable 0.873 — a much
better-balanced outcome than either prior run.

**Lesson:** a small, fixed regression test (`test_heuristics.py`, 18 hand-picked examples) is
useful for smoke-testing but becomes misleading once you're iteratively tuning against it —
it hit 100% during the overcorrected run specifically because that run had been tuned to fix its
exact failure cases, not because the model had actually improved. The held-out `metrics.json`
numbers, computed on data never used for tuning decisions, are treated as the trustworthy signal
in this project.

## Known limitations

- English-only.
- No adversarial training performed — a white-box attacker with access to model weights could
  likely craft inputs that evade it (see `THREAT_MODEL.md` Section 4).
- Training data includes LLM-generated synthetic examples, which may share stylistic patterns
  despite prompting for diversity.
- One unexplained false positive observed during spot-checking: a request to summarize *Pride
  and Prejudice* was flagged, despite sharing no obvious vocabulary or structure with attack
  examples. Not yet investigated further — noted as a known quirk rather than a diagnosed cause.
- **Definitional questions about "system prompt" still misclassified (found during live demo
  testing).** "Explain to me what system prompt is and give me some notes" scored 0.986 —
  solidly within the same confidence range as genuine `system_prompt_extraction` attacks
  (0.88–0.996), meaning this can't be fixed by threshold tuning alone. The `tricky_benign`
  training category already covers this scenario conceptually, but apparently not with enough
  phrasing diversity to fully counter the strong lexical association between "system prompt"
  and attack examples. A borderline case ("give me the derivative of 1/x^2 + 4x", scored 0.740)
  *was* recoverable via a threshold bump (0.5 → 0.80), since it sat in a real gap below the
  attack score cluster — showing that not all false positives have the same fix. Decided not to
  attempt a third retraining pass immediately, given two prior rounds already show how easily
  targeted fixes can overcorrect into new regressions (see Training History above); revisit this
  as a single, carefully-validated pass after Week 4 red-teaming provides a fuller picture of
  failure modes, rather than reactively.

## Latency

_To be filled in during Week 4 load testing — report added p95 latency of the ML tier vs.
heuristic-only baseline, under concurrent load._
