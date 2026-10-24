# Metrics

## Comparing answers with the golden set
- Enum and boolean fields: exact match (case-insensitive).
- `product.order_id`: normalized (upper case, `#` and spaces removed), then exact match.
- `summary` and `product.name` are free text and are not scored.
- Scored fields (8): `category`, `priority`, `sentiment`, `language`, `requested_action`, `needs_human`, `product.category`, `product.order_id`.

## Reported metrics
| Metric | Definition |
|---|---|
| **valid %** | share of tickets whose answer passed schema validation (after at most one repair attempt) |
| **failed** | number of tickets with status `failed` (invalid answer, error, timeout, context overflow) |
| **mean acc** | mean share of correct fields per golden ticket. A `failed` ticket counts as all fields wrong, so a failure is never better than a wrong answer |
| **95% CI** | bootstrap over golden tickets (1000 resamples, seed 0). **If the intervals of two configurations overlap, neither is claimed better** |
| **exact** | share of golden tickets with all 8 fields correct |
| **fabricated order_id** | how often the model invented an order number where the golden label has none (k/n). Guards against an "always null" strategy looking good |
| **p50 / p95 latency** | seconds per ticket, including retries and repair attempts (what a caller waits). The local model is warmed up before a run so its load time is not measured |
| **$/1000** | API cost per 1000 documents: mean tokens per ticket (including repair attempts and thinking tokens) x prices from `config.yaml` x 1000. 0 for the local model |
| **hours/1000** | time to process 1000 documents sequentially (mean latency x 1000). For the local model this is its real cost: hours of laptop compute |
| **options** | extra configuration parameters (e.g. `effort` for the cloud model, `num_ctx` for Ollama) |

Per-field accuracy is reported in a second table.

## Limitations
- The golden set has 10 tickets, so a difference of 1-2 tickets is noise; rely on the confidence intervals.
- Cloud latency depends on the network, local latency on the machine. Compare local configurations on the same machine.
- Claude Haiku 5.5 does not accept temperature/top_p, so the sampling comparison is done on the local model.
