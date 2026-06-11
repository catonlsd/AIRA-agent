# File: backend/tests/test_supervisor_intelligence.py
"""Phase 2A — supervisor intelligence: conversation typing, clarification,
capability composition, route confidence, and trace enrichment."""

import pytest

from app.assistant_supervisor import AssistantSupervisor
from app.clarification import clarification_store
from app.context_builder import build_turn_context


@pytest.fixture(autouse=True)
def _clean_clarification_store():
    clarification_store.clear(None)
    yield
    clarification_store.clear(None)
from app.services.trace_service import TraceService
from app.supervisor_reasoning import (
    CAP_DOCUMENT_QA,
    CAP_EXECUTION,
    CAP_WEB_RESEARCH,
    CONTINUATION,
    FOLLOW_UP,
    NEW_TOPIC,
    classify_conversation_type,
    reason_about_turn,
    score_candidate_routes,
)
from app.turn_classifier import DOCUMENT_QA_MODE, EXECUTION_MODE, classify_turn

_ZOOM_HISTORY = [
    {"role": "user", "content": "How do I start a Zoom meeting?"},
    {"role": "assistant", "content": "Open Zoom, sign in, and click New Meeting."},
]


# ── 2A.1 Conversation intelligence ────────────────────────────────────────────


def test_new_topic_classification():
    assert classify_conversation_type("What are the types of soil?", _ZOOM_HISTORY) == NEW_TOPIC
    assert classify_conversation_type("Who invented Linux?", _ZOOM_HISTORY) == NEW_TOPIC
    assert classify_conversation_type("How does a jet engine work?", _ZOOM_HISTORY) == NEW_TOPIC


def test_follow_up_classification():
    assert classify_conversation_type("what about the mobile app?", _ZOOM_HISTORY) == FOLLOW_UP
    assert classify_conversation_type("compare it", _ZOOM_HISTORY) == FOLLOW_UP
    assert classify_conversation_type("what did you just say?", _ZOOM_HISTORY) == FOLLOW_UP


def test_continuation_classification():
    assert classify_conversation_type("continue", _ZOOM_HISTORY) == CONTINUATION
    assert classify_conversation_type("tell me more", _ZOOM_HISTORY) == CONTINUATION
    assert classify_conversation_type("go deeper", _ZOOM_HISTORY) == CONTINUATION


def test_memory_suppressed_for_unrelated_topic():
    """The reported bug: a fresh question after Zoom must reason as NEW_TOPIC."""
    reasoning = reason_about_turn("What are the types of soil?", history=_ZOOM_HISTORY)
    assert reasoning.conversation_type == NEW_TOPIC


def test_no_history_is_new_topic():
    assert classify_conversation_type("tell me more", None) == NEW_TOPIC


# ── 2A.2 Clarification intelligence ──────────────────────────────────────────


def test_vague_build_request_asks_clarification():
    reasoning = reason_about_turn("Build me a RAG system")
    assert reasoning.needs_clarification is True
    assert len(reasoning.clarification_questions) >= 1


def test_vague_deploy_request_asks_clarification():
    reasoning = reason_about_turn("Deploy my application")
    assert reasoning.needs_clarification is True
    # Deploy questions probe the target and destination.
    joined = " ".join(reasoning.clarification_questions).lower()
    assert "which" in joined or "where" in joined


@pytest.mark.parametrize(
    "clear_request",
    [
        "make a ppt about transformers",
        "git push",
        "install package requests",
        "Read file backend/app/main.py",
        "Create file hello.txt",
        "Create a project plan and save it",
    ],
)
def test_clear_requests_do_not_ask_clarification(clear_request):
    reasoning = reason_about_turn(clear_request)
    assert reasoning.needs_clarification is False


@pytest.mark.asyncio
async def test_clarification_path_returns_targeted_questions():
    # A vague non-RAG build keeps the plain targeted-question format.
    supervisor = AssistantSupervisor()
    ctx = build_turn_context("Build me a website", session_id=None, run_id="t1")
    reasoning = reason_about_turn("Build me a website")
    assert reasoning.needs_clarification is True

    result = await supervisor._dispatch_non_chat(
        "Build me a website", reasoning.classification, ctx, reasoning=reasoning
    )

    assert result["mode"] == "clarification"
    assert result["decision"] == "clarification"
    assert result["meta"]["clarification_questions"] == reasoning.clarification_questions
    # The questions appear in the actual reply.
    assert reasoning.clarification_questions[0] in result["message"]


# ── 2A.3 Capability composition ──────────────────────────────────────────────


def test_document_plus_research_composes():
    reasoning = reason_about_turn(
        "Compare my uploaded document with recent research.",
        has_uploaded_files=True,
    )
    assert reasoning.capabilities == [CAP_DOCUMENT_QA, CAP_WEB_RESEARCH]
    assert reasoning.needs_clarification is False


