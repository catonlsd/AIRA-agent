# File: backend/tests/test_document_first.py
"""Milestone A step 3 — document-first behavior: routing, grounded answers,
honest insufficiency, marked web fallback, and clean composition."""

import pytest

from app.assistant_supervisor import AssistantSupervisor
from app.context_builder import build_turn_context
from app.supervisor_reasoning import reason_about_turn
from app.turn_classifier import DOCUMENT_QA_MODE, classify_turn


def _doc_result(has_evidence: bool, message: str, sources=None):
    return {
        "run_id": "d1",
        "status": "completed",
        "decision": "document_qa_completed" if has_evidence else "document_qa_insufficient_evidence",
        "mode": DOCUMENT_QA_MODE,
        "message": message,
        "final_answer": message,
        "sources": sources or [],
        "artifacts": [],
        "approval_summary": None,
        "meta": {"has_evidence": has_evidence},
    }


class _DocStub:
    def __init__(self, has_evidence, sources=None):
        self._has = has_evidence
        self._sources = sources or []

    def answer(self, query, history=None, **kwargs):
        msg = "The report says revenue grew." if self._has else "I couldn't find that in your documents."
        return _doc_result(self._has, msg, self._sources)


class _ResearchStub:
    def __init__(self, answer="Broader research answer.", sources=None, raise_error=False):
        self.calls = 0
        self._answer = answer
        self._sources = sources if sources is not None else [{"source_type": "web", "title": "site"}]
        self._raise = raise_error

    def run(self, goal, **kwargs):
        self.calls += 1
        if self._raise:
            raise RuntimeError("research down")
        return {"message": self._answer, "sources": self._sources}


async def _dispatch_doc(supervisor, goal="What does the report say about revenue?"):
    ctx = build_turn_context(goal, session_id="doc-s", run_id="doc-r", uploaded_file_names=["report.pdf"])
    reasoning = reason_about_turn(goal, has_uploaded_files=True, uploaded_file_names=["report.pdf"])
    return await supervisor._dispatch_non_chat(goal, reasoning.classification, ctx, reasoning=reasoning)


# ── Routing ──────────────────────────────────────────────────────────────────


def test_uploaded_file_question_routes_to_document_qa():
    mode = classify_turn(
        "Based on the document I uploaded, what is the main conclusion?",
        has_uploaded_files=True,
    ).mode
    assert mode == DOCUMENT_QA_MODE


def test_no_files_plain_question_avoids_document_path():
    assert classify_turn("what is python?").mode != DOCUMENT_QA_MODE


# ── Grounded answer vs honest fallback ───────────────────────────────────────


@pytest.mark.asyncio
async def test_document_answer_marked_as_from_uploaded_files():
    supervisor = AssistantSupervisor()
    supervisor._documents = _DocStub(True, sources=[{"source_type": "document", "title": "report.pdf"}])
    supervisor.research = _ResearchStub()

    result = await _dispatch_doc(supervisor)

    assert result["mode"] == DOCUMENT_QA_MODE
    assert result["meta"]["answered_from"] == "uploaded_documents"
    assert supervisor.research.calls == 0  # document-first: no research needed
    assert result["sources"][0]["title"] == "report.pdf"


@pytest.mark.asyncio
async def test_insufficient_evidence_escalates_to_marked_web_fallback():
    supervisor = AssistantSupervisor()
    supervisor._documents = _DocStub(False)
    supervisor.research = _ResearchStub()

    result = await _dispatch_doc(supervisor)

    assert result["mode"] == DOCUMENT_QA_MODE  # routed mode preserved
    assert supervisor.research.calls == 1
    assert result["decision"] == "document_qa_web_fallback"
    assert result["meta"]["answered_from"] == "web_fallback"
    # Honest, clearly-marked transition; no vector internals in the prose.
    assert "don't appear to contain enough information" in result["message"]
    assert "Broader research answer." in result["message"]
    assert "chunk" not in result["message"].lower()
    assert "collection" not in result["message"].lower()
    assert result["sources"][0]["source_type"] == "web"


@pytest.mark.asyncio
async def test_fallback_failure_keeps_honest_insufficiency():
    supervisor = AssistantSupervisor()
    supervisor._documents = _DocStub(False)
    supervisor.research = _ResearchStub(raise_error=True)

    result = await _dispatch_doc(supervisor)

    assert result["meta"]["answered_from"] == "insufficient_documents"
    assert "couldn't find" in result["message"]
    assert result["sources"] == []  # never fabricate sources


@pytest.mark.asyncio
async def test_empty_fallback_answer_emits_no_fake_sources():
    supervisor = AssistantSupervisor()
    supervisor._documents = _DocStub(False)
    supervisor.research = _ResearchStub(answer="", sources=[])

    result = await _dispatch_doc(supervisor)
    assert result["meta"]["answered_from"] == "insufficient_documents"
    assert result["sources"] == []


# ── Ingestion/retrieval through the swappable store ──────────────────────────


def test_ingest_and_retrieve_through_vector_abstraction():
    from app.rag.embedding_provider import HashingEmbeddingProvider
    from app.services.document_qa_service import DocumentQnAService
    from app.services.vector_store_service import ChromaVectorStore

    from uuid import uuid4

    store = ChromaVectorStore(f"test_doc_first_{uuid4().hex[:8]}", ephemeral=True)
    service = DocumentQnAService(
        store=store, embeddings=HashingEmbeddingProvider()
    )
    service.ingest(
        document_id=1,
        document_name="report.pdf",
        pages=[
            {"page": 1, "text": "Revenue grew 40 percent in 2025."},
            {"page": 2, "text": "Costs were flat year over year."},
        ],
    )
    chunks = service.retrieve("what happened to revenue", k=2)
    assert chunks
    # Metadata supports real product needs: file name + page survive retrieval.
    assert chunks[0].document_name == "report.pdf"
    assert chunks[0].page in (1, 2)
