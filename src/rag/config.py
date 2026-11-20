"""Paths and ingestion parameters for the RAG pipeline."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "rag"

CATALOG = DATA / "catalog.yaml"        # every document and its metadata
AUTHORING = DATA / "authoring"         # markdown sources of the synthetic store documents
RAW = DATA / "raw"                     # the corpus as the pipeline sees it: .md / .docx / .html / .pdf
CACHE = DATA / ".cache"                # extracted text per file hash (git-ignored): incremental runs

MANIFEST = DATA / "manifest.json"      # one record per file: hashes, status, metadata, chunk count
CHUNKS = DATA / "chunks.jsonl"         # structure-aware chunks: the index is built from these
CHUNKS_FIXED = DATA / "chunks_fixed.jsonl"   # fixed-size baseline, kept for the retrieval comparison
INGEST_REPORT = DATA / "ingest_report.json"  # dedup, language checks, chunking comparison

# Bump when extraction or normalization changes: cached texts are then re-extracted.
PIPELINE_VERSION = "ingest-v1"
CHUNKER_VERSION = "chunker-v3"   # v2: merged chunks name every merged section in their label;
                                 # v3: an FAQ keeps one question per chunk (FAQ_CHUNKS)

# Token counting. o200k_base splits Cyrillic and German far better than cl100k_base, so a token budget
# means roughly the same amount of text in all three corpus languages. It is an offline approximation;
# the embedding model has its own tokenizer with a 512-token window, and 300 tokens here stay well inside it.
TOKENIZER = "o200k_base"

# Structure-aware chunking (see README, "Chunking strategy").
CHUNK_MAX_TOKENS = 380   # one chunk = one section or a part of it; with the header it stays under the 512-token
                         # window of the embedding model (measured: at most 472 XLM-R tokens)
CHUNK_MIN_TOKENS = 150   # sibling sections smaller than this are merged (chosen by the size sweep in step 2)

# Fixed-size baseline for the comparison.
FIXED_TOKENS = 300
FIXED_OVERLAP = 50

NEAR_DUP_JACCARD = 0.8    # word 5-shingle overlap above which two documents are near-duplicates
MIN_CHARS_PER_PAGE = 50    # a PDF page with less text has no usable text layer (needs OCR)
LANG_MIXED_WARN = 0.2      # warn when more than this share of a document's paragraphs is in another language

# ---------------------------------------------------------------- step 2: index and retrieval
MODELS_DIR = ROOT / ".models"                 # downloaded ONNX models (git-ignored)
INDEX_DIR = DATA / ".index"                   # on-disk Qdrant collections (git-ignored, rebuilt from chunks)
EMBED_CACHE = CACHE / "embeddings"            # vectors by sha256(model + text): unchanged chunks are never re-embedded
EVALS = ROOT / "evals"
RETRIEVAL_QUESTIONS = EVALS / "retrieval_questions.yaml"
RETRIEVAL_RESULTS = EVALS / "results" / "retrieval"

EMBED_MODEL = "e5-large"       # key in src/rag/embeddings.py MODELS; chosen by the comparison in README
RERANK_MODEL = "bge-m3"        # key in src/rag/retrieve.py RERANKERS
CANDIDATES = 30                # how many hits each of vector / BM25 contributes to the fusion
RERANK_CANDIDATES = 20         # how many fused hits the cross-encoder re-scores
RRF_K = 60                     # Reciprocal Rank Fusion constant
TOP_K = 5                      # hits returned / evaluated (recall@5)

# ---------------------------------------------------------------- step 3: answers with sources
PROMPTS_DIR = ROOT / "prompts" / "rag"        # v1.md, v2.md, ... + CHANGELOG.md
PROMPT_VERSION = "v1"
ANSWER_MODEL = "claude-haiku-5-5"
ANSWER_EFFORT = "low"          # Haiku 5.5 default is medium; short grounded answers need little reasoning
ANSWER_MAX_TOKENS = 4000       # thinking + the JSON answer; a cut answer (stop_reason=max_tokens) is not used
CONTEXT_BUDGET = 2000          # o200k tokens of retrieved text sent to the model (about 5 chunks)
MIN_RERANK_SCORE = -6.0        # best reranker score below this: nothing relevant was found, answer "I don't know"
                               # without calling the model. -4.0 until step 4; with translated queries the lowest
                               # score of an answerable test question is -5.7, so -6.0 lets every one of them reach
                               # the model, and the model decides on the unanswerable ones (step 4, threshold table)
PRICE_PER_MTOK = {"claude-haiku-5-5": (0.10, 0.50)}   # USD per million input / output tokens (prompts up to 100K)

# Fixes from the error analysis of v1 (step 4). Each one is a switch, so every step of the evaluation can be
# reproduced; the evaluation records the switches it ran with.
QUESTION_LANGUAGE = "v2"       # v1: detect() made for paragraphs; v2: detect_question() for short questions and
                               # Ukrainian in Latin letters
FAQ_CHUNKS = "per_question"          # merged: small sibling sections merged like any document; per_question: one
                               # FAQ question per chunk (needs `python -m src.rag ingest` and `index`)
QUERY_TRANSLATION = True       # rewrite the question in uk / en / de (one model call) and search with all three
QUERY_PROMPTS_DIR = ROOT / "prompts" / "query"
QUERY_PROMPT_VERSION = "v1"
TRANSLATION_CACHE = ROOT / "evals" / "translations.json"   # None: translate every time; a path: reuse a
                               # translation of the same question (stable evaluation runs)
CONTEXT_MIN_SCORE = -6.0       # None: the top-5 go to the model; a number: hits scoring below it are left out
DEMOTE_OUTDATED_FAQ = True     # an FAQ older than a store policy in the same context goes last, with a note

# ---------------------------------------------------------------- step 4: answer evaluation
TESTSET = EVALS / "testset.yaml"
ANSWER_RESULTS = EVALS / "results" / "answers"     # one folder per prompt version (or --tag)
EVAL_RUNS = 3                  # each question is answered this many times: the model is not deterministic
EVAL_WORKERS = 4               # parallel model calls (retrieval runs once per question, before them)

# LLM judge: grades an answer against the reference answer (correct / partial / incorrect)
JUDGE_PROMPTS_DIR = ROOT / "prompts" / "judge"
JUDGE_PROMPT_VERSION = "v2"   # v1 -> v2: see prompts/judge/CHANGELOG.md
JUDGE_MODEL = "claude-haiku-5-5"
JUDGE_EFFORT = "medium"        # grading needs more care than answering
JUDGE_CALIBRATION = EVALS / "judge_calibration.yaml"   # answers labelled by a person
JUDGE_HOLDOUT = EVALS / "judge_holdout.yaml"           # fresh answers labelled by a person: the judge was not
                                                      # tuned on them
JUDGE_RESULTS = EVALS / "results" / "judge"

# Faithfulness: is every claim supported by the sources it cites (checked per claim by an LLM)
FAITHFULNESS_PROMPTS_DIR = ROOT / "prompts" / "faithfulness"
FAITHFULNESS_PROMPT_VERSION = "v1"
FAITHFULNESS_CONTROLS = EVALS / "faithfulness_controls.yaml"   # written control claims
