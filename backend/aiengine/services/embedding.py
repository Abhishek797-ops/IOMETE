"""
EmbeddingService — a provider adapter.

Two providers:

* `GeminiEmbeddingProvider` — live, via `google-genai`, when `GEMINI_API_KEY` is set and
  `EMBEDDING_PROVIDER=gemini`.
* `HashingEmbeddingProvider` — the default. A deterministic, seeded feature-hashing
  embedder over character n-grams and word tokens.

The hashing provider is not a placeholder to be apologised for. It is a real, if simple,
embedding model with properties the live one does not have: it is free, instant, offline,
and **deterministic**, which means retrieval-quality tests can assert actual relevance
outcomes (acceptance test 2: "a paraphrase still retrieves the right ticket") rather than
mocking a vector store. Character n-grams give it genuine robustness to typos and
morphology, which is most of what matters for short technical text.

What it does *not* do is capture semantics between unrelated vocabularies — "executors are
being terminated" and "pods keep dying" will not match on the vector channel alone. That is
precisely why retrieval is hybrid: the symptom and metadata channels catch that case, and
`system/status` reports honestly which embedding provider answered.

Dimension discipline: `EMBEDDING_DIM` is asserted at write time. A silent dimension
mismatch produces cosine scores computed over truncated vectors — nonsense that looks like
a working system. Changing the dimension requires `manage.py reembed`.
"""

from __future__ import annotations

import hashlib
import itertools
import logging
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import numpy as np
from django.conf import settings

logger = logging.getLogger("compass.embedding")


class EmbeddingDimensionMismatch(ValueError):
    """Raised when a stored or computed vector does not match `EMBEDDING_DIM`."""


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    provider: str
    model: str
    dim: int
    is_live: bool


class EmbeddingProvider(Protocol):
    name: str
    model: str
    is_live: bool

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


# ---------------------------------------------------------------------------------------
# Deterministic hashing provider
# ---------------------------------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9][a-z0-9_.\-]*")


def _tokenize(text: str) -> list[str]:
    lowered = (text or "").lower()
    words = _WORD.findall(lowered)
    features: list[str] = []
    for word in words:
        features.append(f"w:{word}")
        # Dotted identifiers also contribute their parts, so `spark.executor.memory`
        # partially matches a ticket that only says `executor memory`.
        if "." in word or "_" in word:
            for part in re.split(r"[._\-]", word):
                if len(part) > 2:
                    features.append(f"w:{part}")
    # Word bigrams: cheap phrase sensitivity, so "memory limit" ≠ "limit memory" entirely.
    features.extend(f"b:{a}|{b}" for a, b in itertools.pairwise(words))
    # Character trigrams over the whole string: typo and morphology tolerance.
    compact = re.sub(r"\s+", " ", lowered)
    features.extend(f"c:{compact[i:i + 3]}" for i in range(max(0, len(compact) - 2)))
    return features


@lru_cache(maxsize=200_000)
def _feature_slot(feature: str, dim: int) -> tuple[int, float]:
    """
    Hash a feature to a dimension index and a sign.

    Signed hashing (the "hashing trick") makes collisions cancel on average instead of
    always adding, which keeps collision noise unbiased.
    """
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    index = value % dim
    sign = 1.0 if (value >> 63) & 1 else -1.0
    return index, sign


class HashingEmbeddingProvider:
    """Deterministic feature-hashing embedder with sublinear term weighting."""

    name = "hashing"
    is_live = False

    def __init__(self, dim: int):
        self.dim = dim
        self.model = f"compass-hashing-{dim}"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = np.zeros(self.dim, dtype=np.float32)
            counts: dict[str, int] = {}
            for feature in _tokenize(text):
                counts[feature] = counts.get(feature, 0) + 1
            for feature, count in counts.items():
                index, sign = _feature_slot(feature, self.dim)
                # Sublinear (log) term frequency: a word repeated 50 times in a pasted log
                # must not dominate the vector.
                weight = 1.0 + math.log(count)
                # Structural features are more discriminative than raw character trigrams.
                if feature.startswith("w:"):
                    weight *= 1.6
                elif feature.startswith("b:"):
                    weight *= 1.3
                vector[index] += sign * weight
            norm = float(np.linalg.norm(vector))
            if norm > 0:
                vector /= norm
            vectors.append(vector.tolist())
        return vectors


# ---------------------------------------------------------------------------------------
# Gemini provider
# ---------------------------------------------------------------------------------------


