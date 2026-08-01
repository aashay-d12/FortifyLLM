# DATA.md

Documents the dataset used to train FortifyLLM's ML classifier layer. Categories map to `THREAT_MODEL.md` Section 3.

## Sources

| Source                                                                                    | Rows (approx.)              | License / Terms                         | Notes                                                                                                                                                                                                                                                                                                                                                                                                                    |
| ----------------------------------------------------------------------------------------- | --------------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| [`deepset/prompt-injections`](https://huggingface.co/datasets/deepset/prompt-injections) | ~600                        | CC-BY-4.0                               | Pre-labeled injection vs. benign prompts.                                                                                                                                                                                                                                                                                                                                                                                |
| [`verazuo/jailbreak_llms`](https://github.com/verazuo/jailbreak_llms) (CCS'24)           | ≤1,000 (capped, 500/class) | Research use only, per maintainer terms | Real-world scraped jailbreak + regular prompts. Contains crude/explicit language in some jailbreak examples — expected, since these are genuine attack attempts.**Raw files are gitignored and never committed to this repo.**                                                                                                                                                                                    |
| Synthetic (Groq-generated)                                                                | ~330                        | N/A (generated for this project)        | LLM-generated paraphrases across 5 attack categories + 2 benign categories, including a`novel_phrasing` category held out from train/val to test generalization. `tricky_benign` weighted higher (70 vs. 40 baseline) after evaluation revealed it needed more hard-negative diversity — see `MODEL_CARD.md` "Training History" for the full story, including an overcorrection (120) that had to be walked back. |

## Categories

Attack: `instruction_override`, `jailbreak_persona`, `system_prompt_extraction`, `delimiter_injection`, `novel_phrasing` (held-out, test-only).
Benign: `everyday`, `tricky_benign` (uses attack-adjacent vocabulary innocently — debugging, form validation, IT/sysadmin, academic definitions), `wild_regular` (real non-attack prompts from the jailbreak_llms source).

## Splits

70% train / 15% val / 15% test, stratified by label. `novel_phrasing` examples are excluded from train/val and added only to test, so test performance on that slice measures generalization to unseen phrasing rather than memorization.

**Final counts (from the trained model's evaluation):**

- Total test set: 327 rows (includes the 40-row `novel_phrasing` holdout as a subset)
- Train / val exact counts: not yet logged here — run `check_dataset_counts.py` and paste the output below.

```Python
=== Raw sources ===
deepset_injections.csv: 662 rows
wild_jailbreak.csv: 1000 rows
synthetic.csv: 294 rows

=== Processed splits ===
train.csv: 1336 rows, label dist: {0: 702, 1: 634}
  categories: {'deepset_unlabeled': 472, 'jailbreak_persona': 373, 'wild_regular': 335, 'tricky_benign': 53, 'instruction_override': 29, 'system_prompt_extraction': 28, 'everyday': 25, 'delimiter_injection': 21}
val.csv: 286 rows, label dist: {0: 150, 1: 136}
  categories: {'deepset_unlabeled': 97, 'wild_regular': 83, 'jailbreak_persona': 76, 'tricky_benign': 9, 'delimiter_injection': 6, 'system_prompt_extraction': 6, 'everyday': 5, 'instruction_override': 4}
test.csv: 327 rows, label dist: {1: 176, 0: 151}
  categories: {'deepset_unlabeled': 93, 'jailbreak_persona': 84, 'wild_regular': 82, 'novel_phrasing': 40, 'tricky_benign': 8, 'instruction_override': 7, 'system_prompt_extraction': 6, 'everyday': 4, 'delimiter_injection': 3}
```

Regenerate the dataset via:

```bash
python3 dataset_builder.py
```

## Known limitations

- English-only.
- Class balance is not exact — see counts above. Residual imbalance is handled at training time via class-weighted loss (`WeightedTrainer` in `fine_tune_classifier.py`) rather than solely through generation volume, after an earlier attempt to fix imbalance purely via synthetic volume caused a different regression (see `MODEL_CARD.md`).
- Synthetic examples reflect one LLM's notion of "diverse attack phrasing" — may share stylistic patterns despite the diversity prompt used to generate them.
- `wild_jailbreak` labels (`jailbreak: True/False`) come from the original dataset's crowd-sourced labeling, not manually re-verified here.

## Responsible use note

The `verazuo/jailbreak_llms` dataset is used strictly for training a defensive classifier, per the maintainers' stated research-use intent. Raw data (`data/raw/`, `data/processed/`) is excluded from version control via `.gitignore` due to explicit content in some real-world jailbreak samples.
