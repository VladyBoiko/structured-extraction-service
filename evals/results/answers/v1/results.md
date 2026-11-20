# Answer evaluation: prompt v1

33 questions x 3 runs, claude-haiku-5-5 (effort low). Deterministic scorers only; per question details: [per_question.md](per_question.md).

| metric | value | meaning |
|---|---|---|
| pass | 0.76 | answer passes all deterministic checks |
| decision | 0.82 | answered when it should, said "I don't know" when it should |
| false_not_found | 0.21 | "I don't know" although the documents answer it (of answerable questions) |
| answered_unanswerable | 0.00 | answered a question the documents do not answer |
| facts | 1.00 | all key facts present (of answered, answerable questions) |
| traps | 0.04 | a trap value in the answer |
| source_hit | 1.00 | at least one citation from an expected document |
| source_precision | 0.99 | share of citations from expected documents |
| retrieval_hit | 0.97 | an expected document is in the context |
| language | 0.97 | answer in the language of the question |
| id_leak | 0.00 | a source id like S1 shown to the customer |

| type | questions | pass |
|---|---|---|
| answerable | 8 | 0.62 |
| partial | 2 | 0.50 |
| trap | 19 | 0.79 |
| unanswerable | 4 | 1.00 |

| language | questions | pass |
|---|---|---|
| de | 7 | 0.86 |
| en | 9 | 0.89 |
| mixed | 1 | 0.00 |
| uk | 16 | 0.69 |

## Stability across runs

- passed in every run: 23 of 33
- unstable (passed in some runs): t04, t05, t22
- failed in every run: t12, t16, t17, t18, t19, t27, t28
- statuses: {'answered': 69, 'not_found_model': 12, 'not_found_retrieval': 18}; claims dropped by the citation check: 0

## Cost and latency

- $0.348 per 1,000 questions ($0.425 per 1,000 that reach the model; the others stop at the retrieval threshold and cost nothing)
- tokens per model call: 3861 in, 271 out (thinking included)
- latency per question that reaches the model: p50 2046 ms, p95 4212 ms
- this evaluation: $0.0345, 183 s
