# Evaluation report - 2026-05-27

## Setup

- model_dir: C:\Users\sdiaz\Documents\tesis\output\fakenews_xlmroberta_full_v1\best_model
- validation_path: data\claims_es_pe_full\validation.tsv
- test_path: data\claims_es_pe_full\test.tsv
- label_strategy: strict
- max_length: 128
- decision_threshold: 0.9927636981010437

## Validation set

- examples: 296
- label_counts: {'False': 190, 'True': 106}
- macro_f1: 0.9357
- accuracy: 0.9426
- confusion_matrix: [[188, 2], [15, 91]]

Per-class metrics

- False: precision=0.9261 recall=0.9895 f1=0.9567 support=190
- True: precision=0.9785 recall=0.8585 f1=0.9146 support=106

## Test set

- examples: 298
- label_counts: {'False': 191, 'True': 107}
- macro_f1: 0.9478
- accuracy: 0.9530
- confusion_matrix: [[189, 2], [12, 95]]

Per-class metrics

- False: precision=0.9403 recall=0.9895 f1=0.9643 support=191
- True: precision=0.9794 recall=0.8879 f1=0.9314 support=107
