# File: backend/tests/test_document_qa.py

from uuid import uuid4

import pytest

from app.rag.embedding_provider import (
    HashingEmbeddingProvider,
    get_embedding_provider,
)
from app.services.document_qa_service import DocumentQnAService
from app.services.vector_store_service import ChromaVectorStore


def _unique(prefix: str) -> str:
    # Ephemeral Chroma shares collections by name within a process; a unique
    # name per call keeps tests isolated.
    return f"{prefix}_{uuid4().hex[:10]}"


def _service():
    # Dependency-free embeddings + an ephemeral Chroma collection per test.
    return DocumentQnAService(
        embeddings=HashingEmbeddingProvider(),
        store=ChromaVectorStore(_unique("test_docqa"), ephemeral=True),
    )


_PYTHON_PAGES = [
    {"page": 1, "text": "Python is a high-level programming language created by Guido van Rossum. "
                        "It is widely used for web development, data analysis, and automation."},
    {"page": 2, "text": "Python emphasizes readable code and has a large standard library. "
                        "Popular frameworks include Django and FastAPI."},
]


# ── embedding provider ───────────────────────────────────────────────────────

def test_embedding_provider_is_hashing_in_tests():
    provider = get_embedding_provider()
    assert provider.name == "hashing"

    vectors = provider.embed_documents(["hello", "world"])
    assert len(vectors) == 2 and len(vectors[0]) == provider.dimensions
    assert len(provider.embed_query("hello")) == provider.dimensions


# ── vector store ─────────────────────────────────────────────────────────────

def test_chroma_store_add_query_count_delete():
    emb = HashingEmbeddingProvider()
    store = ChromaVectorStore(_unique("test_store"), ephemeral=True)
    texts = ["Python programming language", "The weather is sunny today"]
    store.add(
        ["d1:0", "d1:1"],
        texts,
        [{"document_id": 1, "chunk_index": 0}, {"document_id": 1, "chunk_index": 1}],
        emb.embed_documents(texts),
    )
    assert store.count() == 2

    hits = store.query(emb.embed_query("which programming language"), k=2)
    assert hits[0][2] >= hits[1][2]               # sorted by score desc
    assert "Python" in hits[0][0]                  # most relevant first
    assert 0.0 <= hits[0][2] <= 1.0

    store.delete({"document_id": 1})
    assert store.count() == 0


# ── document Q&A service ─────────────────────────────────────────────────────

def test_ingest_and_retrieve():
    service = _service()
    added = service.ingest(document_id=7, document_name="python.txt", pages=_PYTHON_PAGES)
    assert added >= 1

    chunks = service.retrieve("what is python used for", k=3)
    assert chunks
    assert chunks[0].document_id == 7
    assert chunks[0].document_name == "python.txt"
    assert chunks[0].score >= chunks[-1].score


def test_answer_with_evidence_is_grounded():
    service = _service()
    service.ingest(document_id=7, document_name="python.txt", pages=_PYTHON_PAGES)

    result = service.answer("what is python used for?")
    assert result["mode"] == "document_qa"
    assert result["decision"] == "document_qa_completed"
    assert result["meta"]["has_evidence"] is True
    assert result["meta"]["top_score"] > 0
    assert isinstance(result["message"], str) and result["message"].strip()


def test_answer_without_evidence_is_honest():
    service = _service()
    service.ingest(document_id=7, document_name="python.txt", pages=_PYTHON_PAGES)

    result = service.answer("describe the migration patterns of arctic terns")
    assert result["decision"] == "document_qa_insufficient_evidence"
    assert result["meta"]["has_evidence"] is False
    assert result["sources"] == []
    assert "couldn't find" in result["message"].lower()


def test_answer_with_empty_store_is_honest():
    service = _service()
    result = service.answer("anything at all")
    assert result["meta"]["has_evidence"] is False
    assert result["decision"] == "document_qa_insufficient_evidence"


@pytest.mark.parametrize(
    "query",
    ["summarize this file", "summarize the attached document", "what is this document about", "give me an overview"],
)
def test_summary_requests_use_documents_even_with_low_similarity(query):
    # A summarize/overview request does not semantically match any single chunk,
    # but with documents present it must still be answered from them.
    service = _service()
    service.ingest(document_id=7, document_name="python.txt", pages=_PYTHON_PAGES)

    result = service.answer(query)
    assert result["decision"] == "document_qa_completed"
    assert result["meta"]["has_evidence"] is True
    assert result["meta"]["chunk_count"] >= 1


def test_summary_request_with_empty_store_is_still_honest():
    service = _service()
    result = service.answer("summarize this file")
    assert result["meta"]["has_evidence"] is False
    assert result["decision"] == "document_qa_insufficient_evidence"


def test_specific_offtopic_question_stays_honest():
    service = _service()
    service.ingest(document_id=7, document_name="python.txt", pages=_PYTHON_PAGES)
    result = service.answer("what is the boiling point of mercury")
    assert result["meta"]["has_evidence"] is False
    assert result["decision"] == "document_qa_insufficient_evidence"
