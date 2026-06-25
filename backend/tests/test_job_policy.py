# File: backend/tests/test_job_policy.py
"""Queue scheduling policy — priority, concurrency classes, and fairness.

The durable queue is no longer plain FIFO: higher-priority classes claim first
(created_at FIFO breaks ties), a class at its concurrency cap is skipped, and one
owner can't run more than their fair share — so nothing monopolises workers and
nothing starves. Quotas stay separate; cancel/retry/replay still behave; class /
priority stay internal (never in the user payload)."""

from uuid import uuid4

import pytest

from app import job_policy
from app.core.config import Settings
import app.execution_queue as eq
from app.execution_queue import RUNNING, execution_queue
from app.job_policy import ARTIFACT, INTERACTIVE, MAINTENANCE, VALIDATION


def _enqueue(owner, kind, **kw):
    return execution_queue.enqueue(owner, kind, {}, **kw)


# ── Class assignment ─────────────────────────────────────────────────────────


def test_kinds_map_to_classes():
    assert job_policy.class_for("artifact") is ARTIFACT
    assert job_policy.class_for("startup_validation") is VALIDATION
    assert job_policy.class_for("anything_else") is INTERACTIVE
    # Operator replay is always isolated maintenance, regardless of kind.
    assert job_policy.class_for("artifact", origin="replay") is MAINTENANCE


def test_enqueue_records_class_and_priority_internally():
    owner = f"account:{uuid4().hex}"
    execution_queue.register_handler("artifact_like", lambda j: {"ok": True})
    job = execution_queue.enqueue(owner, "artifact", {}, title="T")
    # The clean (user-facing) payload never leaks scheduler internals.
    assert "exec_class" not in job and "priority" not in job
    # But internally the row carries them for scheduling.
    from app.db.database import SessionLocal
    from app.db.models import ExecutionJob
    with SessionLocal() as s:
        row = s.get(ExecutionJob, job["id"])
        assert row.exec_class == "artifact" and row.priority == ARTIFACT.priority


# ── Priority-aware claiming ──────────────────────────────────────────────────


def test_higher_priority_class_claims_first():
    owner = f"account:{uuid4().hex}"
    # Enqueue a heavy artifact first, then a light interactive job AFTER it.
    heavy = _enqueue(owner, "artifact", title="heavy")
    light = _enqueue(owner, "interactive_chat", title="light")  # -> interactive class
    view = execution_queue.claim()
    # Interactive (priority 100) wins even though the artifact was queued first.
    assert view.id == light["id"]


def test_fifo_breaks_ties_within_a_class():
    owner = f"account:{uuid4().hex}"
    first = _enqueue(owner, "interactive_a", title="first")
    second = _enqueue(owner, "interactive_b", title="second")
    view = execution_queue.claim()
    assert view.id == first["id"]  # same priority -> oldest first


# ── Concurrency-class shaping ────────────────────────────────────────────────


def test_class_at_concurrency_cap_is_skipped(monkeypatch):
    monkeypatch.setattr(eq.settings, "queue_concurrency_artifact", 1)
    monkeypatch.setattr(eq.settings, "queue_per_owner_inflight_cap", 99)  # isolate the class rule
    owner = f"account:{uuid4().hex}"
    # One artifact already running -> the artifact class is at its cap of 1.
    running = _enqueue(owner, "artifact", title="running")
    execution_queue.transition(running["id"], RUNNING)
    queued_artifact = _enqueue(owner, "artifact", title="queued-artifact")
    light = _enqueue(owner, "interactive_x", title="light")
    view = execution_queue.claim()
    # The capped artifact is skipped; the lighter job runs instead.
    assert view.id == light["id"]
    assert execution_queue.get(owner, queued_artifact["id"])["status"] == "queued"


# ── Fairness: no owner monopolises ───────────────────────────────────────────


def test_per_owner_inflight_cap_prevents_monopoly(monkeypatch):
    monkeypatch.setattr(eq.settings, "queue_per_owner_inflight_cap", 1)
    busy = f"account:{uuid4().hex}"
    other = f"account:{uuid4().hex}"
    # `busy` already has one running job -> at the per-owner cap.
    running = _enqueue(busy, "interactive_1", title="busy-running")
    execution_queue.transition(running["id"], RUNNING)
    busy_queued = _enqueue(busy, "interactive_2", title="busy-queued")
    other_queued = _enqueue(other, "interactive_3", title="other-queued")
    view = execution_queue.claim()
    # `busy` is skipped (already at fair share); `other` proceeds — no starvation.
    assert view.owner == other and view.id == other_queued["id"]
    assert execution_queue.get(busy, busy_queued["id"])["status"] == "queued"


def test_scheduling_disabled_falls_back_to_fifo(monkeypatch):
    monkeypatch.setattr(eq.settings, "queue_scheduling_enabled", False)
    owner = f"account:{uuid4().hex}"
    heavy = _enqueue(owner, "artifact", title="heavy-first")
    light = _enqueue(owner, "interactive_y", title="light-second")
    view = execution_queue.claim()
    # FIFO: the artifact queued first wins, ignoring priority.
    assert view.id == heavy["id"]


# ── Config validation ────────────────────────────────────────────────────────


def test_invalid_concurrency_config_is_rejected():
    with pytest.raises(ValueError):
        Settings(queue_concurrency_artifact=-1)


def test_invalid_owner_cap_is_rejected():
    with pytest.raises(ValueError):
        Settings(queue_per_owner_inflight_cap=0)


def test_validate_policy_passes_for_defaults():
    job_policy.validate_policy(eq.settings)  # should not raise


# ── Scheduling coexists with cancel/retry ────────────────────────────────────


def test_canceled_job_does_not_occupy_a_class_slot(monkeypatch):
    monkeypatch.setattr(eq.settings, "queue_concurrency_artifact", 1)
    owner = f"account:{uuid4().hex}"
    a = _enqueue(owner, "artifact", title="a")
    execution_queue.request_cancel(owner, a["id"])  # queued -> canceled (terminal)
    b = _enqueue(owner, "artifact", title="b")
    view = execution_queue.claim()
    # The canceled job frees the class slot, so the next artifact can claim.
    assert view.id == b["id"]
