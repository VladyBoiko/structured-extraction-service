# Structured Extraction Service

Turns messy customer support tickets of an online electronics store into validated JSON and measures which model and prompt
do it best. A cloud model (Claude Haiku 5.5) and a local model (Qwen2.5 3B via Ollama) run behind one interface and are
compared on field accuracy, share of valid answers, latency and cost.

> **Block 2 of the course project**, a RAG system that answers support questions from the store's documents with sources,
> lives in the same repository and runs separately: see [RAG over the support corpus](#rag-over-the-support-corpus-block-2).
> None of its commands run the block 1 extraction.

## Input

`data/texts/` holds 75 synthetic tickets, one `<id>.txt` file each. They are deliberately messy: different lengths, typos,
slang, missing details, English mixed with Ukrainian and German, long emails with signatures, spam, and even instructions
aimed at the model. Order numbers (`ES-xxxxx`) are fictional; there is no personal data.

```text
data/texts/t09.txt
Hi team, навушники JBL Tune 760NC прийшли з подряпиною на корпусі and the left ear is silent. Order ES-49877.
Хочу обмін, bitte schnell, у мене це подарунок на завтра зранку!
```

`data/golden/` holds reference labels for 30 of the tickets, one `<id>.json` per ticket with the same name as the text
(`golden/t09.json` labels `texts/t09.txt`).

Labeling rules: [data/LABELING_GUIDE.md](data/LABELING_GUIDE.md).

## Output schema

Defined with Pydantic in [src/schema.py](src/schema.py) and sent to both models as JSON Schema.

| Field | Type | Values |
|---|---|---|
| `category` | enum | what the problem is about: `order_status`, `order_change`, `delivery`, `payment`, `product_defect`, `usage_help`, `product_question`, `account`, `other` |
| `priority` | enum | `low`, `medium`, `high`, `urgent` |
| `sentiment` | enum | `negative`, `neutral`, `positive` |
| `language` | enum | `en`, `uk`, `de`, `mixed` |
| `requested_action` | enum | what the customer wants done: `refund`, `replacement`, `repair`, `cancellation`, `information`, `other`, `none` |
| `needs_human` | bool | whether a support agent has to act |
| `escalation_threat` | bool | the customer threatens a complaint, legal action, a chargeback or a public review |
| `repeat_contact` | bool | the customer already contacted support about this issue |
| `deadline` | string or null | a time limit the customer states, as written ("tomorrow noon") |
| `tracking_number` | string or null | parcel tracking number; never the order number |
| `order_id` | string or null | order number in the form `ES-12345` |
| `summary` | string | one English sentence, 1-200 characters |
| `products` | list of objects | every product the ticket is about, each with `name` (string or null) and `category` (enum: `smartphone`, `laptop`, `tv`, `headphones`, `tablet`, `appliance`, `accessory`, `other`, `unknown`); empty if none |

Expected output for the ticket above:

```json
{
  "category": "product_defect",
  "priority": "urgent",
  "sentiment": "negative",
  "language": "mixed",
  "requested_action": "replacement",
  "needs_human": true,
  "escalation_threat": false,
  "repeat_contact": false,
  "deadline": "на завтра зранку",
  "tracking_number": null,
  "order_id": "ES-49877",
  "summary": "JBL Tune 760NC from order ES-49877 arrived scratched with a silent left ear; customer wants a fast exchange.",
  "products": [{"name": "JBL Tune 760NC", "category": "headphones"}]
}
```

## How it works

1. Every configuration in [config.yaml](config.yaml) (model + sampling parameters) processes every ticket with the system
   prompt from `prompts/<version>.md`.
2. Structured output: the cloud model gets the schema as a forced tool call, the local model through Ollama's `format`.
3. Each answer is validated with Pydantic:
   - timeouts, network errors, 429 and 5xx are retried up to 2 times with backoff;
   - errors a retry cannot fix (other 4xx, context overflow, no tool call in the answer) fail immediately;
   - a schema-invalid answer is sent back once for repair, then the ticket is marked `failed`.
4. Every result is saved with the model, prompt version, sampling parameters, tokens, latency and cost.
5. Metrics are computed on the golden set and written next to the results.

## Setup

Requirements: Python 3.11+, an Anthropic API key, and [Ollama](https://ollama.com) for the local model.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip install -r requirements.txt
cp .env.example .env                             # then put your ANTHROPIC_API_KEY into .env
ollama pull qwen2.5:3b                           # local model, ~2 GB
```

A full run of 75 tickets costs about one cent on the API.

## Run

```bash
python main.py            # or: make run
```

Other commands:

```bash
python main.py --run cloud_default --limit 3   # one configuration, first 3 tickets
python main.py --report-only                   # recompute metrics for the latest run without calling models
python -m src.errors                           # differences from the golden set per configuration (make errors)
python -m pytest -q                            # offline tests, no API needed (make test)
python main.py --config config.smoke.yaml      # pipeline check on a fake model (make smoke)
```

If the API key is missing or Ollama is not running, that configuration is skipped with a message and the others still run.

## Results

Each run creates `results/<YYYY-MM-DD_HH-MM-SS>__<prompt>/` and never overwrites earlier runs:

- `<configuration>.jsonl` - one record per ticket: `id`, `run`, `provider`, `model`, `prompt_version`, `temperature`,
  `top_p`, `options`, `timestamp`, `status` (`ok` / `failed`), `output` (validated JSON), `raw` (model text), `error`,
  `attempts`, `repairs`, `latency_s`, `input_tokens`, `output_tokens`, `cost_usd`;
- `metrics.json` and `metrics.md` - the comparison tables: run metrics over all tickets (validity, latency, cost), accuracy
  on the golden set and per-field accuracy.

Metric definitions: [docs/METRICS.md](docs/METRICS.md).
Comparison of the models and prompts, error analysis and the production choice: [REPORT.md](REPORT.md).

## Configuration

[config.yaml](config.yaml) holds the prompt version, data paths, timeout, retry and repair limits, `max_tokens`, and the list
of configurations. Each configuration sets `provider`, `model`, `temperature`, `top_p`, provider `options` and token prices.

| Configuration | Model | Sampling |
|---|---|---|
| `cloud_default` | Claude Haiku 5.5 | `effort: medium`; the model does not accept temperature/top_p |
| `local_t0` | qwen2.5:3b | temperature 0.0, top_p 1.0 |
| `local_t07` | qwen2.5:3b | temperature 0.7, top_p 0.9 |

## Project structure

| Path | Contents |
|---|---|
| `main.py` | entry point |
| `src/schema.py` | output schema |
| `src/providers.py` | common model interface: Anthropic, Ollama, mock |
| `src/pipeline.py` | run loop, retries, timeout, validation, saving |
| `src/metrics.py` | accuracy, validity, latency, cost |
| `src/errors.py` | error analysis against the golden set |
| `prompts/` | versioned system prompts and [CHANGELOG.md](prompts/CHANGELOG.md) |
| `data/texts/`, `data/golden/` | input tickets and reference labels |
| `docs/METRICS.md` | metric definitions |
| `REPORT.md` | results, error analysis, production choice |
| `results/` | model outputs and metrics per run |
| `tests/` | pytest suite |

---

## RAG over the support corpus (block 2)

A support agent asks a question in Ukrainian, English, German or a mix ("Скільки днів на повернення в Австрії?") and gets
an answer built only from the store's documents, with the document and section cited for every claim, or "not in the
documents" when the corpus has no answer. Block 3 will put an agent on top of this corpus.

Pipeline: documents (PDF / DOCX / HTML / Markdown) → cleaning → chunks + metadata → vector store (hybrid search +
reranking) → answer with sources → evals in CI. **Steps 1–3 are implemented** (corpus, ingestion, chunking; index, hybrid search,
reranking, filters, retrieval evaluation; answers with verified citations and "I don't know"); evals in CI are next.

### Run

```bash
pip install -r requirements.txt
python -m src.rag data          # or: make rag-data
```

| Command | What it does |
|---|---|
| `python -m src.rag build-store` | renders the store documents from `data/rag/authoring/*.md` into `.md` / `.docx` / `.html` |
| `python -m src.rag download` | fetches the 15 external documents (manuals, spec sheets, law) into `data/rag/raw/external/` |
| `python -m src.rag ingest` | extract → clean → deduplicate → chunk → `data/rag/chunks.jsonl` + `manifest.json` (incremental) |
| `python -m src.rag ingest --full` | the same, ignoring the extraction cache |
| `python -m src.rag data` | all three in order (`make rag-data`) |

A full ingestion takes about 20 seconds (most of it on the three 140–180-page PDF manuals); a repeated run reuses the
cache in `data/rag/.cache/` and takes a few seconds.

### Corpus

51 documents (54 files: 3 are planted duplicates), about 230,000 tokens. Every document is in one language; mixed
language is left for the questions.

| | Count |
|---|---|
| Format | HTML 21, Markdown 13, DOCX 9, PDF 8 |
| Language | English 20, German 16, Ukrainian 15 |
| Type | store policies 26, law 7, manufacturer spec sheets 5, product pages 4, FAQ 3, service 3, manufacturer manuals 3 |
| Region | Ukrainian store 15, all regions 13, German/Austrian/Swiss store 10, manufacturer 8, EU law 3, German law 2 |

**Store documents (36)** are synthetic, like the tickets of block 1: return, warranty, delivery, payment, loyalty,
privacy and other policies, FAQs and product pages of the fictional ElectroStore (orders `ES-xxxxx`, Ukraine + DACH).
They are written once in `data/rag/authoring/` and published by `build-store` in the format a store would use: Word
files with real Title/Heading/List/Table styles, and HTML pages with navigation, a cookie banner, breadcrumbs, a
related-articles box and a footer around the article. So the ingestion has to undo real page chrome.

**External documents (15)** are public and are downloaded, not committed: JBL spec sheets (PDF, EN/DE), Sony help guides
for WH-1000XM5 and WF-1000XM5 (PDF, EN/DE, 144–181 pages), the Ukrainian consumer protection law and Cabinet resolution
No. 172 (zakon.rada.gov.ua), EU directives 2011/83 (EN/DE) and 2019/771 (EUR-Lex), BGB §§ 312g and 355
(gesetze-im-internet.de). The catalog pins the URL and SHA-256 of every file; a changed hash means the publisher
updated the document.

**Traps built into the corpus** (the test set in step 4 asks about them):

| Trap | Documents |
|---|---|
| Outdated versions | returns UA 2024 → 2025 (14 → 30 days, refund 10 → 7 days), delivery UA 2024 → 2025 (free from 2,000 → 3,000 UAH), loyalty 2024 → 2025 (Gold 10% → 7%). The old versions stay in the corpus with `status: superseded` |
| Similar products | JBL Tune 760NC / 770NC / 520BT; Sony WH-1000XM5 (over-ear, not waterproof) / WF-1000XM5 (in-ear, IPX4) |
| Regional rules | the same topic for Ukraine and for DACH with different terms: returns, warranty, delivery; price guarantee exists only in DACH, trade-in only in Ukraine |
| Conflicting sources | the Ukrainian FAQ (May 2024) still says 14 days and free delivery from 2,000 UAH; store policy vs. the statutory minimum in the law |
| Duplicates | an exact copy with other line endings, the same FAQ exported from an old CMS template, an unpublished draft with two edits |

All metadata lives in one place, [data/rag/catalog.yaml](data/rag/catalog.yaml): type, topic, language, region, version,
effective date, status and `superseded_by`, plus URL and SHA-256 for external files.

### Ingestion

| Stage | What happens |
|---|---|
| Extract | **PDF**: `pymupdf4llm` turns font sizes into headings and keeps tables as markdown; pages stay separated. **HTML**: scripts, navigation, header, footer, cookie banners, breadcrumbs and asides are removed, the content root is found, and blocks are walked in order. Site rules: EUR-Lex `Article 9` + `Right of withdrawal` → `### Article 9 — Right of withdrawal`, numbered points laid out as 2-column tables → list items, footnotes dropped; zakon.rada `Розділ` / `Стаття N.` → headings; gesetze-im-internet `<dl>` lists. **DOCX**: the body is walked in order, Title/Heading styles → headings, list styles → list items, tables → markdown; the page header and footer are outside the body and are ignored. **Markdown**: encoding detected |
| Clean | Unicode NFKC (keeping `№`), CRLF → LF, zero-width characters and soft hyphens removed; running headers and footers removed (lines that repeat at the edges of 25%+ of pages: Sony's "Help Guide / model name", copyright lines); page numbers; words hyphenated across lines rejoined; lines a PDF wrapped inside a sentence rejoined; "Related Topic" link lists and table-of-contents link lines dropped; zakon.rada editorial notes `{Із змінами, внесеними згідно…}` dropped |
| Deduplicate | **Exact**: SHA-256 of the normalized text with whitespace collapsed: the CRLF copy and the old-CMS export are dropped. **Near**: Jaccard similarity of word 5-shingles ≥ 0.8: the draft (0.886) is dropped. Two catalogued *versions* of one policy would be kept on purpose, because retrieval needs both and filters by `status` |
| Check language | each document's language is detected and compared with the catalog, and the share of paragraphs in another language is measured (warning above 20%). All 51 documents pass: none is mixed |
| Chunk | structure-aware, see below; the fixed-size baseline is written too, for the comparison in step 2 |
| Record | `chunks.jsonl`, `manifest.json` (per file: hashes, ingest status, metadata, detected language, token and chunk counts, dataset version), `ingest_report.json` (dedup decisions, language checks, chunking statistics) |

Every chunk in [data/rag/chunks.jsonl](data/rag/chunks.jsonl) carries: `chunk_id` (`returns_ua_2025#001`), `doc_id`,
`source`, `title`, `section` (heading path; for merged sections all of them, e.g. `Правила повернення товару (Україна) > 4. Повернення коштів / 5. Товари, які не можна повернути / 6. Товар неналежної якості`),
`format`, `doc_type`, `topic`, `language`, `region`, `version`, `effective_date`, `status`, `superseded_by`, `url`,
`doc_hash`, `n_tokens`, `text`, `pipeline_version`.

### Chunking strategy

**Choice: structure-aware chunks of at most 380 tokens, cut along headings, never inside a paragraph, list item, table
row or sentence; neighbouring sections shorter than 150 tokens are merged.** The size was chosen by measuring retrieval
(step 2, below), not guessed.

Why this way of cutting, for these documents:

- **Every document is already divided by meaning.** A policy has one section per rule ("Rücksendekosten", "Строк
  повернення"), a law has articles, a manual has one topic per page. A support question almost always targets one
  rule or two neighbouring ones, so whole sections are the natural unit to retrieve.
- **The section is the citation.** Step 3 has to cite the document *and the section* for every claim. Every chunk is a
  whole section, a part of one, or several whole neighbouring sections, and its `section` label names exactly what it
  holds ("Правила повернення товару (Україна) > 1. Строк повернення / 2. Як оформити повернення / 3. Вартість доставки
  повернення"). A fixed window that starts in the middle of one section and ends in the next has no section to cite.
- **Tables carry the answers.** Return shipping costs per country, delivery prices, instalment plans and battery times
  are tables. A row without its header loses its meaning, so a table is split only between rows, and every piece
  repeats the header row.
- **Headings give the context the text lacks.** "Up to 24 instalments" says nothing about the store's payment rules
  without "Оплата частинами". Each piece repeats its section heading, and the document title + section path is put in
  front of the text for embedding, BM25 and reranking (a contextual chunk header).

Why this size:

- **Small sections are merged because questions span them.** Store sections have a median of 70–90 tokens. Cut one by
  one, "Gold status" (the discount table) and "sale items are excluded" (the next section) land in different chunks, and
  "why did my Gold discount not apply to a sale item?" matches neither well. Merging neighbours below 150 tokens turns a
  small policy into 1–3 chunks of whole sections. In the retrieval sweep this was the difference between missing that
  question and finding it at rank 1 (table below).
- **380 is the most the embedding model can read.** e5-large reads 512 tokens of its own tokenizer (XLM-R), which
  counts up to 1.3x the o200k tokens we budget in. Measured over the corpus, the longest chunk with its header is 472
  XLM-R tokens, so nothing is truncated. Long law articles and manual topics (one in ten is longer than 850–1,600
  tokens) are split along paragraphs into pieces that each still hold a full rule with its condition.
- **It fits the answer step.** The context budget in step 3 is about 1,500–2,000 tokens: 5 chunks of this size.
- There is no overlap: the boundaries follow the structure, and the repeated heading does what overlap does for fixed
  windows.

**Comparison with a fixed window** (300 tokens, 50 overlap, same tokenizer, a similar average size) on the whole corpus
and on one document of each kind. "Starts mid-sentence": the chunk body does not begin at a line or sentence start of
the document. "Cut tables": a table row is broken or rows lost their header. "Several sections": body text of one
section is followed by the heading of another; for structure-aware chunks these are whole merged sections, all named in
the label; for fixed windows they are pieces of sections, labelled only by the section where the window starts.

| | Structure-aware 380 / merge < 150 | Fixed 300/50 |
|---|---|---|
| chunks | 834 | 938 |
| average / median tokens | 282 / 309 | 293 / 300 |
| start mid-sentence | 1 (0.1%) | 835 (89%) |
| cut tables | 2 | 17 |
| several sections | 169 (20%, whole sections) | 475 (51%, cut sections) |

| Document (tokens) | Chunks (struct / fixed) | Mid-sentence starts | Cut tables | Several sections |
|---|---|---|---|---|
| returns_ua_2025, md (552) | 2 / 3 | 0 / 2 | 0 / 1 | 2 / 2 |
| delivery_dach, docx (319) | 1 / 2 | 0 / 1 | 0 / 0 | 1 / 2 |
| payment_ua, html (312) | 1 / 2 | 0 / 1 | 0 / 0 | 1 / 2 |
| jbl_tune_770nc_spec_en, pdf (1,193) | 4 / 5 | 0 / 4 | 0 / 0 | 3 / 5 |
| sony_wf1000xm5_help_guide_en, pdf (42,572) | 156 / 171 | 0 / 156 | 0 / 6 | 20 / 100 |
| eu_directive_2011_83_consumer_rights_en, html (17,822) | 63 / 72 | 0 / 70 | 0 / 0 | 13 / 27 |

An example from `returns_ua_2025`: the structure-aware chunk `#000` holds sections 1–3 whole and names all three;
`#001` holds sections 4–6. Fixed chunk `#000` runs from the title into the return-shipping table of section 3 and stops
right after the table's header row; fixed chunk `#001` starts mid-sentence in section 2 ("у будь-якому відділенні Нової
Пошти…"), holds sections 3 to 6, and is labelled "2. Як оформити повернення", so an answer about return shipping costs
would cite the wrong section.

On retrieval quality the two strategies end up equal with the full pipeline (hybrid + reranking: MRR 0.84 for both),
and structure-aware chunks are ahead without the reranker in recall (vectors 0.94 vs 0.88, hybrid 0.88 vs 0.81). With
equal retrieval, the exact citations and whole tables decide.

### Index and retrieval

```bash
python -m src.rag index                                    # embed chunks, build the Qdrant collections
python -m src.rag search "Was kostet die Rücksendung nach Österreich?"
python -m src.rag search "return window" --region UA INTL --all-versions --mode hybrid
python -m src.rag eval-retrieval                           # recall@5 / MRR on evals/retrieval_questions.yaml
python -m src.rag eval-retrieval --models minilm mpnet e5-large --sweep   # + model, size and reranker comparisons
```

The first run downloads the models (about 3 GB into `.models/`) and embeds the corpus (about 4 minutes on a laptop
CPU); later runs reuse both.

| Part | Implementation |
|---|---|
| Embeddings | `intfloat/multilingual-e5-large` (1024 dims) via fastembed, ONNX on CPU, local and free; `query:` / `passage:` prefixes as the model was trained. Vectors are cached by sha256(model + text) in `data/rag/.cache/embeddings/`: unchanged chunks are never embedded again |
| Vector store | Qdrant in embedded mode, stored in `data/rag/.index/`. The collection name carries a fingerprint of the chunks and the model, so a changed corpus gets a fresh collection and an unchanged one is reused |
| Lexical search | BM25 (rank-bm25) over the same header + text; words cut to 6 characters as a crude stemmer for uk/de/en ("повернення"/"повернути" → "поверн") |
| Fusion | Reciprocal Rank Fusion of the top-30 of each search (ranks, not scores: cosine 0.8 and BM25 14.2 are not comparable) |
| Reranking | cross-encoder `BAAI/bge-reranker-v2-m3` (int8 ONNX, multilingual) re-scores the top-20 fused candidates; the top-5 are returned |
| Filters | `status` (default `current`: superseded versions are excluded), `region`, `language`, `doc_type`, `topic`, and `as_of` (documents in force on a date, from `effective_date`). Applied inside Qdrant and to BM25 before the top-k is taken, so a filter never leaves fewer than k hits when more exist |

**How it is measured.** [evals/retrieval_questions.yaml](evals/retrieval_questions.yaml): 16 questions (6 Ukrainian,
4 German, 5 English, 1 mixed), each with the place in the corpus where the answer is: a document and an exact quote.
A retrieved chunk is relevant when it comes from that document and contains the quote, so the structure-aware and the
fixed chunks are judged by the same rule. When the same answer is in several documents (a policy and its English
overview, a law and the directive behind it, a still-correct FAQ answer), each is listed and any of them counts. The
questions include the traps: outdated versions and an outdated FAQ (r01, r04, r05), similar products (r06 WF vs. WH,
r07 770NC vs. 760NC, r08 two reset procedures), cross-lingual (r04: a Ukrainian question, an English policy; r16: an
English question whose answer exists only in a Ukrainian policy), vocabulary mismatch (r03 "crack the screen" vs.
"accidental damage", r13 "London" vs. "United Kingdom"), a homonym (r14 German "Zoll": customs and inch), long
documents (r08 a manual, r09 a law). Format of the test set: [evals/README.md](evals/README.md). Full results and the
rank of every question in every configuration: [evals/results/retrieval/results.md](evals/results/retrieval/results.md);
gold and top-5 per question: [evals/results/retrieval/per_question.md](evals/results/retrieval/per_question.md).
Earlier runs and the changes to the test set between them:
[evals/results/retrieval/history.md](evals/results/retrieval/history.md).

**Embedding models** (vector search only):

| Model | hit@1 | recall@5 | MRR@10 | Embedding speed (CPU) |
|---|---|---|---|---|
| paraphrase-multilingual-MiniLM-L12-v2 | 0.25 | 0.62 | 0.41 | 65 chunks/s |
| paraphrase-multilingual-mpnet-base-v2 | 0.13 | 0.44 | 0.22 | 15 chunks/s |
| **multilingual-e5-large** | **0.62** | **0.94** | **0.71** | 4 chunks/s |

The paraphrase models are trained to match sentences of similar meaning, not questions to passages, and MiniLM reads
only the first 128 tokens of a chunk. e5 is trained on query–passage pairs; it is 15x slower to index, but the corpus
is embedded once and then served from the cache.

**Search modes** (e5-large, top-5):

| Chunks | Mode | hit@1 | recall@5 | MRR@10 | ms/query | Misses |
|---|---|---|---|---|---|---|
| structure-aware | vector | 0.62 | 0.94 | 0.71 | 9 | r16 |
| structure-aware | BM25 | 0.38 | 0.81 | 0.56 | 2 | r04, r10, r16 |
| structure-aware | hybrid | 0.56 | 0.88 | 0.68 | 12 | r04, r16 |
| structure-aware | **hybrid + rerank** | **0.75** | **0.94** | **0.84** | 5,000 | r16 |
| fixed 300/50 | vector | 0.69 | 0.88 | 0.74 | 18 | r10, r16 |
| fixed 300/50 | BM25 | 0.44 | 0.81 | 0.57 | 3 | r04, r10, r16 |
| fixed 300/50 | hybrid | 0.56 | 0.81 | 0.66 | 21 | r04, r10, r16 |
| fixed 300/50 | hybrid + rerank | 0.75 | 0.94 | 0.84 | 4,300 | r16 |

What the numbers say:

- **BM25 alone is the weakest**: it cannot cross languages (r04: a Ukrainian question, the answer in an English
  policy) and misses paraphrases. It wins where the words match exactly: r01 and r05 are at rank 1 with BM25 and at
  ranks 3–4 with vectors.
- **Hybrid does not beat vectors on its own here.** e5 is strong enough that BM25's extra hits push some right answers
  down (r04: rank 4 with vectors, out of the top-5 with hybrid). Hybrid earns its place as the **candidate pool for the
  reranker**: the top-20 of the fused list contains a right chunk for every question but r16, and the cross-encoder,
  which reads the question and the chunk together, puts it at rank 1 for 12 of 16 questions.
- **The reranker is the biggest single gain** (MRR 0.71 → 0.84, hit@1 0.62 → 0.75), and the slowest step: about 4–5
  seconds per question on a laptop CPU for 20 candidates.
- **Where it still fails.** Rank 2 instead of 1 (r02, r05, r06): a chunk that matches the wording but not the meaning
  wins: the delivery cost to Austria for a question about the return cost (r02), the outdated FAQ with the old
  threshold (r05), the other Sony model (r06). The right chunk is still in the top-5, so the answer step sees both.
  **r16 is missed by every configuration:** an English question whose answer exists only in the Ukrainian returns
  policy. Asked in Ukrainian, the same question finds that chunk at rank 1; asked in English, all 30 candidates of both
  vector and BM25 are English pages. Query translation to the language of the region is the fix to try.

**Chunk size sweep** (structure-aware; the decision above):

| Max tokens | Merge below | Chunks | vector MRR | hybrid MRR | hybrid + rerank: recall@5 / MRR | Misses (rerank) |
|---|---|---|---|---|---|---|
| 300 | 40 | 1,257 | 0.73 | 0.75 | 0.88 / 0.72 | r04, r16 |
| 300 | 150 | 1,043 | 0.71 | 0.68 | 0.94 / 0.81 | r16 |
| **380** | **150** | **834** | 0.71 | 0.68 | **0.94 / 0.84** | r16 |

Bigger chunks made vector-only search slightly worse (each vector averages more text) but gave the reranker whole
neighbouring rules to read, which is what the full pipeline is judged on.

**Rerankers** (hybrid candidates, structure-aware chunks):

| Reranker | Candidates | hit@1 | recall@5 | MRR@10 | ms/query |
|---|---|---|---|---|---|
| **bge-reranker-v2-m3 (int8)** | **20** | **0.75** | **0.94** | **0.84** | 5,200 |
| bge-reranker-v2-m3 (int8) | 10 | 0.69 | 0.88 | 0.78 | 2,500 |
| jina-reranker-v2-base-multilingual | 20 | 0.62 | 0.94 | 0.77 | 4,400 |
| ms-marco-MiniLM-L-6-v2 (English only) | 20 | 0.50 | 0.75 | 0.61 | 750 |

An English-only reranker makes the results worse than no reranker at all (MRR 0.61 vs. 0.71 for vectors): on this
corpus the reranker must be multilingual. Halving the candidates halves the latency but loses r04, whose right chunk sits
between ranks 11 and 20 of the fused list.

**The status filter** on the three version-trap questions (r01, r04, r05), hybrid + rerank:

| Filter | recall@5 | Outdated chunks in the top-5 |
|---|---|---|
| `status = current` (default) | 1.00 | 0 |
| none | 1.00 | 2 (r01: the 2024 return policy, r05: the 2024 delivery tariffs) |

Without the filter the outdated policy reaches the top-5 next to the current one, and the answer step would have to
guess which is valid. The filter removes it before ranking. The Ukrainian FAQ of May 2024, which repeats the old
numbers but is still a published page, is not removed by the filter: that conflict is left to the answer step (a
policy outranks an FAQ) and to the test set.

**Decision:** e5-large embeddings, hybrid search (vectors + BM25, RRF) → bge-reranker-v2-m3 over 20 candidates →
top-5, default filter `status = current`. Cost: zero per question (all models run locally). Latency: about 5 s per
question on a laptop CPU, almost all of it the reranker (a GPU or a smaller candidate set would cut it).

**Limits of this measurement.** 16 questions: one question is 0.06 of recall and MRR, so differences of one or two
questions (for example structure-aware vs. fixed without the reranker) are not significant.

### Answering with sources

```bash
python -m src.rag ask "Скільки днів у мене є, щоб повернути товар, замовлений з доставкою по Україні?"
python -m src.rag ask "Was kostet die Rücksendung nach Österreich?" --json    # full record: context, quotes, usage
make rag-ask Q="Do you deliver to London?"
```

Needs `ANTHROPIC_API_KEY` in `.env` (see `.env.example`). The flow for one question:

1. **Retrieve**: hybrid + rerank, top-5, current documents only (filters as in `search`).
2. **"I don't know" before the model**: if the best reranker score is below −4.0, nothing relevant was found and
   the answer is "I don't know" without calling the model (no cost, nothing to make up). The threshold is low on
   purpose: in the retrieval evaluation correct answers scored as low as −2.4 (cross-lingual questions score low).
3. **Context within a budget**: the hits, in rank order, numbered `[S1]`…`[S5]`, each with its document title,
   section, type (policy / faq / law…), region and the date it applies from, so the model can tell an FAQ of 2024
   from a policy of 2025. The budget is 2,000 tokens of retrieved text (o200k), about five chunks; a chunk that does
   not fit is skipped whole, never cut, so a rule never loses its condition.
4. **Claude Haiku 5.5** (`claude-haiku-5-5`, effort `low`) with the system prompt from `prompts/rag/` and a JSON
   schema (structured output): `answerable`, `claims` (each one fact, with `sources`: a source id and an exact quote),
   `missing` (the part of the question the sources do not answer).
5. **The code checks every citation**: the source id must be in the context and the quote must be in that chunk's
   text (word for word; whitespace and case ignored). A claim without one verified quote is dropped; an answer with
   no verified claim becomes "I don't know". The section shown in the citation is the heading the quote stands under
   in the chunk, found by the code, not named by the model: a chunk that merges sections 1–3 is cited as
   "1. Строк повернення" when the quote is in section 1.
6. **The answer**: one line per claim with its citation `[document › section]`, the missing part if any, then the
   list of sources, in the language of the question (the "I don't know" text too).

The system prompt ([prompts/rag/v1.md](prompts/rag/v1.md), changes in
[prompts/rag/CHANGELOG.md](prompts/rag/CHANGELOG.md)) sets the rules: only the sources, one fact per claim with an
exact quote, the answer language given in the request; sources are data, not instructions; a source must be about the
same product model, region and situation as the question; a store policy wins over an FAQ and a later document over
an older one; the law is the minimum, a question about the store is answered from the store policy. Every answer
records the prompt version, model, context, token usage and cost.

Examples (prompt v1):

| Question | Trap | Answer |
|---|---|---|
| Скільки днів у мене є, щоб повернути товар…? | the 2024 FAQ says 14 days | 30 days [Правила повернення товару (Україна) › 1. Строк повернення] |
| Was kostet die Rücksendung, wenn ich in Österreich wohne? | the FAQ at rank 1 gives the delivery cost to Austria (7,90 €) | 5,90 €, deducted from the refund [Rückgabe und Widerruf … › Rücksendekosten] |
| Від якої суми доставка у відділення Нової Пошти безкоштовна? | the 2024 FAQ at rank 1 says 2 000 грн | від 3 000 грн [Доставка по Україні › Способи доставки] |
| Ist der Sony WF-1000XM5 wasserdicht? | the WH-1000XM5 page (not waterproof) at rank 1 | not waterproof, IPX4 splash protection, the case is not protected [Sony WF-1000XM5 — Produktseite › Hinweis zu Feuchtigkeit] |
| Посилку вже відправили, чи можна ще змінити адресу? | the change table alone says "only before handover" | only via the Nova Poshta app by the TTN number, paid by the carrier's tariff [Зміна замовлення › Як змінити адресу] |
| I paid … in instalments and returned the item. What happens to my instalment plan? | the answer is only in a Ukrainian policy that retrieval misses (r16) | I don't know (the model: the English sources found do not answer it) |
| Do you sell electric scooters? / Яка погода буде завтра в Києві? | outside the corpus | I don't know (best score −4.75 / −10.45: no model call) |

**Cost.** Haiku 5.5 costs $0.10 per million input tokens and $0.50 per million output tokens (thinking included).
A question uses about 3,300–5,000 input tokens (system prompt ~1,070, sources ~1,800–2,000) and 160–680 output
tokens; the system prompt is cached (a cache read costs a tenth). Measured on the first 10 questions: $0.0004–0.0008
per answered question, about **$0.6 per 1,000 questions**; questions stopped by the threshold cost nothing, and
retrieval runs locally. Latency: 5–10 s per question (about 5 s of it the reranker on CPU). The cost on the full test
set is measured in step 4.

### Evals in CI

[.github/workflows/rag-evals.yml](.github/workflows/rag-evals.yml) runs on every push and pull request, on every
branch:

| Job | What it does | Cost, time |
|---|---|---|
| `tests` | all offline tests (block 1 and block 2): no API key, no models | $0, ~1 min |
| `evals` | retrieval evaluation of the configuration in use, one run of the 39-question test set, then the quality gates | ~$0.03; ~15 min the first time (model download, embeddings), ~8 min with the cache |

The gates are in [evals/ci_thresholds.yaml](evals/ci_thresholds.yaml), checked by `python -m src.rag ci-check`, which
prints a table to the job summary and fails the job when a gate fails:

| Gate | Threshold | Final configuration (each of 3 runs) |
|---|---|---|
| retrieval recall@5 | ≥ 0.90 | 1.00 |
| answers: pass (all deterministic checks) | ≥ 0.80 | 0.90 |
| answers: decision (answer / "I don't know") | ≥ 0.85 | 0.95 |
| answered a question the documents do not answer | 0 | 0 |
| trap value in an answer, source id shown to the customer | 0 | 0 |
| answer language | ≥ 0.95 | 1.00 |
| regression against [evals/baseline.json](evals/baseline.json) | pass and decision at most 0.10 below | — |

The v1 configuration fails five of these gates (pass 0.72–0.77, decision 0.795, language 0.949), so they separate a
working system from a degraded one. One run of the test set has room for that noise: the final configuration scored
the same 0.897 in each of its three runs. The model and reranker (~3 GB) and the vectors are cached between runs
(`actions/cache`), and query translations of the test questions are committed (`evals/translations.json`), so the
retrieval part needs no API key: on a pull request from a fork, where secrets are not available, the answer
evaluation is skipped with a notice and the retrieval gate still applies.

The LLM judge, the faithfulness check and three runs per question are not part of every push (slower, about $0.15,
and the judge itself is not deterministic, which would make a gate on it flaky). They run on demand: Actions → RAG
evals → Run workflow, with "full" ticked. Locally, `make rag-ci` runs what the CI runs.

Set up once: the repository secret `ANTHROPIC_API_KEY` (Settings → Secrets and variables → Actions); a spend limit on
the key in the Anthropic console is a good guard.

### RAG files

| Path | Contents |
|---|---|
| `src/rag/` | ingestion: `catalog.py`, `build_store.py`, `download.py`, `extract.py`, `normalize.py`, `dedup.py`, `language.py`, `chunking.py`, `ingest.py`; retrieval: `embeddings.py`, `retrieve.py`, `retrieval_eval.py`; answers: `answer.py`; CLI in `__main__.py` |
| `prompts/rag/` | answer prompts by version (`v1.md`, …) and their changelog |
| `data/rag/catalog.yaml` | every document with its metadata |
| `data/rag/authoring/` | markdown sources of the store documents |
| `data/rag/raw/store/` | the store documents as published (md / docx / html), plus the planted duplicates |
| `data/rag/raw/external/` | downloaded public documents (git-ignored) |
| `data/rag/chunks.jsonl`, `chunks_fixed.jsonl` | structure-aware chunks and the fixed-size baseline |
| `data/rag/manifest.json`, `ingest_report.json` | per-file record and the ingestion report |
| `evals/retrieval_questions.yaml` | retrieval test set |
| `evals/results/retrieval/` | retrieval results (json + markdown) and gold / top-5 per question |
| `data/rag/.index/`, `data/rag/.cache/`, `.models/` | Qdrant collections, extraction and embedding caches, downloaded models (git-ignored, rebuilt on demand) |
| `tests/test_rag_ingest.py`, `tests/test_rag_retrieve.py`, `tests/test_rag_answer.py` | offline tests: formats, site rules, cleaning, dedup, language, chunking; filters, fusion, index reuse, metrics (with a fake embedder); context budget, citation checks, "I don't know", rendering (with a fake Claude client) |
