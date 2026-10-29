# Evaluation — dev split

76 documents · 80 pages · 613 labelled values · 198 distractors · detector 1.4.0+s14e877c15bfa+r0a6bede1 · NER en_core_web_md-3.8.0

| Experiment | Precision | Recall | F1 | FPR (distractors) | FNR | Detection ms/page |
|---|---|---|---|---|---|---|
| A — Rules only | 0.712 | 0.7341 | 0.7229 | 0.7475 | 0.2659 | 0.73 |
| B — Rules + Context | 0.99 | 0.9706 | 0.9802 | 0.0202 | 0.0294 | 1.72 |
| C — NER only | 0.8784 | 0.2121 | 0.3417 | 0.0 | 0.7879 | 7.04 |
| D — Hybrid (Rules + Context + NER + Validation) | 0.9903 | 0.9951 | 0.9927 | 0.0202 | 0.0049 | 8.28 |

Extraction (incl. OCR): 233.5 ms/page.

## Visual findings — 33 PDF/image pages, 189.3 ms/page

| Type | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|
| QR_CODE | 6 | 0 | 0 | 1.0 | 1.0 |
| SIGNATURE | 6 | 0 | 0 | 1.0 | 1.0 |
