# Judge prompts: changelog

The system prompt of the LLM judge (`python -m src.rag judge`, `judge-calibrate`). The version in use is
`JUDGE_PROMPT_VERSION` in `src/rag/config.py`. Each version is calibrated on the answers labelled by a person in
`evals/judge_calibration.yaml`; results in `evals/results/judge/`.

## v1

Labels correct / partial / incorrect with the same definitions as the human labels; the reference answer is the
truth; content, not style; details of the reference the customer did not ask about are not required; reason first.

## v2

Two problems seen when v1 graded the whole test set:

- **A contradiction.** "I don't know" when the documents answer the question was both "partial" (a false "not in the
  documents") and "incorrect" ("I don't know" when the reference has an answer): three identical "I don't know"
  answers to t28 were graded incorrect, incorrect and partial. v2 says that an answer that is only "I don't know" is
  incorrect, and the "partial" rule is for a note inside an answer that answers the question.
- **Context of the reference counted as missing.** "Instalments are not available in Germany" was graded partial
  because it did not add "only in Ukraine" (t20). v2 says that what the customer needs is what the question asks.

One more clarification, from the only disagreement in the v1 calibration (t01): a value the reference calls outdated
is wrong only when given as valid for the same thing; the legal minimum of 14 days next to the store's 30 days is not
the outdated 14 days of the FAQ.
