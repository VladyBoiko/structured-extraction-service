# Answer evaluation: prompt v2

39 questions x 3 runs, claude-haiku-5-5 (effort low). Deterministic scorers only; per question details: [per_question.md](per_question.md).

Pipeline: `{'question_language': 'v2', 'faq_chunks': 'merged', 'query_translation': False, 'context_min_score': None, 'min_rerank_score': -4.0, 'context_budget': 2000, 'chunks': 'b45c1c1f1569'}`

| metric | value | meaning |
|---|---|---|
| pass | 0.80 [0.68–0.92] | answer passes all deterministic checks |
| decision | 0.81 [0.69–0.92] | answered when it should, said "I don't know" when it should |
| false_not_found | 0.21 [0.09–0.34] | "I don't know" although the documents answer it (of answerable questions) |
| answered_unanswerable | 0.00 | answered a question the documents do not answer |
| facts | 1.00 | all key facts present (of answered, answerable questions) |
| traps | 0.01 | a trap value in the answer |
| source_hit | 1.00 | at least one citation from an expected document |
| source_precision | 1.00 | share of citations from expected documents |
| retrieval_hit | 0.94 | an expected document is in the context |
| language | 1.00 | answer in the language of the question |
| id_leak | 0.00 | a source id like S1 shown to the customer |

[a–b]: 95% interval, bootstrap over questions.

| type | questions | pass |
|---|---|---|
| answerable | 11 | 0.64 |
| partial | 3 | 1.00 |
| trap | 21 | 0.82 |
| unanswerable | 4 | 1.00 |

| language | questions | pass |
|---|---|---|
| de | 8 | 1.00 |
| en | 11 | 0.91 |
| mixed | 1 | 1.00 |
| uk | 19 | 0.65 |

## Stability across runs

- passed in every run: 30 of 39
- unstable (passed in some runs): t04, t33
- failed in every run: t16, t17, t18, t28, t34, t37, t39
- statuses: {'answered': 83, 'not_found_model': 6, 'not_found_retrieval': 27, 'not_found_unverified': 1}; claims dropped by the citation check: 1

## Cost and latency

- $0.351 per 1,000 questions ($0.457 per 1,000 that reach the model; the others stop at the retrieval threshold and cost nothing)
- tokens per model call: 4138 in, 322 out (thinking included)
- latency per question that reaches the model: p50 1432 ms, p95 4251 ms
- this evaluation: $0.0411, 216 s
