# Structured Extraction Service

Turns messy customer support tickets of an online electronics store into validated JSON and measures which model and prompt
do it best. A cloud model (Claude Haiku 5.5) and a local model (Qwen2.5 3B via Ollama) run behind one interface and are
compared on field accuracy, share of valid answers, latency and cost.

## Input

`data/texts/` holds 30 synthetic tickets, one `<id>.txt` file each. They are deliberately messy: different lengths, typos,
missing details, and English mixed with Ukrainian and German. Order numbers (`ES-xxxxx`) are fictional; there is no personal data.

```text
data/texts/t09.txt
Hi team, навушники JBL Tune 760NC прийшли з подряпиною на корпусі and the left ear is silent. Order ES-49877.
Хочу обмін, bitte schnell, у мене це подарунок на завтра зранку!
```

`data/golden/` holds reference labels for 10 of the tickets, one `<id>.json` per ticket with the same name as the text
(`golden/t09.json` labels `texts/t09.txt`). Labeling rules: [data/LABELING_GUIDE.md](data/LABELING_GUIDE.md).

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
| `summary` | string | one English sentence, 1-200 characters |
| `product` | object | `name` (string or null), `category` (enum: `smartphone`, `laptop`, `tv`, `headphones`, `tablet`, `appliance`, `accessory`, `other`, `unknown`), `order_id` (string or null) |

Expected output for the ticket above:

```json
{
  "category": "product_defect",
  "priority": "urgent",
  "sentiment": "negative",
  "language": "mixed",
  "requested_action": "replacement",
  "needs_human": true,
  "summary": "JBL Tune 760NC from order ES-49877 arrived scratched with a silent left ear; customer wants a fast exchange.",
  "product": {"name": "JBL Tune 760NC", "category": "headphones", "order_id": "ES-49877"}
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

A full run of 30 tickets costs well under one cent on the API.

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
- `metrics.json` and `metrics.md` - the comparison tables.

Metric definitions: [docs/METRICS.md](docs/METRICS.md).

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
| `results/` | model outputs and metrics per run |
| `tests/` | pytest suite |
