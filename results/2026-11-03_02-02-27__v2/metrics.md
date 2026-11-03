Runs (all tickets):

| run | model | prompt | temp | top_p | options | tickets | valid % | failed | p50 s | p95 s | $/1000 | hours/1000 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cloud_default | claude-haiku-5-5 | v2 | None | None | effort=medium | 75 | 100 | 0 | 1.72 | 2.00 | 0.5356 | 0.49 |
| local_t0 | qwen2.5:3b | v2 | 0.0 | 1.0 | num_ctx=4096 | 75 | 100 | 0 | 3.87 | 4.41 | 0.0000 | 1.08 |
| local_t07 | qwen2.5:3b | v2 | 0.7 | 0.9 | num_ctx=4096 | 75 | 100 | 0 | 3.85 | 4.61 | 0.0000 | 1.07 |

Accuracy on the golden set:

| run | golden | mean acc [95% CI] | exact | fabricated order_id |
|---|---|---|---|---|
| cloud_default | 30 | 0.97 [0.96-0.99] | 0.70 | 0/12 |
| local_t0 | 30 | 0.82 [0.77-0.86] | 0.07 | 0/12 |
| local_t07 | 30 | 0.82 [0.78-0.86] | 0.07 | 0/12 |

Per-field accuracy:

| run | category | priority | sentiment | language | requested_action | needs_human | escalation_threat | repeat_contact | deadline | tracking_number | order_id | products.category |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cloud_default | 0.97 | 0.90 | 0.90 | 1.00 | 0.97 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.97 |
| local_t0 | 0.83 | 0.47 | 0.77 | 0.83 | 0.53 | 0.77 | 1.00 | 1.00 | 0.93 | 0.97 | 1.00 | 0.70 |
| local_t07 | 0.83 | 0.47 | 0.77 | 0.80 | 0.57 | 0.83 | 1.00 | 1.00 | 0.93 | 0.97 | 1.00 | 0.70 |

_If the confidence intervals of two configurations overlap, neither is claimed better._