class GeminiEmbeddingProvider:
    """
    Live embeddings via `google-genai`.

    `output_dimensionality` is requested so the live vectors match `EMBEDDING_DIM` and can
    share the same column and index as the hashing provider's. Results are re-normalised
    locally because truncated Gemini embeddings are not unit-length.
    """

    name = "gemini"
    is_live = True

    def __init__(self, dim: int, model: str, api_key: str):
        self.dim = dim
        self.model = model
        self._api_key = api_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        from google.genai import types

        client = self._get_client()
        response = client.models.embed_content(
            model=self.model,
            contents=list(texts),
            config=types.EmbedContentConfig(
                task_type="SEMANTIC_SIMILARITY",
                output_dimensionality=self.dim,
            ),
        )
        vectors: list[list[float]] = []
        for embedding in response.embeddings:
            array = np.asarray(embedding.values, dtype=np.float32)
            if array.shape[0] != self.dim:
                raise EmbeddingDimensionMismatch(
                    f"Gemini returned {array.shape[0]} dimensions, expected {self.dim}. "
                    "Check EMBEDDING_DIM against the model's supported output sizes."
                )
            norm = float(np.linalg.norm(array))
            if norm > 0:
                array /= norm
            vectors.append(array.tolist())
        return vectors


# ---------------------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------------------


def get_provider() -> EmbeddingProvider:
    """
    Resolve the configured provider, falling back to hashing with a warning.

    The fallback is loud: an operator who set `EMBEDDING_PROVIDER=gemini` and forgot the key
    needs to know their deployment is not doing what they think. `system/status` reports
    both the requested and the effective provider for the same reason.
    """
    dim = settings.EMBEDDING_DIM
    requested = settings.EMBEDDING_PROVIDER

    if requested == "gemini":
        if settings.GEMINI_API_KEY:
            try:
                return GeminiEmbeddingProvider(dim, settings.EMBEDDING_MODEL,
                                               settings.GEMINI_API_KEY)
            except ImportError:
                logger.warning(
                    "EMBEDDING_PROVIDER=gemini but google-genai is not installed. "
                    "Falling back to the deterministic hashing embedder."
                )
        else:
            logger.warning(
                "EMBEDDING_PROVIDER=gemini but GEMINI_API_KEY is not set. Falling back to "
                "the deterministic hashing embedder. Retrieval still works; it is lexical "
                "and n-gram based rather than semantic."
            )
    return HashingEmbeddingProvider(dim)


def embed_text(text: str) -> EmbeddingResult:
    return embed_texts([text])[0]


def embed_texts(texts: Sequence[str]) -> list[EmbeddingResult]:
    """Embed a batch. Empty inputs get a zero vector rather than an exception."""
    provider = get_provider()
    dim = settings.EMBEDDING_DIM
    cleaned = [(text or "").strip() for text in texts]

    non_empty_indexes = [i for i, text in enumerate(cleaned) if text]
    vectors: list[list[float]] = [[0.0] * dim for _ in cleaned]

    if non_empty_indexes:
        try:
            computed = provider.embed([cleaned[i] for i in non_empty_indexes])
        except EmbeddingDimensionMismatch:
            raise
        except Exception:
            logger.exception(
                "Embedding provider %s failed; falling back to the hashing embedder for "
                "this batch so the request can still be served.",
                provider.name,
            )
            provider = HashingEmbeddingProvider(dim)
            computed = provider.embed([cleaned[i] for i in non_empty_indexes])

        for slot, vector in zip(non_empty_indexes, computed, strict=False):
            if len(vector) != dim:
                raise EmbeddingDimensionMismatch(
                    f"Provider {provider.name} produced {len(vector)} dimensions, "
                    f"expected {dim}."
                )
            vectors[slot] = vector

    return [
        EmbeddingResult(
            vector=vector,
            provider=provider.name,
            model=provider.model,
            dim=dim,
            is_live=provider.is_live,
        )
        for vector in vectors
    ]


def cosine_similarity(left: Sequence[float] | None, right: Sequence[float] | None) -> float:
    """
    Cosine similarity, clamped to [0, 1].

    Both providers emit unit vectors, so this is a dot product in practice, but the norms
    are computed anyway: a vector that arrived from a fixture or an older provider may not
    be normalised, and silently returning a wrong score is worse than a few extra flops.

    Negative similarities are clamped to 0: "less similar than unrelated" is not a concept
    the ranking layer has any use for, and a negative score would corrupt the RRF fusion.
    """
    if not left or not right:
        return 0.0
    a = np.asarray(left, dtype=np.float32)
    b = np.asarray(right, dtype=np.float32)
    if a.shape != b.shape:
        # Dimension drift: refuse to produce a number rather than compare truncated vectors.
        logger.error(
            "Cosine similarity between mismatched dimensions (%s vs %s). Returning 0.0. "
            "Run `manage.py reembed` after changing EMBEDDING_DIM.",
            a.shape, b.shape,
        )
        return 0.0
    denominator = float(np.linalg.norm(a)) * float(np.linalg.norm(b))
    if denominator == 0:
        return 0.0
    return max(0.0, min(1.0, float(np.dot(a, b)) / denominator))


def describe_provider() -> dict[str, object]:
    provider = get_provider()
    return {
        "provider": provider.name,
        "model": provider.model,
        "dim": settings.EMBEDDING_DIM,
        "is_live": provider.is_live,
        "requested": settings.EMBEDDING_PROVIDER,
    }
