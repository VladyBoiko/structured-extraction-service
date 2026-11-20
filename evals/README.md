# Evals

## Retrieval test set (step 2)

[retrieval_questions.yaml](retrieval_questions.yaml) holds 16 questions (6 Ukrainian, 4 German, 5 English, 1 mixed),
each with the place in the corpus where the answer is.

| Field | Meaning |
|---|---|
| `question` | the customer question sent to the search |
| `language` | `uk`, `de`, `en` or `mixed`, for the per-language breakdown |
| `evidence` | acceptable answers: a document (`doc`) and an exact `quote` from it. Several entries = the same answer in several documents (the policy and its English overview, a law and the directive behind it) |
| `trap` | what makes the question hard (outdated FAQ, a similar product, another language, a homonym) |
| `superseded` | outdated versions that contain a competing answer; used by the status-filter experiment |

A retrieved chunk is relevant when it comes from the `doc` of an evidence entry and contains its `quote` (whitespace is
ignored). Gold is defined by quotes, not by chunk ids, so the same questions judge the structure-aware and the
fixed-size chunks fairly: a fixed window that cuts the quote in half does not count. A question is a hit at k when at
least one relevant chunk is in the top-k.

Run: `python -m src.rag eval-retrieval` (add `--sweep` to repeat the chunk size and reranker comparisons, which
re-embed and take minutes). It stops with an error if a quote is not found in its document.

Results:

- [results/retrieval/results.md](results/retrieval/results.md): metrics of every configuration and the rank of the
  first relevant chunk per question;
- [results/retrieval/per_question.md](results/retrieval/per_question.md): per question, the gold chunks and the top-5
  of the chosen configuration.

## Answer test set (step 4)

[testset.yaml](testset.yaml) holds 39 questions (19 Ukrainian, 11 English, 8 German, 1 mixed): 21 traps, 11 plain,
3 partial, 4 unanswerable; 6 of them phrased the way customers write; one with a prompt injection planted in a
retrieved document (`inject`). Fields (also explained at the top of the file):

| Field | Meaning |
|---|---|
| `expect` | `answer` or `not_found` ("I don't know") |
| `type` | `answerable`, `trap`, `partial`, `unanswerable` |
| `expected_answer` | the reference answer, for the judge |
| `must_include` | key facts; `"a \| b"` = any of the alternatives; case, spaces in numbers and the decimal sign are ignored |
| `must_not_include` | trap values that must not appear |
| `expected_sources` | documents an answer may cite |
| `known_issue` | a failure found before the fixes, and its cause |

| File | What |
|---|---|
| [judge_calibration.yaml](judge_calibration.yaml) | 20 answers of v1 labelled by a person (correct / partial / incorrect), to calibrate the LLM judge |
| [judge_holdout.yaml](judge_holdout.yaml) | 10 fresh answers of v2 labelled the same way: a check of the judge on answers it was not tuned on |
| [faithfulness_controls.yaml](faithfulness_controls.yaml) | claims that differ from their source in one detail (must be rejected) and correct restatements (must be accepted) |
| [translations.json](translations.json) | cached query translations: evaluation runs see the same retrieval |
| [ci_thresholds.yaml](ci_thresholds.yaml), [baseline.json](baseline.json) | CI quality gates and the regression baseline |

Commands: `python -m src.rag eval` (3 runs, deterministic checks), `judge`, `faithfulness`, `judge-calibrate
[--holdout]`, `ci-check`. Each run writes to a new folder or file under [results/](results/) and never overwrites an
earlier one:

| Results | Run |
|---|---|
| `results/answers/v1`, `v1-rescored` | prompt v1, the first 33 questions |
| `results/answers/v1_2` | prompt v1, all 39 questions: the baseline of step 4 |
| `results/answers/v2-prompt`, `v2-lang`, `v2-faq`, `v2-translation`, `v2-outdated-faq` | one fix added at a time |
| `results/answers/v2-threshold` | the final configuration (also `evals/baseline.json`) |
| `results/judge/calibration_v1`, `calibration_v2`, `holdout_v2` | the judge against the human labels |

