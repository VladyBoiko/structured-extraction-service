"""Metrics for comparing configurations. The rules are described in docs/METRICS.md."""
import random
from collections import defaultdict

# Fields compared with the golden set. `summary` and `product.name` are free text and are not scored.
FIELDS = [
    "category", "priority", "sentiment", "language", "requested_action",
    "needs_human", "product.category", "product.order_id",
]


def _get(obj: dict | None, path: str):
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        cur = cur.get(part)
    return cur


def _norm(field: str, value):
    if isinstance(value, str):
        s = value.strip()
        if field.endswith("order_id"):
            return s.upper().replace("#", "").replace(" ", "")
        return s.lower()
    return value


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    pos = (len(s) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def _bootstrap_ci(scores: list[float], n_boot: int = 1000, seed: int = 0) -> tuple[float, float]:
    """95% confidence interval of the mean (bootstrap over golden tickets, fixed seed)."""
    if not scores:
        return 0.0, 0.0
    rng = random.Random(seed)
    n = len(scores)
    means = sorted(sum(rng.choices(scores, k=n)) / n for _ in range(n_boot))
    return means[int(0.025 * n_boot)], means[int(0.975 * n_boot) - 1]


def compute_metrics(records: list[dict], golden: dict[str, dict]) -> dict:
    """Metrics of one configuration (model + prompt + sampling).

    Accuracy is computed on the golden tickets present in the run; an invalid answer counts as all fields wrong.
    """
    n = len(records)
    n_valid = sum(1 for r in records if r["valid"])
    latencies = [r["latency_s"] for r in records]
    total_cost = sum(r["cost_usd"] for r in records)

    by_id = {r["id"]: r for r in records}
    gold_ids = [i for i in golden if i in by_id]
    correct = defaultdict(int)
    ticket_scores: list[float] = []
    exact = 0
    fabricated = golden_null = filled_ok = golden_filled = 0

    for gid in gold_ids:
        rec = by_id[gid]
        flags = []
        for f in FIELDS:
            ok = rec["valid"] and _norm(f, _get(rec["output"], f)) == _norm(f, _get(golden[gid], f))
            correct[f] += int(ok)
            flags.append(ok)
        ticket_scores.append(sum(flags) / len(FIELDS))
        exact += int(all(flags))

        # order_id: count fabricated values (golden is null) separately from accuracy on filled ones
        g_oid = _norm("product.order_id", _get(golden[gid], "product.order_id"))
        m_oid = _norm("product.order_id", _get(rec["output"], "product.order_id")) if rec["valid"] else None
        if g_oid is None:
            golden_null += 1
            fabricated += int(m_oid is not None)
        else:
            golden_filled += 1
            filled_ok += int(m_oid == g_oid)

    ng = len(gold_ids)
    per_field = {f: (correct[f] / ng if ng else 0.0) for f in FIELDS}
    ci_lo, ci_hi = _bootstrap_ci(ticket_scores)
    first = records[0]
    return {
        "run": first["run"], "model": first["model"], "prompt_version": first["prompt_version"],
        "temperature": first["temperature"], "top_p": first["top_p"], "options": first.get("options"),
        "n_tickets": n, "n_golden": ng,
        "valid_pct": 100 * n_valid / n if n else 0.0,
        "failed": n - n_valid,
        "mean_field_accuracy": sum(ticket_scores) / ng if ng else 0.0,
        "mean_field_accuracy_ci95": [ci_lo, ci_hi],
        "exact_match": exact / ng if ng else 0.0,
        "per_field_accuracy": per_field,
        "order_id_fabricated": fabricated,
        "order_id_golden_null": golden_null,
        "order_id_filled_accuracy": filled_ok / golden_filled if golden_filled else None,
        "latency_p50_s": _percentile(latencies, 0.5),
        "latency_p95_s": _percentile(latencies, 0.95),
        "cost_total_usd": total_cost,
        "cost_per_1000_usd": total_cost / n * 1000 if n else 0.0,
        # sequential processing time for 1000 documents (for the local model this is its hardware cost)
        "hours_per_1000": sum(latencies) / n * 1000 / 3600 if n else 0.0,
    }


def format_tables(all_metrics: list[dict]) -> str:
    """Markdown tables: summary metrics and per-field accuracy."""
    lines = [
        "| run | model | prompt | temp | top_p | options | valid % | failed | mean acc [95% CI] | exact "
        "| fabricated order_id | p50 s | p95 s | $/1000 | hours/1000 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in all_metrics:
        lo, hi = m["mean_field_accuracy_ci95"]
        opts = ", ".join(f"{k}={v}" for k, v in (m.get("options") or {}).items()) or "-"
        lines.append(
            f"| {m['run']} | {m['model']} | {m['prompt_version']} | {m['temperature']} | {m['top_p']} | {opts} "
            f"| {m['valid_pct']:.0f} | {m['failed']} | {m['mean_field_accuracy']:.2f} [{lo:.2f}-{hi:.2f}] "
            f"| {m['exact_match']:.2f} | {m['order_id_fabricated']}/{m['order_id_golden_null']} "
            f"| {m['latency_p50_s']:.2f} | {m['latency_p95_s']:.2f} | {m['cost_per_1000_usd']:.4f} "
            f"| {m['hours_per_1000']:.2f} |"
        )
    lines += ["", "Per-field accuracy (golden set):", "",
              "| run | " + " | ".join(FIELDS) + " |",
              "|---|" + "---|" * len(FIELDS)]
    for m in all_metrics:
        cells = " | ".join(f"{m['per_field_accuracy'][f]:.2f}" for f in FIELDS)
        lines.append(f"| {m['run']} | {cells} |")
    lines += ["", f"_Golden tickets per configuration: {all_metrics[0]['n_golden']}. "
                  "If the confidence intervals of two configurations overlap, neither is claimed better._"]
    return "\n".join(lines)
