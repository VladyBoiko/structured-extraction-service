# Retrieval results: history of runs

The current results are in [results.md](results.md). This file keeps the earlier runs, so changes in the numbers can be
traced to changes in the test set.

## Summary

| Run | Questions | hybrid + rerank: hit@1 / recall@5 / MRR@10 | What changed |
|---|---|---|---|
| 1 | 15 | 0.80 / 1.00 / 0.90 | – |
| 2 | 16 | 0.75 / 0.94 / 0.84 | one question added (r16), evidence and trap descriptions refined |

On the 15 questions of run 1, run 2 gives the same result (hit@1 12/15 = 0.80, recall@5 15/15, MRR 0.90): the whole
drop comes from the new question r16, which every configuration misses. The pipeline and the corpus did not change
between the runs.

## Run 2: changes to the test set

| Question | Change | Why |
|---|---|---|
| r07 | evidence `"listen wirelessly for up to 44 hours"` replaced by `"Music playtime with BT on and ANC on: Up to 44 hrs"` | in the JBL text the first sentence is footnoted "BT on / ANC off", so it does not support an answer about ANC on; the spec table states it exactly |
| r08 | evidence: the German help guide added | the same reset procedure in the other language counts, as in r06 |
| r09 | evidence: `"понад установлений строк (чотирнадцять днів)"` added | the next part of article 8 states the same 14-day term (with the penalty) |
| r11 | evidence: Directive 2011/83/EU Art. 16(e), German and English, added | the source of BGB § 312g(2) 3, which was already counted |
| r12 | evidence: the Ukrainian FAQ added | its instalment answer (from 1 500 UAH) agrees with the current payment policy; the FAQ is wrong only on other topics |
| r16 | new question: an English question whose answer exists only in the Ukrainian returns policy | to measure cross-lingual retrieval where no same-language page has the answer |
| r02, r04, r08, r14, r15 | `trap` descriptions completed | traps found in the results: the DACH FAQ gives the delivery cost to Austria (r02), the 2024 FAQ allows Gold on sale items (r04), the WH-1000XM5 has another reset procedure (r08), German "Zoll" also means inch (r14), partial answers without the Nova Poshta redirect (r15) |
| r01, r10 | no change | candidates considered and left out: the general 14-day rule of the law (r01, the question is about the store) and recital (40) of the directive (r10, the operative rule is Article 9) |

Evidence additions do not change the metrics of their questions: in each case a counted chunk was already at rank 1.

## Run 1 (15 questions)

**Embedding models** (vector search only):

| Model | hit@1 | recall@5 | MRR@10 |
|---|---|---|---|
| paraphrase-multilingual-MiniLM-L12-v2 | 0.27 | 0.60 | 0.41 |
| paraphrase-multilingual-mpnet-base-v2 | 0.13 | 0.40 | 0.20 |
| multilingual-e5-large | 0.60 | 1.00 | 0.73 |

**Search modes** (e5-large, top-5):

| Chunks | Mode | hit@1 | recall@5 | MRR@10 | ms/query | Misses |
|---|---|---|---|---|---|---|
| structure-aware | vector | 0.60 | 1.00 | 0.73 | 9 | – |
| structure-aware | BM25 | 0.33 | 0.87 | 0.56 | 1 | r04, r10 |
| structure-aware | hybrid | 0.60 | 0.93 | 0.73 | 10 | r04 |
| structure-aware | hybrid + rerank | 0.80 | 1.00 | 0.90 | 4,700 | – |
| fixed 300/50 | vector | 0.73 | 0.93 | 0.79 | 12 | r10 |
| fixed 300/50 | BM25 | 0.47 | 0.80 | 0.59 | 2 | r04, r09, r10 |
| fixed 300/50 | hybrid | 0.60 | 0.87 | 0.70 | 11 | r04, r10 |
| fixed 300/50 | hybrid + rerank | 0.80 | 1.00 | 0.90 | 3,800 | – |

**Chunk size sweep** (structure-aware):

| Max tokens | Merge below | Chunks | vector MRR | hybrid MRR | hybrid + rerank: recall@5 / MRR | Misses (rerank) |
|---|---|---|---|---|---|---|
| 300 | 40 | 1,257 | 0.78 | 0.77 | 0.93 / 0.77 | r04 |
| 300 | 150 | 1,043 | 0.76 | 0.69 | 1.00 / 0.87 | – |
| 380 | 150 | 834 | 0.73 | 0.73 | 1.00 / 0.90 | – |

**Rerankers** (hybrid candidates, structure-aware chunks):

| Reranker | Candidates | hit@1 | recall@5 | MRR@10 | ms/query |
|---|---|---|---|---|---|
| bge-reranker-v2-m3 (int8) | 20 | 0.80 | 1.00 | 0.90 | 4,600 |
| bge-reranker-v2-m3 (int8) | 10 | 0.73 | 0.93 | 0.83 | 2,300 |
| jina-reranker-v2-base-multilingual | 20 | 0.67 | 1.00 | 0.81 | 3,900 |
| ms-marco-MiniLM-L-6-v2 (English only) | 20 | 0.53 | 0.80 | 0.66 | 1,400 |

**Status filter** (r01, r04, r05, hybrid + rerank): with `status = current` recall@5 1.00 and no outdated chunk in the
top-5; without the filter recall@5 1.00 and 2 outdated chunks (r01, r05). Unchanged in run 2.

The decisions taken on run 1 (e5-large, hybrid + bge-reranker-v2-m3 over 20 candidates, chunks of 380 tokens merged
below 150) hold in run 2: in every comparison the chosen option is still the best one.
