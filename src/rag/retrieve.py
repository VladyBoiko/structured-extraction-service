"""Index and hybrid search: Qdrant (vectors) + BM25 (words) -> RRF fusion -> cross-encoder reranking,
with metadata filters applied inside both searches, before the top-k is taken.

    r = Retriever.build()                                   # structure-aware chunks, default models
    hits = r.search("Скільки днів на повернення?", mode="rerank", filters=Filters(regions=["UA", "INTL"]))
"""

import datetime as dt
import hashlib
import json
import re
import time
from dataclasses import dataclass, field

from qdrant_client import QdrantClient, models
from rank_bm25 import BM25Okapi

from . import config as C
from .embeddings import Embedder

RERANKERS = {
    "bge-m3": "BAAI/bge-reranker-v2-m3-int8",                 # multilingual, 0.57 GB (int8 ONNX)
    "jina": "jinaai/jina-reranker-v2-base-multilingual",      # multilingual, 1.1 GB
    "msmarco": "Xenova/ms-marco-MiniLM-L-6-v2",               # English only, 0.08 GB: the lesson baseline
}
MODES = ("vector", "bm25", "hybrid", "rerank")


def load_chunks(path=C.CHUNKS) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def chunk_header(chunk: dict) -> str:
    """Contextual header: document title + section path. A chunk "| Österreich | 5,90 € |" means nothing
    alone; "Rückgabe und Widerruf (DACH) > Rücksendekosten" in front of it tells both searches what it is."""
    title, section = chunk["title"], chunk["section"]
    if not section:
        return title
    return section if section.startswith(title) else f"{title} > {section}"


def search_text(chunk: dict) -> str:
    return f"{chunk_header(chunk)}\n{chunk['text']}"


# ---------------------------------------------------------------- filters

def date_ordinal(value: str | None) -> int:
    return dt.date.fromisoformat(value).toordinal() if value else 0


@dataclass
class Filters:
    """Metadata filters. Default: only current documents (superseded versions are excluded)."""
    status: str | None = "current"
    regions: list[str] | None = None
    languages: list[str] | None = None
    doc_types: list[str] | None = None
    topics: list[str] | None = None
    as_of: str | None = None          # only documents in force on that date (effective_date <= as_of)

    def _lists(self):
        return (("region", self.regions), ("language", self.languages), ("doc_type", self.doc_types),
                ("topic", self.topics))

    def to_qdrant(self) -> models.Filter | None:
        must = []
        if self.status:
            must.append(models.FieldCondition(key="status", match=models.MatchValue(value=self.status)))
        for key, values in self._lists():
            if values:
                must.append(models.FieldCondition(key=key, match=models.MatchAny(any=values)))
        if self.as_of:
            must.append(models.FieldCondition(key="effective_ord", range=models.Range(lte=date_ordinal(self.as_of))))
        return models.Filter(must=must) if must else None

    def match(self, chunk: dict) -> bool:
        """The same filter in Python, for BM25 (which lives outside Qdrant)."""
        if self.status and chunk["status"] != self.status:
            return False
        for key, values in self._lists():
            if values and chunk[key] not in values:
                return False
        if self.as_of and date_ordinal(chunk["effective_date"]) > date_ordinal(self.as_of):
            return False
        return True


NO_FILTER = Filters(status=None)


# ---------------------------------------------------------------- BM25

def tokenize(text: str) -> list[str]:
    """Lowercase words; long words cut to 6 characters, a crude stemmer that works the same for uk/de/en:
    "повернення"/"повернути" -> "поверн", "Rücksendung"/"Rücksendekosten" -> "rückse"."""
    return [w[:6] for w in re.findall(r"\w+", text.lower())]


class BM25:
    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        self.index = BM25Okapi([tokenize(search_text(c)) for c in chunks])

    def search(self, query: str, filters: Filters, k: int) -> list[tuple[int, float]]:
        scores = self.index.get_scores(tokenize(query))
        order = sorted(range(len(self.chunks)), key=lambda i: -scores[i])
        out = []
        for i in order:
            if scores[i] <= 0:
                break
            if filters.match(self.chunks[i]):     # filter before taking k: k allowed hits, not fewer
                out.append((i, float(scores[i])))
                if len(out) == k:
                    break
        return out


# ---------------------------------------------------------------- index

_client: QdrantClient | None = None


def shared_client() -> QdrantClient:
    """Local (embedded) Qdrant stored on disk. It locks its folder, so one process keeps one client."""
    global _client
    if _client is None:
        import atexit
        C.INDEX_DIR.mkdir(parents=True, exist_ok=True)
        _client = QdrantClient(path=str(C.INDEX_DIR))
        atexit.register(_client.close)   # close while Python is still up (otherwise its destructor fails at exit)
    return _client


