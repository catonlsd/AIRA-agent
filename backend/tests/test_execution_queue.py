# File: backend/tests/test_execution_queue.py
"""Durable background execution — queue model, worker, and approval enqueue.

A DB-backed ExecutionJob queue runs heavy work (artifact generation) out of the
request path: enqueue is idempotent, claim is atomic (one execution), failure is
honest with bounded retry, and state stays scope-owned and reconnect-safe. The
worker runs real artifact generation + validation and records activity. Approval
can enqueue the continuation without double-executing."""

import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient

from app.accounts import account_service
from app.activity import ARTIFACT_CREATED, activity_service
from app.artifacts.service import ArtifactService, _artifact_to_dict, artifact_store
from app.auth import make_account_token
from app.context_builder import build_turn_context
from app.db.database import ensure_runtime_columns
import app.execution_queue as eq
from app.execution_queue import COMPLETED, FAILED, QUEUED, RUNNING, execution_queue
from app.job_handlers import JOB_ARTIFACT, register_default_handlers
from app.main import app
from app.assistant_supervisor import AssistantSupervisor

ensure_runtime_columns()
register_default_handlers()
client = TestClient(app)


def _account():
    return account_service.register(f"u_{uuid4().hex[:10]}@example.com", "password123", "Alice")


def _auth(account, workspace_id=None):
    h = {"Authorization": f"Bearer {make_account_token(account['id'])}"}
    if workspace_id:
        h["X-Workspace-Id"] = workspace_id
    return h


def _artifact_payload(goal="A deck about Q3 sales", kind="pptx"):
    pending, _ = ArtifactService().plan(goal, kind)  # deterministic, no LLM
    return _artifact_to_dict(pending)


# ── Job model + queue mechanics ──────────────────────────────────────────────


def test_enqueue_creates_durable_scoped_record():
    owner = f"account:{uuid4().hex}"
    job = execution_queue.enqueue(owner, "noop", {"x": 1}, title="T", session_id="s")
    assert job["status"] == QUEUED and job["kind"] == "noop" and job["title"] == "T"
    # Scope/ownership persists and is readable only in-scope.
    assert execution_queue.get(owner, job["id"]) is not None
    assert execution_queue.get(f"account:{uuid4().hex}", job["id"]) is None  # no leak


def test_queued_running_completed_transition():
    owner = f"account:{uuid4().hex}"
    execution_queue.register_handler("ok", lambda job: {"done": True})
    job = execution_queue.enqueue(owner, "ok", {})
    view = execution_queue.claim()
    assert view is not None and execution_queue.get_raw(view.id)["status"] == RUNNING
    execution_queue.transition(view.id, COMPLETED, result={"done": True})
    assert execution_queue.get(owner, job["id"])["status"] == COMPLETED


def test_handler_failure_is_recorded_after_bounded_retry(monkeypatch):
    monkeypatch.setattr(eq.settings, "job_max_attempts", 2)
    owner = f"account:{uuid4().hex}"
    execution_queue.register_handler("boom", lambda job: (_ for _ in ()).throw(RuntimeError("nope")))
    job = execution_queue.enqueue(owner, "boom", {})
    execution_queue.run_once()  # attempt 1 -> re-queued
    assert execution_queue.get(owner, job["id"])["status"] == QUEUED
    execution_queue.run_once()  # attempt 2 -> failed honestly
    final = execution_queue.get(owner, job["id"])
    assert final["status"] == FAILED and "nope" in final["result"]["error"]


def test_enqueue_is_idempotent_by_dedup_key():
    owner = f"account:{uuid4().hex}"
    a = execution_queue.enqueue(owner, "noop", {}, dedup_key="k1")
    b = execution_queue.enqueue(owner, "noop", {}, dedup_key="k1")
    assert a["id"] == b["id"]  # the in-flight job is returned, not duplicated
    assert len(execution_queue.recent(owner)) == 1


