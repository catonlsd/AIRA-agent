# File: backend/tests/test_live_status.py
"""Unified, reconnect-safe live status for inline + queued work.

A durable job maps into one curated phase vocabulary (shared with the streaming
presenter), so a reconnecting client re-reads the snapshot and resumes the right
phase — or resolves honestly to a terminal phase if the work already finished.
Scope-checked; never leaks worker/queue internals."""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.accounts import account_service
from app.artifacts.service import ArtifactService, _artifact_to_dict
from app.auth import make_account_token
from app.execution_queue import RUNNING, execution_queue
from app.job_handlers import JOB_ARTIFACT, register_default_handlers
from app.live_status import job_phase, live_snapshot, live_status_service
from app.main import app
from app.workspaces import workspace_service

register_default_handlers()
client = TestClient(app)


def _account():
    return account_service.register(f"u_{uuid4().hex[:10]}@example.com", "password123", "Alice")


def _auth(account, workspace_id=None):
    h = {"Authorization": f"Bearer {make_account_token(account['id'])}"}
    if workspace_id:
        h["X-Workspace-Id"] = workspace_id
    return h


def _artifact_payload(goal="A deck about Q3", kind="pptx"):
    pending, _ = ArtifactService().plan(goal, kind)
    return _artifact_to_dict(pending)


# ── Phase mapping (unified vocabulary) ───────────────────────────────────────


def test_job_phase_maps_lifecycle_to_calm_labels():
    assert job_phase("queued")["label"] == "Queued"
    assert job_phase("running")["label"] == "Working in the background"
    assert job_phase("validating")["label"] == "Running validation"
    assert job_phase("completed")["tone"] == "good"
    assert job_phase("failed")["tone"] == "bad"
    assert job_phase("cancel_requested")["label"] == "Canceling"
    # A freshly-queued retry reads honestly as a re-run.
    assert job_phase("queued", origin="retry")["label"] == "Retrying"


def test_live_snapshot_is_clean_and_marks_terminal():
    active = live_snapshot({"id": "j1", "status": "running", "title": "T", "result": None})
    assert active["state"] == "active" and active["phase"]["key"] == "working_background"
    done = live_snapshot({"id": "j2", "status": "completed", "result": {"download_url": "/x"}})
    assert done["state"] == "terminal" and done["phase"]["label"] == "Completed"
    # No worker/queue internals leak into the snapshot.
    for banned in ("owner", "exec_class", "priority", "payload", "dedup_key", "attempts"):
        assert banned not in done


# ── Service: scope-checked snapshot + active list ────────────────────────────


def test_snapshot_is_scope_checked():
    owner = f"account:{uuid4().hex}"
    job = execution_queue.enqueue(owner, "noop", {}, title="T")
    assert live_status_service.snapshot(owner, job["id"]) is not None
    assert live_status_service.snapshot(f"account:{uuid4().hex}", job["id"]) is None  # no leak


def test_active_lists_only_non_terminal_work():
    owner = f"account:{uuid4().hex}"
    execution_queue.register_handler("ok_live", lambda j: {"ok": True})
    done = execution_queue.enqueue(owner, "ok_live", {}, title="done")
    execution_queue.drain()
    running = execution_queue.enqueue(owner, "noop", {}, title="active")
    execution_queue.transition(running["id"], RUNNING)
    active = live_status_service.active(owner)
    ids = {s["id"] for s in active}
    assert running["id"] in ids and done["id"] not in ids
    assert all(s["state"] == "active" for s in active)


# ── HTTP: reconnect-safe, scope-aware ────────────────────────────────────────


def test_job_endpoint_carries_unified_phase():
    owner = _account()
    job = execution_queue.enqueue(f"account:{owner['id']}", "noop", {}, title="T")
    body = client.get(f"/jobs/{job['id']}", headers=_auth(owner)).json()
    assert body["job"]["phase"]["label"] == "Queued"


def test_live_snapshot_endpoint_resumes_phase_and_is_scoped():
    owner, outsider = _account(), _account()
    job = execution_queue.enqueue(f"account:{owner['id']}", "noop", {}, title="T")
    execution_queue.transition(job["id"], RUNNING)
    ok = client.get(f"/jobs/{job['id']}/live", headers=_auth(owner)).json()
    assert ok["live"]["state"] == "active" and ok["live"]["phase"]["key"] == "working_background"
    # Another account can't resume it — 404, existence never leaks.
    assert client.get(f"/jobs/{job['id']}/live", headers=_auth(outsider)).status_code == 404


def test_reconnect_after_completion_shows_terminal_not_fake_progress():
    owner = _account()
    job = execution_queue.enqueue(f"account:{owner['id']}", JOB_ARTIFACT, _artifact_payload(), title="PPTX generation")
    execution_queue.drain()  # finishes the real artifact off-request
    # A client reconnecting AFTER completion sees the honest terminal state.
    live = client.get(f"/jobs/{job['id']}/live", headers=_auth(owner)).json()["live"]
    assert live["state"] == "terminal" and live["phase"]["label"] == "Completed"
    assert live["result"]["download_url"].startswith("/artifacts/")


def test_live_list_endpoint_restores_active_work():
    owner = _account()
    running = execution_queue.enqueue(f"account:{owner['id']}", "noop", {}, title="bg")
    execution_queue.transition(running["id"], RUNNING)
    body = client.get("/jobs/live", headers=_auth(owner)).json()
    assert any(s["id"] == running["id"] and s["state"] == "active" for s in body["live"])


def test_workspace_member_sees_live_non_member_does_not():
    owner, viewer, outsider = _account(), _account(), _account()
    ws = client.post("/workspaces", json={"name": "Team"}, headers=_auth(owner)).json()["workspace"]
    workspace_service.add_member(ws["id"], viewer["id"], "viewer")
    job = execution_queue.enqueue(ws["owner_key"], "noop", {}, title="WS")
    execution_queue.transition(job["id"], RUNNING)
    # A member can resume the shared live view.
    assert client.get(f"/jobs/{job['id']}/live", headers=_auth(viewer, ws["id"])).json()["live"]["state"] == "active"
    # An outsider (falls back to personal scope) can't see it.
    assert client.get(f"/jobs/{job['id']}/live", headers=_auth(outsider, ws["id"])).status_code == 404
