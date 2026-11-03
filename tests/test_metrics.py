from src.metrics import FIELDS, compute_metrics, format_tables

GOLDEN = {
    "a": {"category": "payment", "priority": "high", "sentiment": "negative", "language": "en",
          "requested_action": "refund", "needs_human": True, "order_id": "ES-1",
          "products": [{"name": None, "category": "tv"}, {"name": "HDMI cable", "category": "accessory"}]},
    "b": {"category": "other", "priority": "low", "sentiment": "neutral", "language": "uk",
          "requested_action": "none", "needs_human": False, "order_id": None, "products": []},
}


def rec(i, output, valid=True):
    return {"id": i, "run": "r", "model": "m", "prompt_version": "v1", "temperature": 0.0, "top_p": None,
            "valid": valid, "output": output, "latency_s": 1.0, "cost_usd": 0.001}


def perfect(i):
    return {k: v for k, v in GOLDEN[i].items()}


def test_perfect_answers():
    m = compute_metrics([rec("a", perfect("a")), rec("b", perfect("b"))], GOLDEN)
    assert m["mean_field_accuracy"] == 1.0 and m["exact_match"] == 1.0
    assert m["order_id_fabricated"] == 0 and m["order_id_golden_null"] == 1


def test_failed_answer_counts_all_fields_wrong():
    m = compute_metrics([rec("a", perfect("a")), rec("b", None, valid=False)], GOLDEN)
    assert m["failed"] == 1 and m["valid_pct"] == 50.0
    assert m["mean_field_accuracy"] == 0.5 and m["exact_match"] == 0.5


def test_fabricated_order_id_detected():
    wrong = {**perfect("b"), "order_id": "ES-999"}
    m = compute_metrics([rec("a", perfect("a")), rec("b", wrong)], GOLDEN)
    assert m["order_id_fabricated"] == 1


def test_order_id_normalization_and_enum_case():
    out = {**perfect("a"), "category": "Payment", "order_id": "#es-1"}
    m = compute_metrics([rec("a", out)], {"a": GOLDEN["a"]})
    assert m["mean_field_accuracy"] == 1.0


def test_products_compared_by_categories_in_any_order():
    out = {**perfect("a"), "products": [{"name": "cable", "category": "accessory"}, {"name": "TV", "category": "tv"}]}
    missing = {**perfect("a"), "products": [{"name": None, "category": "tv"}]}
    m = compute_metrics([rec("a", out)], {"a": GOLDEN["a"]})
    assert m["per_field_accuracy"]["products.category"] == 1.0
    m = compute_metrics([rec("a", missing)], {"a": GOLDEN["a"]})
    assert m["per_field_accuracy"]["products.category"] == 0.0


def test_cost_per_1000_and_ci_bounds():
    m = compute_metrics([rec("a", perfect("a")), rec("b", perfect("b"))], GOLDEN)
    assert abs(m["cost_per_1000_usd"] - 1.0) < 1e-9
    lo, hi = m["mean_field_accuracy_ci95"]
    assert 0.0 <= lo <= hi <= 1.0
    assert set(m["per_field_accuracy"]) == set(FIELDS)


def test_accuracy_only_on_golden_tickets():
    recs = [rec("a", perfect("a")), rec("x", None, valid=False)]       # "x" has no golden label
    m = compute_metrics(recs, GOLDEN)
    assert m["mean_field_accuracy"] == 1.0 and m["n_golden"] == 1
    assert m["valid_pct"] == 50.0                                      # validity covers all tickets


def test_format_tables_has_one_row_per_run():
    m = compute_metrics([rec("a", perfect("a")), rec("b", None, valid=False)], GOLDEN)
    assert "| r | 2 | 0.50 [" in format_tables([m])
