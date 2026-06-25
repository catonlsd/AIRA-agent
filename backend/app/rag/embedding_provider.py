# File: backend/app/rag/embedding_provider.py
"""
Swappable embedding backends.

`EmbeddingProvider` is the interface; the supervisor/RAG code depends only on
this, so the backend can change (local sentence-transformers now; an API or a
hosted store later) without touching callers.

Selection order: AIRA_EMBEDDING_PROVIDER env var, then settings.embedding_provider.
Tests set the env to "hashing" so no heavy model loads.
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

from app.core.config import settings
from app.rag.embeddings import HashingEmbeddings


@runtime_checkable
class EmbeddingProvider(Protocol):
    name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class HashingEmbeddingProvider:
    """Dependency-free, deterministic embeddings. Fast; used in tests/CI."""

    name = "hashing"

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions
        self._impl = HashingEmbeddings(dimensions)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._impl.embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._impl.embed(text)


class SentenceTransformerEmbeddingProvider:
    """Local semantic embeddings via sentence-transformers (lazy-loaded)."""

    name = "sentence_transformers"

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or settings.embedding_model or "all-MiniLM-L6-v2"
        self.dimensions = 384
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
            self.dimensions = self._model.get_sentence_embedding_dimension()
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._ensure_model()
        vectors = model.encode(texts, normalize_embeddings=True)
        return [vector.tolist() for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        model = self._ensure_model()
        return model.encode(text, normalize_embeddings=True).tolist()


_CACHE: dict[str, EmbeddingProvider] = {}


def _resolve_choice() -> str:
    choice = (os.getenv("AIRA_EMBEDDING_PROVIDER") or settings.embedding_provider or "").lower()
    if choice in ("hashing", "hash"):
        return "hashing"
    # "sentence_transformers", "local", anything else -> semantic (with fallback).
    return "sentence_transformers"


def get_embedding_provider() -> EmbeddingProvider:
    key = _resolve_choice()
    if key not in _CACHE:
        if key == "hashing":
            _CACHE[key] = HashingEmbeddingProvider()
        else:
            try:
                _CACHE[key] = SentenceTransformerEmbeddingProvider()
            except Exception:
                # Never hard-fail RAG because the model could not load.
                _CACHE[key] = HashingEmbeddingProvider()
    return _CACHE[key]
