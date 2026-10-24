| run | model | prompt | temp | top_p | options | valid % | failed | mean acc [95% CI] | exact | fabricated order_id | p50 s | p95 s | $/1000 | hours/1000 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cloud_default | claude-haiku-5-5 | v1 | None | None | effort=medium | 100 | 0 | 0.94 [0.90-0.97] | 0.50 | 0/5 | 1.50 | 2.27 | 0.2899 | 0.44 |
| local_t0 | qwen2.5:3b | v1 | 0.0 | 1.0 | num_ctx=4096 | 100 | 0 | 0.74 [0.62-0.82] | 0.00 | 0/5 | 3.45 | 3.61 | 0.0000 | 0.96 |
| local_t07 | qwen2.5:3b | v1 | 0.7 | 0.9 | num_ctx=4096 | 100 | 0 | 0.74 [0.66-0.80] | 0.00 | 0/5 | 3.45 | 3.63 | 0.0000 | 0.96 |

Per-field accuracy (golden set):

| run | category | priority | sentiment | language | requested_action | needs_human | product.category | product.order_id |
|---|---|---|---|---|---|---|---|---|
| cloud_default | 1.00 | 0.90 | 0.80 | 1.00 | 0.90 | 0.90 | 1.00 | 1.00 |
| local_t0 | 0.50 | 0.40 | 0.80 | 0.90 | 0.60 | 0.80 | 0.90 | 1.00 |
| local_t07 | 0.60 | 0.30 | 0.80 | 0.90 | 0.60 | 0.90 | 0.80 | 1.00 |

_Golden tickets per configuration: 10. If the confidence intervals of two configurations overlap, neither is claimed better._
