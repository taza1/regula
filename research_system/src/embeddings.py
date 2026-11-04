"""Embedding interface for optional vector retrieval (FUT-020).

Vectors are an add-on to FTS5/BM25, never a replacement: with no provider
configured, search stays keyword-only. Providers:

* ``local_hash``  - deterministic feature hashing of unigrams and bigrams. Offline,
  free, and purely lexical; it exists so the vector pipeline can be exercised in
  tests and offline runs. It is NOT a semantic model and makes no quality claim.
* ``model_endpoint`` - calls ``embeddings.create`` on the already-configured
  OpenAI-compatible model client. This sends evidence text to that endpoint, so it
  only runs when explicitly selected; the data-handling decision belongs in the
  FUT-001/FUT-020 ADR, not here.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Optional, Protocol

MAX_INPUT_CHARS = 8000
_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")


class EmbeddingError(RuntimeError):
    """The provider failed; callers fall back to keyword retrieval."""


class EmbeddingProvider(Protocol):
    model_id: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def normalize_for_embedding(text: str) -> str:
    """Casefold, collapse whitespace, and bound the input length."""

    return " ".join((text or "").casefold().split())[:MAX_INPUT_CHARS]


class LocalHashEmbedder:
    model_id = "local-hash-v1"

    def __init__(self, dimensions: int = 256):
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(normalize_for_embedding(text)) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        tokens = _TOKEN_RE.findall(text)
        features = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
        vector = [0.0] * self.dimensions
        for feature in features:
            value = int.from_bytes(
                hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest(), "big")
            vector[(value >> 1) % self.dimensions] += 1.0 if value & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in vector))
        return [x / norm for x in vector] if norm else vector


class ModelEndpointEmbedder:
    """Embeddings from an OpenAI-compatible client the application already holds."""

    def __init__(self, client: Any, model: str, dimensions: int, batch_size: int = 16):
        self._client = client
        self.model = model
        self.model_id = f"endpoint:{model}"
        self.dimensions = dimensions
        self.batch_size = max(1, batch_size)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        try:
            for start in range(0, len(texts), self.batch_size):
                batch = [normalize_for_embedding(t) or " " for t in texts[start:start + self.batch_size]]
                response = self._client.embeddings.create(
                    model=self.model, input=batch, dimensions=self.dimensions)
                data = sorted(response.data, key=lambda item: item.index)
                if len(data) != len(batch):
                    raise EmbeddingError("Embedding response size did not match the request.")
                vectors.extend([list(item.embedding) for item in data])
        except EmbeddingError:
            raise
        except Exception as error:  # noqa: BLE001 - never leak provider internals
            raise EmbeddingError("The embedding provider request failed.") from error
        if any(len(v) != self.dimensions for v in vectors):
            raise EmbeddingError("Embedding dimensions did not match the configured size.")
        return vectors


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def create_embedding_provider(
    provider: str, model_config: Any = None, model_client: Any = None
) -> Optional[EmbeddingProvider]:
    """Build the configured provider, or None when vectors are disabled."""

    if provider == "none":
        return None
    if provider == "local_hash":
        return LocalHashEmbedder()
    if provider == "model_endpoint":
        client = getattr(model_client, "_client", None)
        if client is None or model_config is None:
            raise ValueError(
                "RETRIEVAL_EMBEDDING_PROVIDER=model_endpoint needs an OpenAI-compatible "
                "MODEL_PROVIDER (azure or local_proxy).")
        return ModelEndpointEmbedder(
            client, model_config.embedding_model, model_config.embedding_dimensions,
            model_config.embedding_batch_size)
    raise ValueError(f"Unknown embedding provider: {provider}")