def fingerprint(chunks: list[dict], model_key: str) -> str:
    h = hashlib.sha256(model_key.encode())
    for c in chunks:
        h.update(f"{c['chunk_id']}\n{search_text(c)}\n{c['status']}{c['effective_date']}".encode("utf-8"))
    return h.hexdigest()[:16]


class Retriever:
    def __init__(self, chunks: list[dict], name: str, model_key: str = C.EMBED_MODEL,
                 rerank_key: str = C.RERANK_MODEL, client: QdrantClient | None = None):
        self.chunks = chunks
        self.by_id = {c["chunk_id"]: i for i, c in enumerate(chunks)}
        self.embedder = Embedder(model_key)
        self.rerank_key = rerank_key
        self._reranker = None
        self.name = f"{name}__{model_key}"
        self.collection = f"{self.name}__{fingerprint(chunks, model_key)}"
        self.client = client or shared_client()
        self.bm25 = BM25(chunks)
        self.built_now = self._ensure_index()

    @classmethod
    def build(cls, chunks_path=C.CHUNKS, name: str = "structured", **kw) -> "Retriever":
        return cls(load_chunks(chunks_path), name, **kw)

    def _ensure_index(self) -> bool:
        """The collection name carries a fingerprint of the chunks and the model: the same content reuses
        the collection, any change creates a new one and drops the stale ones of the same name.
        (Re-creating a collection under the same name in embedded Qdrant can keep old points.)"""
        if self.client.collection_exists(self.collection) and \
                self.client.count(self.collection).count == len(self.chunks):
            return False
        for col in self.client.get_collections().collections:
            if col.name.startswith(self.name + "__"):
                self.client.delete_collection(col.name)
        vectors = self.embedder.passages([search_text(c) for c in self.chunks])
        self.client.create_collection(self.collection, vectors_config=models.VectorParams(
            size=vectors.shape[1], distance=models.Distance.COSINE))
        points = [models.PointStruct(id=i, vector=vectors[i].tolist(),
                                     payload={**c, "effective_ord": date_ordinal(c["effective_date"])})
                  for i, c in enumerate(self.chunks)]
        for start in range(0, len(points), 256):
            self.client.upsert(self.collection, points=points[start:start + 256])
        return True

    # ------------------------------------------------------------ the four modes

    def vector(self, query: str, filters: Filters, k: int) -> list[tuple[int, float]]:
        points = self.client.query_points(self.collection, query=self.embedder.query(query).tolist(),
                                          query_filter=filters.to_qdrant(), limit=k, with_payload=False).points
        return [(p.id, p.score) for p in points]

    def hybrid(self, query: str, filters: Filters, k: int) -> list[tuple[int, float]]:
        """Reciprocal Rank Fusion: ranks, not scores (cosine 0.8 and BM25 14.2 are not comparable)."""
        fused: dict[int, float] = {}
        for ranking in (self.vector(query, filters, C.CANDIDATES), self.bm25.search(query, filters, C.CANDIDATES)):
            for rank, (i, _) in enumerate(ranking, start=1):
                fused[i] = fused.get(i, 0.0) + 1 / (C.RRF_K + rank)
        return sorted(fused.items(), key=lambda x: -x[1])[:k]

    def rerank(self, query: str, filters: Filters, k: int) -> list[tuple[int, float]]:
        candidates = self.hybrid(query, filters, C.RERANK_CANDIDATES)
        if not candidates:
            return []
        if self._reranker is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            self._reranker = TextCrossEncoder(RERANKERS[self.rerank_key], cache_dir=str(C.MODELS_DIR))
        texts = [search_text(self.chunks[i]) for i, _ in candidates]
        scores = list(self._reranker.rerank(query, texts))
        ranked = sorted(zip((i for i, _ in candidates), scores), key=lambda x: -x[1])
        return [(i, float(s)) for i, s in ranked[:k]]

    def search(self, query: str, mode: str = "rerank", filters: Filters | None = None, k: int = C.TOP_K) -> list[dict]:
        filters = filters if filters is not None else Filters()
        fn = {"vector": self.vector, "bm25": lambda q, f, n: self.bm25.search(q, f, n),
              "hybrid": self.hybrid, "rerank": self.rerank}[mode]
        return [{**self.chunks[i], "score": s, "rank": r} for r, (i, s) in enumerate(fn(query, filters, k), start=1)]


@dataclass
class Timer:
    total: float = 0.0
    n: int = 0
    samples: list[float] = field(default_factory=list)

    def __enter__(self):
        self._t = time.perf_counter()
        return self

    def __exit__(self, *exc):
        d = time.perf_counter() - self._t
        self.total += d
        self.n += 1
        self.samples.append(d)

    @property
    def ms(self) -> float:
        return 1000 * self.total / max(1, self.n)
