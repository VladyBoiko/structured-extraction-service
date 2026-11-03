# Metrics

## Comparing answers with the golden set
- Enum and boolean fields: exact match (case-insensitive).
- `order_id` and `tracking_number`: normalized (upper case, `#` and spaces removed), then exact match.
- `deadline`: only whether a deadline is present; the wording is not compared.
- `products.category`: the sorted list of product categories must match, so a missing or an extra product makes the
  field wrong; the order of products does not matter.
- `summary` and product names are free text and are not scored.
- Scored fields (12): `category`, `priority`, `sentiment`, `language`, `requested_action`, `needs_human`,
  `escalation_threat`, `repeat_contact`, `deadline`, `tracking_number`, `order_id`, `products.category`.
- The four signal fields (`escalation_threat`, `repeat_contact`, `deadline`, `tracking_number`) are usually false or null,
  so a model that always answers "no" scores high on them; check the per-field table, not only the mean.

## Golden set
- Accuracy metrics are computed on the 30 golden tickets (see [data/LABELING_GUIDE.md](../data/LABELING_GUIDE.md)).
- Validity, latency and cost cover all tickets of a run, not only the golden ones.
- Errors are analysed manually with `python -m src.errors`: it prints every field that differs from the golden label.

## Reported metrics
| Metric | Definition |
|---|---|
| **valid %** | share of tickets whose answer passed schema validation (after at most one repair attempt) |
| **failed** | number of tickets with status `failed` (invalid answer, error, timeout, context overflow) |
| **mean acc** | mean share of correct fields per golden ticket. A `failed` ticket counts as all fields wrong, so a failure is never better than a wrong answer |
| **95% CI** | bootstrap over golden tickets (1000 resamples, seed 0). **If the intervals of two configurations overlap, neither is claimed better** |
| **exact** | share of golden tickets with all 12 fields correct |
| **fabricated order_id** | how often the model invented an order number where the golden label has none (k/n). Guards against an "always null" strategy looking good |
| **p50 / p95 latency** | seconds per ticket, including retries and repair attempts (what a caller waits). The local model is warmed up before a run so its load time is not measured |
| **$/1000** | API cost per 1000 documents: mean tokens per ticket (including repair attempts and thinking tokens) x prices from `config.yaml` x 1000. 0 for the local model |
| **hours/1000** | time to process 1000 documents sequentially (mean latency x 1000). For the local model this is its real cost: hours of laptop compute |
| **options** | extra configuration parameters (e.g. `effort` for the cloud model, `num_ctx` for Ollama) |

Per-field accuracy is reported in a separate table.

## Limitations
- The golden set is small (30 tickets), so a difference of 1-2 tickets is noise; rely on the confidence intervals.
- Prompt versions are improved by looking at errors on the same golden set they are scored on, so an improvement
  partly reflects fitting these tickets; the 45 unlabeled tickets show only validity, latency and cost.
- Cloud latency depends on the network, local latency on the machine. Compare local configurations on the same machine.
- Claude Haiku 5.5 does not accept temperature/top_p, so the sampling comparison is done on the local model.
