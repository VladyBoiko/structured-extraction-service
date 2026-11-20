"""Offline tests for the LLM judge and the faithfulness check (block 2, step 4): fake client, no API calls."""

import json
from types import SimpleNamespace

from src.rag.faithfulness import change_number, check, controls
from src.rag.judge import cohen_kappa, confusion, judge_one


class FakeClient:
    def __init__(self, data):
        self.data, self.requests = data, []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text=json.dumps(self.data))],
                               usage=SimpleNamespace(input_tokens=1000, output_tokens=100))


def test_cohen_kappa():
    assert cohen_kappa(["a", "a", "b", "b"], ["a", "a", "b", "b"]) == 1.0
    assert cohen_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == 0.0
    # high raw agreement, but a judge that always says "a" learns nothing about the rare class
    assert cohen_kappa(["a"] * 9 + ["b"], ["a"] * 10) == 0.0


def test_confusion():
    m = confusion(["correct", "partial", "partial"], ["correct", "correct", "partial"])
    assert m["partial"]["correct"] == 1 and m["partial"]["partial"] == 1 and m["correct"]["correct"] == 1


def test_judge_sends_question_reference_and_answer():
    client = FakeClient({"reason": "matches", "label": "correct"})
    v = judge_one(client, "Q?", "REF", "ANSWER", "PROMPT")
    assert v["label"] == "correct" and v["cost_usd"] > 0
    user = client.requests[0]["messages"][0]["content"]
    assert "<reference_answer>\nREF" in user and "<assistant_answer>\nANSWER" in user
    assert client.requests[0]["output_config"]["format"]["schema"]["properties"]["label"]["enum"] == \
        ["correct", "partial", "incorrect"]


def test_faithfulness_check_sends_each_claim_with_its_full_sources():
    claims = [{"text": "30 днів.", "citations": [{"chunk_id": "a#000", "title": "A"}, {"chunk_id": "a#000", "title": "A"}]},
              {"text": "Безкоштовно.", "citations": [{"chunk_id": "b#000", "title": "B"}]}]
    client = FakeClient({"claims": [{"index": 0, "reason": "ok", "supported": True},
                                    {"index": 1, "reason": "no", "supported": False}]})
    verdicts, spent = check(client, claims, {"a#000": "FULL TEXT A", "b#000": "FULL TEXT B"}, "PROMPT")
    assert [v["supported"] for v in verdicts] == [True, False] and spent > 0
    user = client.requests[0]["messages"][0]["content"]
    assert user.count("FULL TEXT A") == 1 and "FULL TEXT B" in user   # a chunk cited twice is sent once


def test_change_number():
    assert change_number("протягом 30 днів") == "протягом 70 днів"
    assert change_number("kostet 5,90 €") == "kostet 9,90 €"
    assert change_number("від 1 500 грн") == "від 5 500 грн"
    assert change_number("no number") is None


def test_controls_break_real_claims():
    recs = [{"id": f"t0{i}", "run": 1, "claims": [{"text": f"Claim {i} costs {i}0 EUR.",
                                                    "citations": [{"chunk_id": f"d{i}#000"}]}]} for i in range(1, 5)]
    ctrl = controls(recs, n=4)
    changed = [c for c in ctrl if c["kind"] == "number changed"]
    swapped = [c for c in ctrl if c["kind"] == "claim of another question"]
    assert len(changed) == 2 and len(swapped) == 2
    assert changed[0]["text"] != recs[0]["claims"][0]["text"]
    assert changed[0]["citations"] == recs[0]["claims"][0]["citations"]           # same citations, broken claim
    assert swapped[0]["text"] == recs[1]["claims"][0]["text"] and swapped[0]["citations"] == recs[0]["claims"][0]["citations"]
