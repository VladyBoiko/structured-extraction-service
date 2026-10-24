import json

import pytest

from src.pipeline import call_model
from src.providers import LLMResult, NonRetryableError, Provider

GOOD = json.dumps({
    "category": "payment", "priority": "high", "sentiment": "negative", "language": "en",
    "requested_action": "refund", "needs_human": True, "summary": "Double charge.",
    "product": {"name": None, "category": "tv", "order_id": "ES-48213"},
})
BAD = '{"category": "payment"}'
REQ = {"max_tokens": 100, "timeout_s": 1, "max_retries": 2, "max_repair_attempts": 1}
RUN = {"temperature": 0.0, "top_p": None}


class Scripted(Provider):
    """Returns scripted answers or raises scripted exceptions."""

    def __init__(self, items):
        self.items = list(items)

    def generate(self, *args, **kwargs):
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResult(item, 10, 5)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("src.pipeline.time.sleep", lambda s: None)


def run(items):
    return call_model(Scripted(items), "system", "user", {}, RUN, REQ)


def test_valid_first_try():
    r = run([GOOD])
    assert r["status"] == "ok" and r["attempts"] == 1 and r["repairs"] == 0


def test_invalid_then_repaired():
    r = run([BAD, GOOD])
    assert r["status"] == "ok" and r["attempts"] == 2 and r["repairs"] == 1


def test_invalid_twice_is_failed():
    r = run([BAD, BAD])
    assert r["status"] == "failed" and r["repairs"] == 1 and "invalid_schema" in r["error"]
    assert r["output"] is None


def test_timeouts_then_success():
    r = run([TimeoutError("t"), TimeoutError("t"), GOOD])
    assert r["status"] == "ok" and r["attempts"] == 3


def test_too_many_timeouts_is_failed():
    r = run([TimeoutError("t")] * 3)
    assert r["status"] == "failed" and r["attempts"] == 3 and "TimeoutError" in r["error"]


def test_non_retryable_fails_immediately():
    r = run([NonRetryableError("prompt did not fit")])
    assert r["status"] == "failed" and r["attempts"] == 1
