"""Offline retrieval helpers: FTS5 query building, local embeddings, rank fusion.

The embedding here is a deterministic feature-hashing vector, not a learned
model. It gives hybrid retrieval a semantic-ish signal (unigram and bigram
overlap) with no network or model dependency; a real embedding provider can
replace ``embed_text`` behind the same cosine interface.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Iterable

EMBEDDING_DIMENSIONS = 256
RRF_K = 60

_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")

# Terms that signal opposing findings. Appended to a topic query so the
# contradictory search looks for the same subject with negative language.
CONTRADICTION_TERMS = (
    "no effect",
    "not effective",
    "fails",
    "contradicts",
    "refutes",
    "inconsistent",
    "negative results",
    "failed to replicate",
)


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.casefold())


def build_fts_query(query: str) -> str:
    """Turn free text into a safe FTS5 OR-query of quoted prefix-free terms."""

    terms = list(dict.fromkeys(tokenize(query)))
    return " OR ".join(f'"{term}"' for term in terms)


def build_contradictory_queries(query: str) -> list[str]:
    """FTS5 match strings: any topic term AND one exact negation phrase.

    Requiring the phrase keeps topic terms from drowning out the negation
    signal in BM25; documents without opposing language are not returned.
    """

    topic = build_fts_query(query)
    if not topic:
        return []
    return [f'({topic}) AND "{term}"' for term in CONTRADICTION_TERMS]


def embed_text(text: str, dimensions: int = EMBEDDING_DIMENSIONS) -> list[float]:
    tokens = tokenize(text)
    features = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
    vector = [0.0] * dimensions
    for feature in features:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        sign = 1.0 if value & 1 else -1.0
        vector[(value >> 1) % dimensions] += sign
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else vector


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def reciprocal_rank_fusion(
    rankings: Iterable[tuple[float, list[str]]], k: int = RRF_K
) -> list[tuple[str, float]]:
    """Fuse ranked id lists. Each ranking is (weight, ids best-first)."""

    scores: dict[str, float] = {}
    for weight, ids in rankings:
        for position, item in enumerate(ids, start=1):
            scores[item] = scores.get(item, 0.0) + weight / (k + position)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