def test_claim_is_single_use():
    owner = f"account:{uuid4().hex}"
    execution_queue.enqueue(owner, "noop", {})
    first = execution_queue.claim()
    second = execution_queue.claim()
    assert first is not None and second is None  # only one worker can claim it


def test_cancel_request_on_queued_job():
    owner = f"account:{uuid4().hex}"
    job = execution_queue.enqueue(owner, "noop", {})
    assert execution_queue.cancel_request(owner, job["id"]) is True
    # A queued job cancels immediately and the worker skips it.
    assert execution_queue.get(owner, job["id"])["status"] == "canceled"
    assert execution_queue.run_once() is None


def test_cancel_request_is_scope_checked():
    owner = f"account:{uuid4().hex}"
    job = execution_queue.enqueue(owner, "noop", {})
    assert execution_queue.cancel_request(f"account:{uuid4().hex}", job["id"]) is False


# ── Worker runs real artifact generation ─────────────────────────────────────


def test_worker_executes_artifact_job_and_records_activity():
    owner = f"account:{uuid4().hex}"
    job = execution_queue.enqueue(owner, JOB_ARTIFACT, _artifact_payload(), title="PPTX generation")
    ran = execution_queue.drain()
    assert ran == 1
    final = execution_queue.get(owner, job["id"])
    assert final["status"] == COMPLETED
    # Clean, UI-ready result — a real, downloadable artifact, no internals.
    assert final["result"]["download_url"].startswith("/artifacts/")
    for banned in ("path", "spec", "delivery"):
        assert banned not in final["result"]
    # Worker-produced activity is attributed to the scope (run history coherence).
    assert any(e["type"] == ARTIFACT_CREATED for e in activity_service.recent(owner))


# ── Reconnect-safe HTTP status ───────────────────────────────────────────────


def test_job_status_is_scope_aware_over_http():
    owner, outsider = _account(), _account()
    job = execution_queue.enqueue(f"account:{owner['id']}", JOB_ARTIFACT, _artifact_payload(), title="PPTX generation")
    execution_queue.drain()
    ok = client.get(f"/jobs/{job['id']}", headers=_auth(owner)).json()
    assert ok["job"]["status"] == COMPLETED and ok["job"]["result"]["download_url"]
    # Another account can't see it — 404, existence never leaks.
    assert client.get(f"/jobs/{job['id']}", headers=_auth(outsider)).status_code == 404


def test_recent_jobs_listing():
    owner = _account()
    execution_queue.enqueue(f"account:{owner['id']}", "noop", {}, title="A")
    body = client.get("/jobs", headers=_auth(owner)).json()
    assert body["scope"]["is_workspace"] is False
    assert any(j["title"] == "A" for j in body["jobs"])


# ── Approval enqueues continuation without double-executing ──────────────────


def test_approval_enqueues_artifact_and_is_idempotent(monkeypatch):
    monkeypatch.setattr(eq.settings, "queue_artifacts", True)
    # The supervisor reads the flag from its own settings import — patch there too.
    from app.assistant_supervisor import settings as sup_settings
    monkeypatch.setattr(sup_settings, "queue_artifacts", True)

    supervisor = AssistantSupervisor()
    ctx = build_turn_context("approve", session_id=f"sess_{uuid4().hex[:8]}")
    pending, _ = ArtifactService().plan("A deck about Mars", "pptx")
    artifact_store.set(ctx.owner, pending)

    result = asyncio.run(supervisor._handle_artifact_reply("approve", pending, ctx))
    assert result["decision"] == "artifact_queued" and result["meta"]["job_id"]
    assert result["status"] == "queued" and result["artifacts"] == []

    # A duplicate approval finds the flow already consumed — no second job.
    dup = asyncio.run(supervisor._handle_artifact_reply("approve", pending, ctx))
    assert dup["decision"] == "already_handled"
    assert len(execution_queue.recent(ctx.owner, limit=20)) == 1

    # The worker really produces the artifact off the request path.
    execution_queue.drain()
    assert execution_queue.recent(ctx.owner)[0]["status"] == COMPLETED
