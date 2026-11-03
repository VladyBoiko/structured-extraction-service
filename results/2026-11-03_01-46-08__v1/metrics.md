Runs (all tickets):

| run | model | prompt | temp | top_p | options | tickets | valid % | failed | p50 s | p95 s | $/1000 | hours/1000 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cloud_default | claude-haiku-5-5 | v1 | None | None | effort=medium | 75 | 96 | 3 | 1.75 | 3.41 | 0.4236 | 0.53 |
| local_t0 | qwen2.5:3b | v1 | 0.0 | 1.0 | num_ctx=4096 | 75 | 100 | 0 | 3.90 | 4.23 | 0.0000 | 1.07 |
| local_t07 | qwen2.5:3b | v1 | 0.7 | 0.9 | num_ctx=4096 | 75 | 100 | 0 | 3.89 | 4.34 | 0.0000 | 1.08 |

Accuracy on the golden set:

| run | golden | mean acc [95% CI] | exact | fabricated order_id |
|---|---|---|---|---|
| cloud_default | 30 | 0.93 [0.90-0.96] | 0.47 | 0/12 |
| local_t0 | 30 | 0.78 [0.73-0.83] | 0.07 | 0/12 |
| local_t07 | 30 | 0.77 [0.72-0.82] | 0.13 | 0/12 |

Per-field accuracy:

| run | category | priority | sentiment | language | requested_action | needs_human | escalation_threat | repeat_contact | deadline | tracking_number | order_id | products.category |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cloud_default | 0.90 | 0.73 | 0.83 | 0.97 | 0.93 | 0.90 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.93 |
| local_t0 | 0.60 | 0.23 | 0.80 | 0.83 | 0.60 | 0.83 | 0.97 | 0.97 | 0.97 | 0.93 | 0.87 | 0.77 |
| local_t07 | 0.57 | 0.27 | 0.77 | 0.83 | 0.63 | 0.83 | 0.97 | 0.93 | 0.97 | 0.93 | 0.83 | 0.73 |

_If the confidence intervals of two configurations overlap, neither is claimed better._
