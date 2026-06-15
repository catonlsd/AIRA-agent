# File: backend/app/rag/reranker.py
"""
Reranking layer for retrieved document evidence.

Vector similarity alone returns chunks that are *related* but not always the
*best* support for a question, and it happily returns several near-duplicate
chunks that crowd out diverse evidence. The reranker sits above the vector store
(which stays Chroma-agnostic) and below answer composition:

    retrieve wide candidate pool -> rerank by blended relevance ->
    drop near-duplicates -> keep the top-k best, diverse chunks.

`Reranker` is a small Protocol so the strategy is swappable (a cross-encoder or
LLM reranker can drop in later). `LexicalReranker` is the maintainable default:
it blends the vector score with query-term coverage and lightly favours diverse
sources, then de-prioritises overlapping/near-duplicate chunks. It is cheap,
deterministic, and works with the dependency-free hashing embeddings in CI.

Important: a chunk's `.score` stays the RAW vector similarity end-to-end, so the
downstream sufficiency threshold keeps its original meaning. Reranking only
changes order and membership, never the score's semantics.
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from app.rag.schemas import RetrievedChunk

_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are",
    "was", "were", "be", "by", "with", "as", "at", "it", "this", "that", "these",
    "those", "what", "which", "who", "whom", "how", "why", "when", "where", "do",
    "does", "did", "can", "could", "should", "would", "about", "from", "into",
    "your", "you", "my", "me", "i", "we", "they", "them", "their", "its",
}


def _terms(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9][a-z0-9\-]{2,}", text.lower())
        if word not in _STOPWORDS
    }


def _coverage(query_terms: set[str], chunk_terms: set[str]) -> float:
    if not query_terms:
        return 0.0
    return len(query_terms & chunk_terms) / len(query_terms)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


@runtime_checkable
class Reranker(Protocol):
    def rerank(
        self, query: str, chunks: list[RetrievedChunk], *, top_k: int
    ) -> list[RetrievedChunk]: ...


class LexicalReranker:
    """Blend vector score with lexical query coverage, then drop duplicates."""

    def __init__(
        self,
        *,
        vector_weight: float = 0.6,
        lexical_weight: float = 0.4,
        duplicate_threshold: float = 0.82,
    ) -> None:
        self.vector_weight = vector_weight
        self.lexical_weight = lexical_weight
        self.duplicate_threshold = duplicate_threshold

    def relevance(self, query_terms: set[str], chunk: RetrievedChunk) -> float:
        """Blended 0..1 ranking score (not stored on the chunk)."""
        coverage = _coverage(query_terms, _terms(chunk.text))
        vector = max(0.0, min(1.0, chunk.score))
        return self.vector_weight * vector + self.lexical_weight * coverage

    def rerank(
        self, query: str, chunks: list[RetrievedChunk], *, top_k: int
    ) -> list[RetrievedChunk]:
        if not chunks:
            return []
        query_terms = _terms(query)

        ranked = sorted(
            chunks,
            key=lambda c: (self.relevance(query_terms, c), c.score),
            reverse=True,
        )

        # Greedily keep the best chunk; skip a later chunk that is a near-duplicate
        # of one already kept (overlapping windows / repeated boilerplate), so the
        # evidence passed to composition stays diverse.
        kept: list[RetrievedChunk] = []
        kept_terms: list[set[str]] = []
        for chunk in ranked:
            terms = _terms(chunk.text)
            if any(
                _jaccard(terms, prior) >= self.duplicate_threshold
                for prior in kept_terms
            ):
                continue
            kept.append(chunk)
            kept_terms.append(terms)
            if len(kept) >= top_k:
                break
        return kept


_RERANKER: Reranker = LexicalReranker()


def get_reranker() -> Reranker:
    """Process-wide default reranker (swap the strategy here later)."""
    return _RERANKER
