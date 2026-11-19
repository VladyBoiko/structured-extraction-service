"""Offline tests for retrieval (block 2, step 2): a fake embedder stands in for the ONNX model."""

import hashlib

import numpy as np
import pytest
from qdrant_client import QdrantClient

import src.rag.retrieve as R
from src.rag import config as C
from src.rag.retrieval_eval import is_hit, lint, run_config


def chunk(cid, text, section="Policy > Rules", status="current", region="UA", language="uk", doc_type="policy",
          topic="returns", effective="2025-03-01"):
    doc = cid.split("#")[0]
    return {"chunk_id": cid, "doc_id": doc, "title": "Policy", "section": section, "text": text, "status": status,
            "region": region, "language": language, "doc_type": doc_type, "topic": topic, "effective_date": effective}


CHUNKS = [
    chunk("returns_2025#000", "Return within 30 days of delivery. Refund in 7 days."),
    chunk("returns_2024#000", "Return within 14 days of delivery. Refund in 10 days.", status="superseded",
          effective="2024-01-01"),
    chunk("delivery_dach#000", "Versand nach Österreich kostet 7,90 €.", region="DACH", language="de", topic="delivery"),
    chunk("manual#000", "Press and hold the reset button for 20 seconds.", region="GLOBAL", language="en",
          doc_type="manual", topic="product"),
]


class FakeEmbedder:
    """Bag-of-words hashed into 64 dims: texts sharing words get similar vectors."""

    def __init__(self, key):
        self.key = key
        self.last_computed = 0

    def _vec(self, text):
        v = np.zeros(64, dtype=np.float32)
        for w in R.tokenize(text):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1
        return v / (np.linalg.norm(v) or 1)

    def passages(self, texts):
        self.last_computed = len(texts)
        return np.stack([self._vec(t) for t in texts])

    def query(self, text):
        return self._vec(text)


@pytest.fixture
def retriever(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "Embedder", FakeEmbedder)
    monkeypatch.setattr(C, "INDEX_DIR", tmp_path)
    return R.Retriever(CHUNKS, "test", client=QdrantClient(":memory:"))


def test_default_filter_hides_superseded_versions(retriever):
    for mode in ("vector", "bm25", "hybrid"):
        ids = [h["chunk_id"] for h in retriever.search("return within 30 days", mode=mode, k=4)]
        assert "returns_2024#000" not in ids, mode
        assert ids[0] == "returns_2025#000", mode


def test_no_filter_shows_all_versions(retriever):
    ids = [h["chunk_id"] for h in retriever.search("return within days", mode="hybrid", filters=R.NO_FILTER, k=4)]
    assert {"returns_2025#000", "returns_2024#000"} <= set(ids)


def test_metadata_filters_work_in_both_searches(retriever):
    flt = R.Filters(regions=["DACH"])
    for mode in ("vector", "bm25"):
        hits = retriever.search("Versand Österreich", mode=mode, filters=flt, k=4)
        assert [h["region"] for h in hits] == ["DACH"], mode
    as_of = R.Filters(status=None, as_of="2024-06-01")   # what was in force in mid-2024
    ids = [h["chunk_id"] for h in retriever.search("return within days", mode="vector", filters=as_of, k=4)]
    assert "returns_2024#000" in ids and "returns_2025#000" not in ids


def test_filter_python_and_qdrant_agree():
    flt = R.Filters(regions=["UA"], doc_types=["policy"], as_of="2025-12-31")
    assert [c["chunk_id"] for c in CHUNKS if flt.match(c)] == ["returns_2025#000"]
    assert flt.to_qdrant() is not None
    assert R.Filters(status=None).to_qdrant() is None


def test_index_is_reused_when_nothing_changed(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "Embedder", FakeEmbedder)
    monkeypatch.setattr(C, "INDEX_DIR", tmp_path)
    client = QdrantClient(":memory:")
    assert R.Retriever(CHUNKS, "t", client=client).built_now
    assert not R.Retriever(CHUNKS, "t", client=client).built_now
    changed = CHUNKS[:-1] + [{**CHUNKS[-1], "text": "Press the button for 30 seconds."}]
    assert R.Retriever(changed, "t", client=client).built_now


def test_rrf_rewards_agreement(retriever, monkeypatch):
    monkeypatch.setattr(retriever, "vector", lambda q, f, k: [(0, .9), (2, .8), (3, .1)])
    monkeypatch.setattr(retriever.bm25, "search", lambda q, f, k: [(3, 9.0), (0, 5.0)])
    ranked = [i for i, _ in retriever.hybrid("q", R.Filters(), 3)]
    assert ranked[0] == 0          # 1st + 2nd beats 1st-only and 3rd + 1st... both in both lists
    assert set(ranked) == {0, 2, 3}


def test_tokenizer_stems_across_languages():
    assert R.tokenize("Повернення повернути") == ["поверн", "поверн"]
    assert R.tokenize("Rücksendung Rücksendekosten") == ["rückse", "rückse"]


def test_header_is_not_doubled():
    assert R.chunk_header(chunk("a#0", "x", section="Policy > Rules")) == "Policy > Rules"
    assert R.chunk_header(chunk("a#0", "x", section="Article 9")) == "Policy > Article 9"


def test_hit_rule_and_lint():
    q = {"id": "q", "evidence": [{"doc": "returns_2025", "quote": "within  30 days"}]}
    assert is_hit(CHUNKS[0], q)
    assert not is_hit(CHUNKS[1], q)                     # same words, other document
    assert lint([q], CHUNKS) == []
    bad = {"id": "b", "evidence": [{"doc": "returns_2025", "quote": "60 days"}]}
    assert "quote not found" in lint([bad], CHUNKS)[0]


def test_metrics(retriever):
    questions = [
        {"id": "a", "question": "return within 30 days", "evidence": [{"doc": "returns_2025", "quote": "30 days"}],
         "superseded": ["returns_2024"]},
        {"id": "b", "question": "nothing matches zzz", "evidence": [{"doc": "manual", "quote": "reset button"}]},
    ]
    res = run_config(retriever, questions, "bm25")
    assert res["per_question"]["a"]["rank"] == 1
    assert res["recall@5"] == 0.5 and res["mrr@10"] == 0.5 and res["misses@5"] == ["b"]
    trap = [{**questions[0], "question": "return within 30 or 14 days"}]
    res = run_config(retriever, trap, "bm25", R.NO_FILTER)
    assert res["per_question"]["a"]["superseded_top5"] == ["returns_2024#000"]
