"""Local multilingual embeddings (fastembed, ONNX on CPU) with a persistent cache.

Every vector is stored by sha256(model + text). Re-indexing after a corpus change embeds only the chunks
whose text changed; switching models never mixes vectors of two models.
"""

import hashlib
import json
from dataclasses import dataclass

import numpy as np

from .config import EMBED_CACHE, MODELS_DIR


@dataclass(frozen=True)
class ModelSpec:
    name: str              # fastembed model id
    query_prefix: str      # e5 models are trained with "query: " / "passage: " prefixes
    passage_prefix: str
    max_tokens: int        # input window; longer text is truncated by the model
    note: str


MODELS = {
    "minilm": ModelSpec("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "", "", 128,
                        "384 dims, 0.22 GB; reads only the first 128 tokens of a chunk"),
    "mpnet": ModelSpec("sentence-transformers/paraphrase-multilingual-mpnet-base-v2", "", "", 512,
                       "768 dims, 1.0 GB"),
    "e5-large": ModelSpec("intfloat/multilingual-e5-large", "query: ", "passage: ", 512,
                          "1024 dims, 2.2 GB; trained for retrieval (query/passage pairs), ~100 languages"),
}


class EmbeddingCache:
    """vectors[i] belongs to keys[i]; saved as one .npy matrix + one .json key list per model."""

    def __init__(self, model_key: str):
        self.npy = EMBED_CACHE / f"{model_key}.npy"
        self.keys_file = EMBED_CACHE / f"{model_key}.keys.json"
        self.index: dict[str, int] = {}
        self.vectors = np.zeros((0, 0), dtype=np.float32)
        if self.npy.exists() and self.keys_file.exists():
            self.vectors = np.load(self.npy)
            self.index = {k: i for i, k in enumerate(json.loads(self.keys_file.read_text()))}

    def get(self, key: str) -> np.ndarray | None:
        i = self.index.get(key)
        return None if i is None else self.vectors[i]

    def add(self, keys: list[str], vectors: np.ndarray) -> None:
        start = len(self.index)
        self.vectors = vectors if start == 0 else np.vstack([self.vectors, vectors])
        for j, k in enumerate(keys):
            self.index[k] = start + j
        EMBED_CACHE.mkdir(parents=True, exist_ok=True)
        np.save(self.npy, self.vectors)
        self.keys_file.write_text(json.dumps(list(self.index)))


class Embedder:
    def __init__(self, model_key: str):
        self.key = model_key
        self.spec = MODELS[model_key]
        self.cache = EmbeddingCache(model_key)
        self._model = None
        self.last_computed = 0      # how many texts the last call actually embedded (not from cache)

    def _load(self):
        if self._model is None:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(self.spec.name, cache_dir=str(MODELS_DIR))
        return self._model

    def _embed(self, texts: list[str], prefix: str) -> np.ndarray:
        full = [prefix + t for t in texts]
        keys = [hashlib.sha256(f"{self.spec.name}\n{t}".encode("utf-8")).hexdigest() for t in full]
        missing = {k: t for k, t in zip(keys, full) if self.cache.get(k) is None}
        self.last_computed = len(missing)
        if missing:
            vecs = np.array(list(self._load().embed(list(missing.values()), batch_size=16)), dtype=np.float32)
            vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)      # unit length: dot product = cosine
            self.cache.add(list(missing), vecs)
        return np.stack([self.cache.get(k) for k in keys])

    def passages(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts, self.spec.passage_prefix)

    def query(self, text: str) -> np.ndarray:
        return self._embed([text], self.spec.query_prefix)[0]
