# File: backend/app/services/vector_store_service.py
"""
Swappable vector store.

`VectorStore` is the interface the RAG/document code depends on. `ChromaVectorStore`
is the default backend (ChromaDB). A different store (Pinecone/Weaviate/...) can
be dropped in later without changing callers.

Embeddings are always passed in explicitly so the embedding backend and the
vector store stay independently swappable.
"""

from __future__ import annotations

import os
from typing import Optional, Protocol, runtime_checkable

from app.core.config import settings

# (text, metadata, score) where score is a 0..1 similarity (higher = closer).
SearchHit = tuple[str, dict, float]


@runtime_checkable
class VectorStore(Protocol):
    def add(
        self,
        ids: list[str],
        texts: list[str],
        metadatas: list[dict],
        embeddings: list[list[float]],
    ) -> None: ...

    def query(self, embedding: list[float], k: int, where: Optional[dict] = None) -> list[SearchHit]: ...

    def delete(self, where: dict) -> None: ...

    def count(self) -> int: ...


def _clean_metadata(metadata: dict) -> dict:
    # Chroma rejects None metadata values; keep only scalar, non-None entries.
    cleaned: dict = {}
    for key, value in (metadata or {}).items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            cleaned[key] = value
        else:
            cleaned[key] = str(value)
    return cleaned


class ChromaVectorStore:
    """ChromaDB-backed vector store using cosine similarity."""

    def __init__(
        self,
        collection_name: Optional[str] = None,
        *,
        persist_dir: Optional[str] = None,
        ephemeral: bool = False,
    ) -> None:
        import chromadb

        if ephemeral:
            self._client = chromadb.EphemeralClient()
        else:
            path = persist_dir or os.getenv("AIRA_CHROMA_DIR") or settings.chroma_dir
            self._client = chromadb.PersistentClient(path=path)

        self._collection = self._client.get_or_create_collection(
            name=collection_name or settings.document_collection,
            metadata={"hnsw:space": "cosine"},
        )

    def add(
        self,
        ids: list[str],
        texts: list[str],
        metadatas: list[dict],
        embeddings: list[list[float]],
    ) -> None:
        if not ids:
            return
        self._collection.add(
            ids=ids,
            documents=texts,
            metadatas=[_clean_metadata(m) for m in metadatas],
            embeddings=embeddings,
        )

    def query(self, embedding: list[float], k: int, where: Optional[dict] = None) -> list[SearchHit]:
        result = self._collection.query(
            query_embeddings=[embedding],
            n_results=max(1, k),
            where=where or None,
        )
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        hits: list[SearchHit] = []
        for text, metadata, distance in zip(documents, metadatas, distances):
            # Cosine distance in [0, 2] -> similarity in [0, 1], clamped.
            score = max(0.0, min(1.0, 1.0 - float(distance)))
            hits.append((text, dict(metadata or {}), score))
        return hits

    def delete(self, where: dict) -> None:
        if where:
            self._collection.delete(where=where)

    def count(self) -> int:
        return self._collection.count()


def get_document_vector_store(*, ephemeral: bool = False) -> VectorStore:
    """Return the configured document vector store (ChromaDB by default)."""
    return ChromaVectorStore(ephemeral=ephemeral)
