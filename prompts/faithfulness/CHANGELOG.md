# Faithfulness prompts: changelog

The system prompt of the faithfulness check (`python -m src.rag faithfulness`): for each claim of an answer, is it
supported by the full text of the chunks it cites? The version in use is `FAITHFULNESS_PROMPT_VERSION` in
`src/rag/config.py`. Each run also checks control claims (real claims with a number changed, or with the claim of
another question under the same citations) that must be rejected.

## v1

Supported = every number, condition, product, country, period and exception of the claim is in its cited sources;
translation, rewording and direct inferences are fine. Not supported = missing, contradicted, mixed up with another
thing the source keeps apart, or a condition made stricter or looser. Each claim only against its own sources.
On the v1 answers: 12 of 12 control claims rejected.
