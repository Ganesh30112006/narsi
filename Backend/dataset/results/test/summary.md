# Evaluation — test split

76 documents · 80 pages · 617 labelled values · 198 distractors · detector 1.4.0+s14e877c15bfa+r0a6bede1 · NER en_core_web_md-3.8.0

| Experiment | Precision | Recall | F1 | FPR (distractors) | FNR | Detection ms/page |
|---|---|---|---|---|---|---|
| A — Rules only | 0.7203 | 0.7261 | 0.7232 | 0.7374 | 0.2739 | 1.12 |
| B — Rules + Context | 0.9883 | 0.9595 | 0.9737 | 0.0202 | 0.0405 | 2.61 |
| C — NER only | 0.8857 | 0.201 | 0.3276 | 0.0 | 0.799 | 13.91 |
| D — Hybrid (Rules + Context + NER + Validation) | 0.9886 | 0.9822 | 0.9854 | 0.0202 | 0.0178 | 15.89 |

Extraction (incl. OCR): 88.8 ms/page.

## Visual findings — 33 PDF/image pages, 238.8 ms/page

| Type | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|
| QR_CODE | 6 | 0 | 0 | 1.0 | 1.0 |
| SIGNATURE | 6 | 0 | 0 | 1.0 | 1.0 |
