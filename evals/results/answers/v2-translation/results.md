# Answer evaluation: prompt v2

39 questions x 3 runs, claude-haiku-5-5 (effort low). Deterministic scorers only; per question details: [per_question.md](per_question.md).

Pipeline: `{'question_language': 'v2', 'faq_chunks': 'per_question', 'query_translation': True, 'context_min_score': None, 'min_rerank_score': -4.0, 'context_budget': 2000, 'chunks': '9c0664878542'}`

| metric | value | meaning |
|---|---|---|
| pass | 0.89 [0.79–0.97] | answer passes all deterministic checks |
| decision | 0.92 [0.82–0.99] | answered when it should, said "I don't know" when it should |
| false_not_found | 0.10 [0.01–0.19] | "I don't know" although the documents answer it (of answerable questions) |
| answered_unanswerable | 0.00 | answered a question the documents do not answer |
| facts | 0.99 | all key facts present (of answered, answerable questions) |
| traps | 0.02 | a trap value in the answer |
| source_hit | 0.98 | at least one citation from an expected document |
| source_precision | 0.96 | share of citations from expected documents |
| retrieval_hit | 0.97 | an expected document is in the context |
| language | 1.00 | answer in the language of the question |
| id_leak | 0.00 | a source id like S1 shown to the customer |

[a–b]: 95% interval, bootstrap over questions.

| type | questions | pass |
|---|---|---|
| answerable | 11 | 0.82 |
| partial | 3 | 1.00 |
| trap | 21 | 0.89 |
| unanswerable | 4 | 1.00 |

| language | questions | pass |
|---|---|---|
| de | 8 | 1.00 |
| en | 11 | 1.00 |
| mixed | 1 | 1.00 |
| uk | 19 | 0.77 |

## Stability across runs

- passed in every run: 34 of 39
- unstable (passed in some runs): t05, t34
- failed in every run: t17, t28, t39
- statuses: {'answered': 95, 'not_found_model': 4, 'not_found_retrieval': 18}; claims dropped by the citation check: 1

## Cost and latency

- $0.503 per 1,000 questions ($0.578 per 1,000 that reach the model; the others stop at the retrieval threshold and cost nothing)
- tokens per model call: 3933 in, 394 out (thinking included)
- latency per question that reaches the model: p50 1448 ms, p95 4738 ms
- this evaluation: $0.0589, 298 s
