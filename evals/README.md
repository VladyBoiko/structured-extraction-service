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