def test_artifact_request_composes_research_and_execution():
    reasoning = reason_about_turn("make a ppt about transformers")
    assert reasoning.capabilities == [CAP_WEB_RESEARCH, CAP_EXECUTION]


def test_single_capability_for_plain_execution():
    reasoning = reason_about_turn("git status")
    assert reasoning.capabilities == [CAP_EXECUTION]


@pytest.mark.asyncio
async def test_composed_document_and_web_dispatch(monkeypatch):
    """Document QA + web research run together and merge into one answer."""
    supervisor = AssistantSupervisor()

    class _DocStub:
        def answer(self, goal, history=None):
            return {
                "message": "The document says X.",
                "sources": [{"source_type": "document", "title": "report.pdf"}],
            }

    class _ResearchStub:
        def run(self, goal, **kwargs):
            return {
                "message": "Recent research says Y.",
                "sources": [{"source_type": "web", "title": "arxiv"}],
            }

    supervisor._documents = _DocStub()
    supervisor.research = _ResearchStub()

    import app.assistant_supervisor as sup_module

    def _fake_generate(self, system, prompt, temperature=0.2):
        assert "The document says X." in prompt
        assert "Recent research says Y." in prompt
        return "Combined: documents say X while research says Y."

    monkeypatch.setattr(sup_module.LLMClient, "generate", _fake_generate)

    goal = "Compare my uploaded document with recent research."
    ctx = build_turn_context(goal, session_id=None, run_id="t2")
    classification = classify_turn(goal, has_uploaded_files=True)

    result = await supervisor._compose_document_and_research(goal, classification, ctx)

    assert result["decision"] == "composed_answer"
    assert result["message"].startswith("Combined:")
    assert len(result["sources"]) == 2
    assert result["meta"]["capabilities_used"] == [CAP_DOCUMENT_QA, CAP_WEB_RESEARCH]
    # Workflow-intelligence stages were traced (2A.6).
    stages = [e.get("stage") for e in ctx.trace.events if e.get("name") == "stage"]
    assert "reading_documents" in stages
    assert "collecting_sources" in stages
    assert "comparing_findings" in stages
    assert "generating_answer" in stages


# ── 2A.4 Route confidence ────────────────────────────────────────────────────


def test_candidate_routes_are_scored_and_bounded():
    classification = classify_turn(
        "Based on the document I uploaded, what is the main conclusion?",
        has_uploaded_files=True,
    )
    candidates = score_candidate_routes(
        "Based on the document I uploaded, what is the main conclusion?",
        classification,
        has_uploaded_files=True,
    )

    assert classification.mode in candidates
    assert all(0.0 <= score <= 1.0 for score in candidates.values())
    # Document evidence should outrank execution for a document question.
    assert candidates[DOCUMENT_QA_MODE] > candidates[EXECUTION_MODE]
    # The selected route keeps at least the router's own confidence.
    assert candidates[classification.mode] >= round(classification.confidence, 2)


def test_reasoning_exposes_selected_route_and_candidates():
    reasoning = reason_about_turn("git status")
    assert reasoning.selected_route == reasoning.classification.mode
    assert reasoning.candidate_routes
    fields = reasoning.trace_fields()
    assert set(fields) == {
        "conversation_type",
        "selected_route",
        "candidate_routes",
        "confidence",
        "clarification_needed",
        "capabilities_used",
    }


# ── 2A.7 Trace schema ────────────────────────────────────────────────────────


def test_trace_record_includes_reasoning_fields():
    record = TraceService().build_record(
        session_id="s",
        run_id="r",
        mode="document_qa",
        latency_ms=12.0,
        final_status="completed",
        conversation_type=NEW_TOPIC,
        selected_route="document_qa",
        candidate_routes={"document_qa": 0.9},
        confidence=0.9,
        clarification_needed=False,
        capabilities_used=[CAP_DOCUMENT_QA],
    )
    assert record["conversation_type"] == NEW_TOPIC
    assert record["selected_route"] == "document_qa"
    assert record["candidate_routes"] == {"document_qa": 0.9}
    assert record["clarification_needed"] is False
    assert record["capabilities_used"] == [CAP_DOCUMENT_QA]


def test_trace_record_backwards_compatible_without_reasoning():
    record = TraceService().build_record(
        session_id="s",
        run_id="r",
        mode="general_chat",
        latency_ms=5.0,
        final_status="completed",
    )
    # Old shape preserved; new fields simply absent.
    assert "conversation_type" not in record
    assert "candidate_routes" not in record
    assert record["mode"] == "general_chat"
    assert record["source_type"] == "model"
