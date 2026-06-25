# File: backend/tests/test_guided_flow_persistence.py
"""Durable, multi-process-safe, idempotent guided-flow state.

Covers: durable storage, restart safety (fresh store instance), atomic
single-consume idempotency, multi-instance resume, and honest stale/expiry/
already-consumed handling.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.assistant_supervisor import AssistantSupervisor
from app.clarification import action_store, clarification_store, plan_store
from app.context_builder import build_turn_context
from app.guided_flow_store import GuidedFlowStore, guided_flow_store

_SESSION = "persist-session"
_RAG = "Build me a RAG system"
_REPLY = (
    "Clarification response:\n"
    f"Original request: {_RAG}\n"
    "Stack: Next.js + FastAPI + FAISS\n"
    "Tools: Hybrid search + citations\n"
    "Output format: Backend implementation"
)


def _present_and_plan():
    """Drive a session to a stored pending plan via two real supervisor turns."""
    supervisor = AssistantSupervisor()
    return supervisor


async def _to_plan_ready(supervisor):
    from app.supervisor_reasoning import reason_about_turn

    ctx = build_turn_context(_RAG, session_id=_SESSION, run_id="p1")
    reasoning = reason_about_turn(_RAG)
    await supervisor._dispatch_non_chat(_RAG, reasoning.classification, ctx, reasoning=reasoning)
    ctx2 = build_turn_context(_REPLY, session_id=_SESSION, run_id="p2")
    return await supervisor._dispatch(_REPLY, ctx2)


# ── Durable storage + restart safety ─────────────────────────────────────────


def test_store_round_trips_through_the_database():
    guided_flow_store.set(_SESSION, "plan", {"goal": "build", "status": "x"}, run_id="r1")
    assert guided_flow_store.peek(_SESSION, "plan") == {"goal": "build", "status": "x"}


def test_pending_state_survives_a_simulated_restart():
    guided_flow_store.set(_SESSION, "plan", {"goal": "build it"})
    # A brand-new store instance == a fresh process. State is read from the DB.
    fresh = GuidedFlowStore()
    assert fresh.peek(_SESSION, "plan") == {"goal": "build it"}


@pytest.mark.asyncio
async def test_pending_plan_is_persisted_durably():
    supervisor = _present_and_plan()
    result = await _to_plan_ready(supervisor)
    assert result["status"] == "plan_ready"
    # The plan exists in the DB, readable by any instance (not in-process state).
    fresh = GuidedFlowStore()
    persisted = fresh.peek(_SESSION, "plan")
    assert persisted is not None
    assert _RAG in persisted["goal"]
    assert persisted["executable"]["steps"]


# ── Idempotent atomic consume ────────────────────────────────────────────────


def test_consume_returns_payload_exactly_once():
    guided_flow_store.set(_SESSION, "plan", {"goal": "once"})
    first = guided_flow_store.consume(_SESSION, "plan")
    second = guided_flow_store.consume(_SESSION, "plan")
    assert first == {"goal": "once"}
    assert second is None  # already claimed


@pytest.mark.asyncio
async def test_duplicate_plan_approval_does_not_double_execute(monkeypatch, tmp_path):
    from tools.filesystem.file_tool import FileTool

    monkeypatch.setattr(FileTool, "_workspace_root", staticmethod(lambda: tmp_path))

    import app.assistant_supervisor as sup_module

    def _gen(self, system, prompt, temperature=0.2):
        if "JSON array" in system or "JSON array" in prompt:
            return '[{"path": "app/main.py", "purpose": "entry"}]'
        return "print('ok')\n"

    monkeypatch.setattr(sup_module.LLMClient, "generate", _gen)

    supervisor = AssistantSupervisor()
    await _to_plan_ready(supervisor)

    # The race: two requests both peeked the same pending plan before either
    # consumed it (duplicate click / two processes). Only one may execute.
    peeked = plan_store.get(_SESSION)
    assert peeked is not None
    ctx_a = build_turn_context("approve plan", session_id=_SESSION, run_id="a")
    ctx_b = build_turn_context("approve plan", session_id=_SESSION, run_id="b")
    first = await supervisor._handle_plan_reply("approve plan", peeked, ctx_a)
    second = await supervisor._handle_plan_reply("approve plan", peeked, ctx_b)

    # First approval executes; second is honestly told it's already handled.
    assert first["status"] == "awaiting_action_approval"
    assert second["decision"] == "already_handled"
    assert second["meta"]["already_handled"] is True
    assert plan_store.get(_SESSION) is None


# ── Multi-instance resume (request on A, approval on B) ──────────────────────


@pytest.mark.asyncio
async def test_resume_works_across_separate_supervisor_instances():
    producer = AssistantSupervisor()
    await _to_plan_ready(producer)

    # A different supervisor instance (== different process) resumes from the DB.
    consumer = AssistantSupervisor()
    ctx = build_turn_context("approve plan", session_id=_SESSION, run_id="x")
    result = await consumer._dispatch("approve plan", ctx)
    assert result["status"] in ("awaiting_action_approval", "completed", "failed")
    assert result["decision"] != "already_handled"  # the consumer really claimed it


# ── Stale / expiry / missing honesty ─────────────────────────────────────────


def test_expired_flow_cannot_be_consumed():
    guided_flow_store.set(_SESSION, "plan", {"goal": "stale"}, ttl_seconds=1)
    # Backdate the row's expiry so it is now stale.
    from app.db.database import SessionLocal
    from app.db.models import GuidedFlow

    with SessionLocal() as s:
        row = s.query(GuidedFlow).filter_by(session_key=_SESSION, kind="plan").first()
        row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        s.commit()

    assert guided_flow_store.consume(_SESSION, "plan") is None


@pytest.mark.asyncio
async def test_approve_after_expiry_is_honest(monkeypatch):
    supervisor = AssistantSupervisor()
    await _to_plan_ready(supervisor)
    # Expire the pending plan.
    from app.db.database import SessionLocal
    from app.db.models import GuidedFlow

    with SessionLocal() as s:
        row = s.query(GuidedFlow).filter_by(session_key=_SESSION, kind="plan").first()
        row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        s.commit()

    ctx = build_turn_context("approve plan", session_id=_SESSION, run_id="e")
    result = await supervisor._dispatch("approve plan", ctx)
    assert result["decision"] == "already_handled"
    assert "already" in result["message"].lower() or "expired" in result["message"].lower()


def test_missing_flow_consumes_to_none():
    assert guided_flow_store.consume("nobody", "plan") is None
    assert guided_flow_store.peek("nobody", "plan") is None


def test_set_replaces_prior_pending_for_same_kind():
    guided_flow_store.set(_SESSION, "plan", {"v": 1})
    guided_flow_store.set(_SESSION, "plan", {"v": 2})
    assert guided_flow_store.peek(_SESSION, "plan") == {"v": 2}  # only the latest


def test_purge_expired_removes_stale_rows():
    guided_flow_store.set(_SESSION, "action", {"x": 1})
    from app.db.database import SessionLocal
    from app.db.models import GuidedFlow

    with SessionLocal() as s:
        for row in s.query(GuidedFlow).all():
            row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)
        s.commit()
    assert guided_flow_store.purge_expired() >= 1


# ── Adapter round-trips the rich dataclasses ─────────────────────────────────


def test_clarification_adapter_round_trips_int_keys():
    from app.clarification import PendingClarification, option_groups_for

    pending = PendingClarification(
        original_request=_RAG,
        questions=["q"],
        option_groups=option_groups_for(_RAG),
    )
    clarification_store.set(_SESSION, pending)
    loaded = clarification_store.get(_SESSION)
    assert loaded is not None
    # Group keys must come back as ints (JSON stringifies them).
    assert set(loaded.option_groups) == {1, 2, 3}
    assert loaded.option_groups[1]["B"] == "Next.js + FastAPI + FAISS"
