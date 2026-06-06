# File: backend/tests/test_document_qa_parity.py
"""
Parity verification: the new Chroma-backed document_qa path vs. the legacy
JSON-store path (RetrievalAgent + AnswerGenerationAgent).

Both use the dependency-free hashing embeddings in tests, so retrieval is
directly comparable. We verify the new path matches the legacy path on document
selection and source metadata, and additionally cover citations, the no-evidence
fallback, persistence across reloads, and repeated questions on one document.
"""

from uuid import uuid4

import pytest

import app.core.llm as llm_module
from app.agents.retrieval_agent import RetrievalAgent
from app.core.config import settings
from app.rag.chunker import chunk_pages
from app.rag.embedding_provider import HashingEmbeddingProvider
from app.rag.vector_store import VectorStore as LegacyVectorStore
from app.services.document_qa_service import DocumentQnAService
from app.services.vector_store_service import ChromaVectorStore

PYTHON_DOC = {
    "id": 11,
    "name": "python_guide.txt",
    "pages": [
        {"page": 1, "text": "Python is a popular high-level programming language used for "
                            "web development, data analysis, and automation. It was created by Guido van Rossum."},
        {"page": 2, "text": "Django and FastAPI are popular Python web frameworks. "
                            "Python emphasizes readable, maintainable code."},
    ],
}

COOKING_DOC = {
    "id": 22,
    "name": "cooking.txt",
    "pages": [
        {"page": 1, "text": "To bake bread you need flour, water, yeast, and salt. "
                            "Knead the dough and let it rise before baking it in a hot oven."},
    ],
}


def _new_service():
    # Unique collection per call: ephemeral Chroma shares collections by name
    # within a process, so a fresh name keeps each test isolated.
    return DocumentQnAService(
        embeddings=HashingEmbeddingProvider(),
        store=ChromaVectorStore(f"parity_{uuid4().hex[:10]}", ephemeral=True),
    )


def _ingest_new(service, doc):
    service.ingest(document_id=doc["id"], document_name=doc["name"], pages=doc["pages"])


def _ingest_legacy(doc):
    """Replicate the /upload ingestion into the legacy JSON vector store."""
    store = LegacyVectorStore()
    chunks = chunk_pages(doc["pages"], settings.chunk_size, settings.chunk_overlap)
    texts, metadatas, ids = [], [], []
    for index, chunk in enumerate(chunks):
        ids.append(f"doc-{doc['id']}-chunk-{index}")
        texts.append(chunk["text"])
        metadatas.append({
            "document_id": doc["id"],
            "document_name": doc["name"],
            "chunk_id": index,
            "chunk_index": index,
            "page": chunk.get("page") or 0,
        })
    store.add_chunks(texts, metadatas, ids)


@pytest.fixture
def legacy_temp(monkeypatch, tmp_path):
    # Isolate the legacy JSON store to a temp dir.
    monkeypatch.setattr(settings, "vector_db_dir", str(tmp_path / "vector_index"))
    yield


# ── Retrieval parity (two documents, pick the right one) ─────────────────────

def test_both_paths_select_the_same_document(legacy_temp):
    service = _new_service()
    _ingest_new(service, PYTHON_DOC)
    _ingest_new(service, COOKING_DOC)

    _ingest_legacy(PYTHON_DOC)
    _ingest_legacy(COOKING_DOC)

    query = "which programming language is good for data analysis"
    new_top = service.retrieve(query, k=3)[0]
    legacy_top = RetrievalAgent().retrieve(query)[0]

    # Both must rank the Python document as the best match.
    assert new_top.document_id == PYTHON_DOC["id"]
    assert legacy_top.document_id == PYTHON_DOC["id"]
    assert new_top.document_name == legacy_top.document_name == PYTHON_DOC["name"]


# ── Source metadata ──────────────────────────────────────────────────────────

def test_new_path_source_metadata_is_correct():
    service = _new_service()
    _ingest_new(service, PYTHON_DOC)

    chunk = service.retrieve("python web frameworks", k=1)[0]
    assert chunk.document_id == PYTHON_DOC["id"]
    assert chunk.document_name == PYTHON_DOC["name"]
    assert chunk.page in (1, 2)
    assert chunk.chunk_id >= 0
    assert chunk.chunk_index >= 0
    assert chunk.text.strip()
    assert 0.0 <= chunk.score <= 1.0


# ── Citations ────────────────────────────────────────────────────────────────

def test_grounded_answer_has_document_citations(monkeypatch):
    # Make the LLM echo document-relevant text so citation filtering keeps it.
    def _doc_answer(self, system, prompt, temperature=0.2):
        return ("Python is a high-level programming language used for web development "
                "and data analysis.")

    monkeypatch.setattr(llm_module.LLMClient, "generate", _doc_answer)

    service = _new_service()
    _ingest_new(service, PYTHON_DOC)

    result = service.answer("what is python")
    assert result["decision"] == "document_qa_completed"
    assert result["meta"]["has_evidence"] is True
    assert result["sources"], "expected at least one document citation"

    citation = result["sources"][0]
    assert citation["source_type"] == "Document"
    assert citation["title"] == PYTHON_DOC["name"]
    assert citation["document_id"] == PYTHON_DOC["id"]
    assert citation["page"] in (1, 2, None)
    assert citation["snippet"]


# ── No-evidence fallback ─────────────────────────────────────────────────────

def test_no_evidence_fallback_is_honest():
    service = _new_service()
    _ingest_new(service, PYTHON_DOC)

    result = service.answer("explain the offside rule in football")
    assert result["meta"]["has_evidence"] is False
    assert result["decision"] == "document_qa_insufficient_evidence"
    assert result["sources"] == []
    assert "couldn't find" in result["message"].lower()


# ── Persistence across reloads ───────────────────────────────────────────────

def test_persisted_documents_survive_a_reload(tmp_path):
    persist_dir = str(tmp_path / "chroma_persist")

    writer = DocumentQnAService(
        embeddings=HashingEmbeddingProvider(),
        store=ChromaVectorStore("parity_persist", persist_dir=persist_dir),
    )
    _ingest_new(writer, PYTHON_DOC)

    # A brand-new service/client pointed at the same directory must see the data.
    reader = DocumentQnAService(
        embeddings=HashingEmbeddingProvider(),
        store=ChromaVectorStore("parity_persist", persist_dir=persist_dir),
    )
    chunks = reader.retrieve("python programming language", k=2)
    assert chunks
    assert chunks[0].document_id == PYTHON_DOC["id"]


# ── Repeated questions on the same document ──────────────────────────────────

def test_same_document_answers_multiple_questions():
    service = _new_service()
    _ingest_new(service, PYTHON_DOC)

    for question in [
        "who created python",
        "what web frameworks does python have",
        "what is python used for",
    ]:
        chunks = service.retrieve(question, k=2)
        assert chunks, f"no chunks for: {question}"
        assert chunks[0].document_id == PYTHON_DOC["id"]
