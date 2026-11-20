# Report: RAG over the support corpus (block 2)

Block 1 (structured extraction from tickets) is reported in [REPORT.md](REPORT.md). How to run everything here, and
the design of each part, is in the README section [RAG over the support corpus](README.md#rag-over-the-support-corpus-block-2).

## Summary

A support assistant answers customer questions in Ukrainian, German, English or a mix, only from the store's
documents, citing the document and section of every claim, and says "I don't know" when the documents do not answer.
It was evaluated on 39 questions answered three times each, with deterministic checks, an LLM judge checked against
human labels, and a faithfulness check; then improved in six measured steps.

| | v1 (first version) | v2 (final) |
|---|---|---|
| answers passing every deterministic check | 0.75 [0.62–0.87] | **0.90** [0.80–0.97] |
| graded correct by the LLM judge | 0.62 | **0.82** |
| "I don't know" although the documents answer | 0.23 | **0.06** |
| answered a question the documents do not answer | 0 | 0 |
| claims supported by the cited source (faithfulness) | 0.985 | 0.96 |
| cost per 1,000 questions | $0.36 | $0.53 |

[a–b]: 95% interval, bootstrap over questions. The quality gates of v2 run in CI on every push (about $0.02 a run).

## Setup

- **Corpus**: 51 documents (54 files with three planted duplicates), Markdown, DOCX, HTML and PDF, each in one
  language (20 English, 16 German, 15 Ukrainian): 36 synthetic store documents (policies, FAQs, product pages) and
  15 public ones (Sony and JBL manuals and spec sheets, Ukrainian, EU and German consumer law). Traps are built in:
  superseded 2024 policies, an FAQ of 2024 that contradicts the 2025 policies, similar products, regional rules.
- **Ingestion**: structure-preserving extraction, cleaning, exact and near-duplicate removal, structure-aware chunks
  (at most 380 tokens, small sibling sections merged; in v2 an FAQ keeps one question per chunk): 853 chunks.
- **Retrieval**: multilingual-e5-large vectors in Qdrant + BM25, fused with RRF, re-scored by bge-reranker-v2-m3,
  top 5, current documents only. All local, $0.
- **Answer**: Claude Haiku 5.5 (effort low) with a JSON schema: claims, each with a source id and an exact quote. The
  code checks every quote against its chunk, drops claims without one, and cites the heading the quote stands under.
- **Versions**: answer prompts `prompts/rag/v1.md`, `v2.md`; judge prompts `prompts/judge/v1.md`, `v2.md`; query
  translation `prompts/query/v1.md`; each with a changelog. Every evaluation records the prompt version and the
  pipeline switches it ran with.

## Test sets

- **Retrieval** ([evals/retrieval_questions.yaml](evals/retrieval_questions.yaml)): 16 questions with the place of
  the answer (document + exact quote), checked against the top-10 of the search one by one; two runs of the
  results and the changes between them are in [history.md](evals/results/retrieval/history.md).
- **Answers** ([evals/testset.yaml](evals/testset.yaml)): 39 questions (19 Ukrainian, 11 English, 8 German, 1 mixed)
  with the reference answer, the facts it must contain (`must_include`), trap values it must not contain
  (`must_not_include`) and the documents it may cite. 21 traps (outdated FAQ, similar products, regional rules, a
  homonym, law vs. store), 11 plain questions, 3 partial (part of the question is not in the documents),
  4 unanswerable (including a prompt injection in the question), 6 phrased the way customers write (slang, typos,
  Ukrainian in Latin letters, an ambiguous question, an emotional one), and one prompt injection planted in a
  retrieved document. Every question was run through the system and its reference checked against the source text.
- **Judge labels**: 20 answers of v1 labelled by a person for calibration, and 10 fresh answers of v2 labelled the
  same way to check the judge on data it was not tuned on.

## Retrieval

Hybrid search plus the reranker was chosen in step 2 over vector-only, BM25-only and hybrid search, three embedding
models, three chunk sizes and four rerankers (README, "Index and retrieval"). Step 4 added two changes:

| Configuration (structure-aware chunks, hybrid + rerank) | hit@1 | recall@5 | MRR@10 | misses |
|---|---|---|---|---|
| step 2 (merged FAQ) | 0.75 | 0.94 | 0.84 | r16 |
| + one FAQ question per chunk | 0.81 | 0.94 | 0.88 | r16 |
| + query translation, each chunk reranked with the question in its own language | 0.75 | **1.00** | 0.88 | – |

The status filter keeps outdated policies out: without it, 2 outdated chunks reach the top 5 of the three
version-trap questions; with it, none.

## Answers: v1 → v2, one change at a time

Each change was switched on alone and measured on 39 questions × 3 runs.

| Step | pass | judge: correct | judge: score | "I don't know" though answerable | $ / 1,000 |
|---|---|---|---|---|---|
| 0. v1 | 0.75 | 0.62 | 0.71 | 0.23 | 0.36 |
| 1. + answer prompt v2 | 0.80 | 0.68 | 0.75 | 0.20 | 0.36 |
| 2. + language detection for short questions | 0.80 | 0.73 | 0.77 | 0.21 | 0.35 |
| 3. + one FAQ question per chunk | 0.86 | 0.81 | 0.83 | 0.15 | 0.38 |
| 4. + query translation | 0.89 | 0.80 | 0.85 | 0.10 | 0.50 |
| 5. + outdated FAQ moved last, with a note | 0.87 | 0.80 | 0.84 | 0.14 | 0.47 |
| 6. + threshold −6 and context filter | **0.90** | **0.82** | **0.86** | **0.06** | 0.53 |

Judge score = (correct + ½ partial) / answers. No step made the system answer an unanswerable question. Steps 4 and 5
differ partly by chance: the translation was generated anew in each run, so retrieval differed too; from step 5 on
translations are cached and every run sees the same retrieval.

By question type, v1 → v2: plain 0.61 → 0.82, traps 0.78 → 0.91, partial 0.78 → 1.00, unanswerable 1.00 → 1.00.
By language: German 0.88 → 1.00, English 0.88 → 1.00, Ukrainian 0.63 → 0.79. Every question gives the same result in
all three runs of v2 (in v1, four questions passed in some runs only).

## The LLM judge

Claude Haiku 5.5 grades each answer against the reference: correct, partial or incorrect, reason first.

| Judge | Labelled answers | Agreement with the person | Cohen's κ | Same label in 3 repeats |
|---|---|---|---|---|
| v1 | 20 (calibration) | 0.95 | 0.91 | 0.85 |
| v2 | 20 (calibration) | 1.00 | 1.00 | 1.00 |
| **v2** | **10 fresh answers** | **0.80** | **0.68** | 0.90 |

Judge v2 was written after v1 graded the whole test set: v1 graded three identical "I don't know" answers incorrect,
incorrect and partial, because two of its rules contradicted each other. Two of the three clarifications were written
while looking at calibration answers, so 1.00 on that set is optimistic; the fresh answers give the honest estimate,
0.80 / κ 0.68. Both disagreements there are known weaknesses: the judge accepted an answer that answered the literal
question but not what a Ukrainian customer needs (the clarification taken too far), and it called a true detail that
is not in the reference an error, because it sees the reference, not the sources.

The deterministic checks agree with the person on 0.65 of the calibration answers (judge: 0.95): they fail a correct
answer that mentions an outdated value, and pass an answer whose every fact is there but whose "not in the
documents" note is false. They catch numbers, sources, language and abstention; the judge catches meaning.

## Faithfulness

Two levels: the code checks that every quote is in the cited chunk word for word (all shown claims pass, by
construction), and an LLM reads each claim with the full text of the chunks it cites and says whether the claim
follows from them.

| | claims | supported | answers fully supported |
|---|---|---|---|
| v1 | 132 | 0.985 | 0.97 |
| v2 | 208 | 0.96 | 0.93 |

The checker is tested on control claims every run: 12 generated errors (a number changed, another question's claim
under these citations), 13 written subtle errors (another country, before/after swapped, "with" vs. "without" ANC,
a condition widened) and 6 correct restatements. It judged 12/12 and 6/6 in both runs, and 12/13 and 13/13 subtle
errors (it once missed "44 hours without ANC" for "44 hours with ANC"). v2 has more claims and more small additions
the source does not state ("the bank closes the plan *when the return is processed*").

## Error analysis

**1. "No" read as "I don't know" (t12, t27).** "Can I pay in instalments for a 1,000 UAH order?" and "How much are
delivery and installation of a washing machine in Odesa?" got "I don't know" in most v1 runs, although the context
had the answer at ranks 1–2 (instalments from 1,500 UAH; installation only in Kyiv, Lviv and Dnipro, delivery
400 UAH). The model treated "the condition is not met" as "no answer", and for a partly available service dropped the
whole answer. Fix: answer prompt v2, "'No' is an answer" and "answer every part the sources cover". Both 3/3 from
step 1 on.

**2. A merged FAQ under the threshold (t17, t18, t37).** The Ukrainian FAQ was one chunk of seven unrelated
questions. For "When is the phone hotline available?" the right question sat inside it, and the reranker scored the
whole chunk −6.5, below the −4 threshold: "I don't know" without a model call. Fix: one FAQ question per chunk. The
German FAQ entry on the hotline then scored −0.1, and t18 passed 3/3; retrieval hit@1 went from 0.75 to 0.81. Not
fixed: t17 ("where are your physical stores?"): the answer ("online only, no pick-up points") is in an FAQ entry
about self-pickup that the reranker still scores low, and the model, given it, says "I don't know".

**3. The answer only in another language (t16, t39).** An English question about instalments after a return has its
answer only in the Ukrainian policy; all 30 candidates of vector and BM25 search were English pages. Fix: the
question is rewritten in Ukrainian, English and German by one cheap model call, candidates are gathered with all
three, and the cross-encoder compares each chunk with the version in the chunk's language. r16/t16 found and answered
3/3. Not fixed: t39 (a dented washing machine): the "damaged on arrival" page is still not in the top 5.

**4. Two fixes made a trap worse (t05).** After steps 3 and 4, the outdated FAQ entry "free delivery from 2,000 UAH"
became its own chunk that matched the question almost word for word, and same-language reranking scored it 6.6 against
1.3 for the 2025 tariffs. In one run of three the model answered 2,000 UAH. The prompt rule "a policy wins over an
FAQ" was not enough against that gap. Fix in code: an FAQ older than a store policy of the same region in the same
context goes last, with a note that it is older; it is not dropped, because some answers exist only in an FAQ.
t05 back to 3/3. Lesson: measuring every change on its own is what showed that a fix for one error opened another.

**5. A lower threshold trades "I don't know" for wrong sources (t34, t39), open.** With translation the best scores
shifted; the table of thresholds against the test set showed −6 as the point where no answerable question is stopped
before the model. False "I don't know" fell from 0.14 to 0.06, and the model still refused all unanswerable questions
that now reach it. But two questions that used to get "I don't know" now get answers from law articles that do not
fit: "what if I threw the box away?" is answered with a rule for contracts signed outside a shop, which suggests the
box does not matter, while the store policy requires the original packaging. The judge grades both incorrect, and
this is worse than "I don't know". A check that a source is about the customer's situation before answering would
be the next step.

**Also found.** The first CI run found source ids ("S4") in 4 of 33 answers, which never happened in the three
evaluation runs: a prompt rule lowers the chance and does not guarantee it, so the code now replaces ids with document
titles. The model sometimes copies a quote with one letter changed, and the exact quote check then drops a correct
claim (twice in the several hundred answers of these evaluations); not fixed. The first CI run also failed because a test needed an API key that the
test job does not have.

## Cost and latency

v2 costs **$0.53 per 1,000 questions**: $0.10 for the query translation and $0.43 for the answer (Claude Haiku 5.5,
$0.10 / $0.50 per million input / output tokens; about 3,600 input and 400 output tokens per answer, thinking
included; the system prompt is cached). Retrieval runs locally. An evaluation of the test set costs $0.06 (3 runs), the
judge $0.015 and the faithfulness check $0.025. On a laptop CPU a question takes about 5 s of retrieval (the reranker)
plus 1.5 s at the median for the answer (4.7 s at p95); on a CI runner the reranker is three to four times slower, and
a CI run takes about 20 minutes.

## Limitations

- **The test set is written from inside.** The questions were written knowing the corpus and its traps, and are
  mostly clean, single-step questions. On the six questions phrased the way customers write, v1 failed three; real
  traffic would score lower than the 0.90.
- **Small sample.** 39 questions: the 95% interval of v2's pass rate is 0.80–0.97; differences under about 0.1
  between two configurations are not significant.
- **The judge is the same model family as the system**, and it sees the reference answer, not the sources. Its
  agreement with a person on fresh answers is 0.80 (κ 0.68), not the 1.00 of the calibration set.
- **The faithfulness checker misses some subtle errors** (1 of 13 written controls in one run).
- **Questions the corpus answers only by omission** ("do you ship to Japan?", answered by a closed list of countries
  that does not name Japan) fail at retrieval: t28 is wrong in every configuration.
- **Latency** is dominated by the CPU reranker.

## What next

A relevance check of the retrieved sources against the customer's situation before answering (error 5); a tolerant
quote match (one or two changed characters); an FAQ entry scored by its question, not its answer (t17); questions from
real support traffic in the test set; a judge that sees the cited sources.

## Reproduce

```bash
python -m src.rag data && python -m src.rag index        # corpus, chunks, index
python -m src.rag eval-retrieval                         # retrieval comparison (README tables)
python -m src.rag eval --tag v2                          # 39 questions x 3 runs, deterministic checks
python -m src.rag judge --tag v2                         # LLM judge (prompt v2)
python -m src.rag faithfulness --tag v2                  # faithfulness + control claims
python -m src.rag judge-calibrate [--holdout]            # judge vs. the human labels
python -m src.rag ci-check --answers v2 --retrieval none # the CI gates
```

Results of every run quoted here are in [evals/results/](evals/results/): `answers/v1_2` (step 0), `v2-prompt`,
`v2-lang`, `v2-faq`, `v2-translation`, `v2-outdated-faq`, `v2-threshold` (final); `judge/` (calibration and fresh
answers); `retrieval/` (step 2 and the step 4 runs).
