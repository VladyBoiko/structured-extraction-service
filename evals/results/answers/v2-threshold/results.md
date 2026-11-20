# Answer evaluation: prompt v2

39 questions x 3 runs, claude-haiku-5-5 (effort low). Deterministic scorers only; per question details: [per_question.md](per_question.md).

Pipeline: `{'question_language': 'v2', 'faq_chunks': 'per_question', 'query_translation': True, 'context_min_score': -6.0, 'demote_outdated_faq': True, 'min_rerank_score': -6.0, 'context_budget': 2000, 'chunks': '9c0664878542'}`

| metric | value | meaning |
|---|---|---|
| pass | 0.90 [0.80–0.97] | answer passes all deterministic checks |
| decision | 0.95 [0.87–1.00] | answered when it should, said "I don't know" when it should |
| false_not_found | 0.06 [0.00–0.14] | "I don't know" although the documents answer it (of answerable questions) |
| answered_unanswerable | 0.00 | answered a question the documents do not answer |
| facts | 0.97 | all key facts present (of answered, answerable questions) |
| traps | 0.00 | a trap value in the answer |
| source_hit | 0.94 | at least one citation from an expected document |
| source_precision | 0.93 | share of citations from expected documents |
| retrieval_hit | 0.94 | an expected document is in the context |
| language | 1.00 | answer in the language of the question |
| id_leak | 0.00 | a source id like S1 shown to the customer |

[a–b]: 95% interval, bootstrap over questions.

| type | questions | pass |
|---|---|---|
| answerable | 11 | 0.82 |
| partial | 3 | 1.00 |
| trap | 21 | 0.91 |
| unanswerable | 4 | 1.00 |

| language | questions | pass |
|---|---|---|
| de | 8 | 1.00 |
| en | 11 | 1.00 |
| mixed | 1 | 1.00 |
| uk | 19 | 0.79 |

## Stability across runs

- passed in every run: 35 of 39
- unstable (passed in some runs): -
- failed in every run: t17, t28, t34, t39
- statuses: {'answered': 99, 'not_found_model': 15, 'not_found_retrieval': 3}; claims dropped by the citation check: 0

## Cost and latency

- $0.532 per 1,000 questions ($0.543 per 1,000 that reach the model; the others stop at the retrieval threshold and cost nothing)
- tokens per model call: 3586 in, 397 out (thinking included)
- latency per question that reaches the model: p50 1486 ms, p95 4681 ms
- this evaluation: $0.0622, 236 s
