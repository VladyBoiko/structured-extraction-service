# Query translation prompts: changelog

The system prompt that rewrites a customer question in Ukrainian, English and German before retrieval
(`QUERY_TRANSLATION` in `src/rag/config.py`). Retrieval searches with every version and the reranker compares each
chunk with the version in the chunk's language.

## v1

Added in step 4 for the cross-lingual misses of the v1 evaluation: a question in one language whose answer is only in
a document in another (t16, t18, t39), and Ukrainian written in Latin letters (t37). Also normalizes spelling and
abbreviations, and drops emotions while keeping the facts of the situation.
