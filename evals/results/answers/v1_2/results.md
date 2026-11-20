# Answer evaluation: prompt v1

39 questions x 3 runs, claude-haiku-5-5 (effort low). Deterministic scorers only; per question details: [per_question.md](per_question.md).

| metric | value | meaning |
|---|---|---|
| pass | 0.75 [0.62–0.87] | answer passes all deterministic checks |
| decision | 0.80 [0.67–0.92] | answered when it should, said "I don't know" when it should |
| false_not_found | 0.23 [0.10–0.36] | "I don't know" although the documents answer it (of answerable questions) |
| answered_unanswerable | 0.00 | answered a question the documents do not answer |
| facts | 1.00 | all key facts present (of answered, answerable questions) |
| traps | 0.01 | a trap value in the answer |
| source_hit | 1.00 | at least one citation from an expected document |
| source_precision | 1.00 | share of citations from expected documents |
| retrieval_hit | 0.94 | an expected document is in the context |
| language | 0.95 | answer in the language of the question |
| id_leak | 0.01 | a source id like S1 shown to the customer |

[a–b]: 95% interval, bootstrap over questions.

| type | questions | pass |
|---|---|---|
| answerable | 11 | 0.61 |
| partial | 3 | 0.78 |
| trap | 21 | 0.78 |
| unanswerable | 4 | 1.00 |

| language | questions | pass |
|---|---|---|
| de | 8 | 0.88 |
| en | 11 | 0.88 |
| mixed | 1 | 0.67 |
| uk | 19 | 0.63 |

## Stability across runs

- passed in every run: 27 of 39
- unstable (passed in some runs): t05, t12, t27, t36
- failed in every run: t16, t17, t18, t19, t28, t34, t37, t39
- statuses: {'answered': 81, 'not_found_model': 9, 'not_found_retrieval': 27}; claims dropped by the citation check: 0

## Cost and latency

- $0.362 per 1,000 questions ($0.471 per 1,000 that reach the model; the others stop at the retrieval threshold and cost nothing)
- tokens per model call: 3897 in, 344 out (thinking included)
- latency per question that reaches the model: p50 1319 ms, p95 4637 ms
- this evaluation: $0.0424, 214 s
