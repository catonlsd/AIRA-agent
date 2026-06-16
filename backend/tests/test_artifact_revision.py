# File: backend/tests/test_artifact_revision.py
"""Artifact revision follow-ups regenerate a richer artifact (not a generic
execution no-op), and a genuine no-op execution is reported honestly — never a
fake 'Execution complete' when nothing actually ran."""

import pytest

import app.core.llm as llm_module
from app.assistant_supervisor import AssistantSupervisor, _is_artifact_revision
from app.context_builder import build_turn_context
from app.memory.session_memory import session_memory
from app.turn_classifier import EXECUTION_MODE, GENERAL_CHAT_MODE


class _Classification:
    def __init__(self, mode=EXECUTION_MODE, artifact_type=None):
        self.mode = mode
        self.artifact_type = artifact_type
        self.reason = "test"
        self.confidence = "high"


# ── Revision intent detection ────────────────────────────────────────────────


def test_revision_phrases_are_detected():
    assert _is_artifact_revision("increase the content in every slide and add images for each herb")
    assert _is_artifact_revision("make the slides longer")
    assert _is_artifact_revision("add more detail and pictures")
    assert _is_artifact_revision("expand each slide")


def test_non_revision_messages_are_ignored():
    assert not _is_artifact_revision("what are medicinal herbs?")
    assert not _is_artifact_revision("tell me more about chamomile")  # no artifact noun
    assert not _is_artifact_revision("hello there")


# ── Revision routes to artifact regeneration ─────────────────────────────────


@pytest.mark.asyncio
async def test_revision_after_artifact_regenerates_not_generic_execution(monkeypatch):
    monkeypatch.setattr(llm_module.LLMClient, "generate", lambda self, system, prompt, temperature=0.2: "")
    supervisor = AssistantSupervisor()

    # Simulate having just generated a deck on medicinal herbs.
    session_memory.note(
        "owner-r", "sess-r", "last_artifact",
        {"kind": "pptx", "goal": "Make a PPT on medicinal herbs", "title": "Medicinal Herbs"},
    )

    ctx = build_turn_context(
        "increase the content in every slide and add images for each herb",
        session_id="sess-r", owner="owner-r",
    )
    result = await supervisor._dispatch_non_chat(ctx.message, _Classification(), ctx)

    # It went back through the artifact pipeline (a fresh plan to approve), not
    # the generic execution path that would no-op.
    assert result["decision"] == "artifact_plan_ready"
    assert result["meta"]["artifact_pending"] is True
    assert result["meta"]["artifact_kind"] == "pptx"


@pytest.mark.asyncio
async def test_revision_without_prior_artifact_does_not_trigger(monkeypatch):
    # No last_artifact in this session -> revision routing must not fire.
    class _ExecStub:
        async def run(self, goal, *, mode, run_id=None):
            return {"status": "completed", "decision": "execution_completed", "final_answer": "ran tool", "plan": [{"tool_name": "shell_tool"}], "mode": mode}

    supervisor = AssistantSupervisor()
    supervisor.execution = _ExecStub()
    ctx = build_turn_context("add more content to the slides", session_id="fresh", owner="fresh")
    result = await supervisor._dispatch_non_chat(ctx.message, _Classification(), ctx)
    assert result["decision"] != "artifact_plan_ready"  # nothing to revise


# ── Honest no-op execution (no fake "Execution complete") ────────────────────


@pytest.mark.asyncio
async def test_noop_execution_is_reported_honestly():
    class _ExecStub:
        async def run(self, goal, *, mode, run_id=None):
            return {
                "status": "completed",
                "final_answer": "AIRA-X needs a specific executable action before it can run tools.",
                "plan": [{"title": "Clarify executable action", "tool_name": None}],
                "mode": mode,
            }

    supervisor = AssistantSupervisor()
    supervisor.execution = _ExecStub()
    ctx = build_turn_context("do something vague", session_id="n", owner="n")
    result = await supervisor._dispatch_non_chat(ctx.message, _Classification(), ctx)

    # Reported honestly as a clarification in the answer card — NOT a completed
    # execution workflow with a fake "Execution complete".
    assert result["decision"] == "needs_action_clarification"
    assert result["mode"] == GENERAL_CHAT_MODE
    assert "couldn't pin down" in result["message"].lower()
    assert "specific executable action" not in result["message"].lower()


@pytest.mark.asyncio
async def test_real_execution_still_completes_normally():
    class _ExecStub:
        async def run(self, goal, *, mode, run_id=None):
            return {"status": "completed", "decision": "execution_completed", "final_answer": "Ran: git status", "plan": [{"tool_name": "git_tool"}], "mode": mode}

    supervisor = AssistantSupervisor()
    supervisor.execution = _ExecStub()
    ctx = build_turn_context("git status", session_id="e", owner="e")
    result = await supervisor._dispatch_non_chat(ctx.message, _Classification(), ctx)
    assert result["decision"] != "needs_action_clarification"
    assert result["status"] == "completed"
