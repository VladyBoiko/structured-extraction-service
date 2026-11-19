"""Deduplication: exact duplicates by content hash, near-duplicates by word-shingle overlap."""

import hashlib
import re


def content_hash(text: str) -> str:
    """The same content gives the same hash, whatever the line endings, spacing or case of whitespace."""
    canonical = " ".join(text.split())
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def shingles(text: str, k: int = 5) -> set[tuple[str, ...]]:
    words = re.findall(r"\w+", text.casefold())
    return {tuple(words[i:i + k]) for i in range(max(1, len(words) - k + 1))}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def near_duplicate_pairs(texts: dict[str, str], threshold: float) -> list[tuple[str, str, float]]:
    """Pairs of keys whose texts overlap above the threshold. O(n^2): fine for a corpus of ~50 documents;
    for millions of documents MinHash + LSH does the same in near-linear time."""
    keys = list(texts)
    sh = {k: shingles(texts[k]) for k in keys}
    pairs = []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            # cheap bound first: jaccard <= min/max of the set sizes
            small, big = sorted((len(sh[a]), len(sh[b])))
            if big == 0 or small / big < threshold:
                continue
            score = jaccard(sh[a], sh[b])
            if score >= threshold:
                pairs.append((a, b, round(score, 3)))
    return pairs
