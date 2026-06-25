# File: backend/tests/test_response_contract.py

from app.context_builder import DEFAULT_SESSION_ID, build_turn_context
from app.response_composer import compose, compose_chat
from app.schemas.assistant_response import (
    AssistantResponse,
    is_valid_mode,
    is_valid_status,
)


# ── context_builder ──────────────────────────────────────────────────────────

def test_build_context_without_db_is_usable():
    ctx = build_turn_context("hello", session_id="sess-1")

    assert ctx.message == "hello"
    assert ctx.session_id == "sess-1"
    assert ctx.run_id
    assert ctx.history == []
    assert ctx.has_uploaded_files is False
    assert ctx.is_resume is False


def test_build_context_defaults_session_when_missing():
    ctx = build_turn_context("hi")
    assert ctx.session_id == DEFAULT_SESSION_ID


def test_build_context_detects_uploaded_files_and_resume():
    ctx = build_turn_context(
        "summarize it",
        session_id="s",
        run_id="run-123",
        uploaded_file_names=["report.pdf", ""],
    )
    assert ctx.uploaded_file_names == ["report.pdf"]
    assert ctx.has_uploaded_files is True
    assert ctx.is_resume is True
    assert ctx.resume_run_id == "run-123"


def test_trace_seam_records_events():
    ctx = build_turn_context("hi", session_id="s")
    ctx.trace.event("classified", mode="general_chat")

    names = [e["name"] for e in ctx.trace.events]
    assert "context_built" in names
    assert "classified" in names
    assert all("elapsed_ms" in e for e in ctx.trace.events)


# ── response_composer ────────────────────────────────────────────────────────

def test_compose_normalizes_partial_result():
    response = compose({"mode": "general_chat", "final_answer": "Hi there"})

    assert isinstance(response, AssistantResponse)
    assert response.mode == "general_chat"
    assert response.message == "Hi there"      # filled from final_answer
    assert response.final_answer == "Hi there"
    assert response.status == "completed"
    assert response.run_id                      # generated when missing
    assert response.sources == []


def test_compose_chat_builds_clean_single_response():
    response = compose_chat(
        run_id="r1",
        mode="general_chat",
        message="Hello! How can I help?",
        session_id="sess-9",
        decision="general_chat_completed",
    )

    assert response.run_id == "r1"
    assert response.session_id == "sess-9"
    assert response.message == "Hello! How can I help?"
    assert response.meta["is_multi_question"] is False
    assert response.meta["question_count"] == 1


def test_compose_attaches_trace_summary():
    ctx = build_turn_context("hi", session_id="s")
    response = compose({"mode": "general_chat", "message": "hi"}, trace=ctx.trace)

    assert "trace" in response.meta
    assert response.meta["trace"]["turn_id"] == ctx.trace.turn_id


def test_compose_drops_non_dict_sources_and_artifacts():
    response = compose(
        {
            "mode": "execution",
            "message": "done",
            "sources": [{"type": "web"}, "bad", None],
            "artifacts": "nope",
        }
    )
    assert response.sources == [{"type": "web"}]
    assert response.artifacts == []


# ── frozen vocab ─────────────────────────────────────────────────────────────

def test_mode_and_status_validators():
    assert is_valid_mode("general_chat")
    assert is_valid_mode("research_then_execution")
    assert not is_valid_mode("totally_made_up")

    assert is_valid_status("requires_approval")
    assert not is_valid_status("kinda_done")
