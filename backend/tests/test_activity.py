# File: backend/tests/test_activity.py
"""Activity/audit history: meaningful, scope-owned product events recorded for
artifacts/documents/runs/members/preferences, listed permission-aware with clean
minimal metadata. Personal and workspace activity isolated; non-members see none."""

import io
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.accounts import account_service
from app.activity import (
    ARTIFACT_CREATED,
    DOCUMENT_UPLOADED,
    RUN_FAILED,
    activity_service,
    severity_for,
)
from app.auth import make_account_token
from app.main import app
from app.workspaces import workspace_service

client = TestClient(app)


def _account():
    return account_service.register(f"u_{uuid4().hex[:10]}@example.com", "password123", "Alice")


def _auth(account, workspace_id=None):
    h = {"Authorization": f"Bearer {make_account_token(account['id'])}"}
    if workspace_id:
        h["X-Workspace-Id"] = workspace_id
    return h


# ── Service: record / read / severity ────────────────────────────────────────


def test_record_and_recent_returns_clean_minimal_metadata():
    owner_key = f"account:{uuid4().hex}"
    activity_service.record(owner_key, ARTIFACT_CREATED, "Created “Roadmap” (PPTX)",
                            actor_name="Ada", status="completed", resource_type="artifact", resource_id="x.pptx")
    events = activity_service.recent(owner_key)
    assert len(events) == 1
    e = events[0]
    assert e["type"] == ARTIFACT_CREATED and e["title"] == "Created “Roadmap” (PPTX)"
    assert e["actor"] == "Ada" and e["severity"] == "info"
    # No internals leak.
    for banned in ("owner", "resource_id", "actor_account_id", "id"):
        assert banned not in e


def test_severity_marks_failures():
    assert severity_for(RUN_FAILED, "failed") == "warn"
    assert severity_for(ARTIFACT_CREATED, "completed") == "info"


def test_activity_is_scope_isolated():
    a, b = f"account:{uuid4().hex}", f"workspace:{uuid4().hex}"
    activity_service.record(a, DOCUMENT_UPLOADED, "Uploaded a.txt")
    activity_service.record(b, DOCUMENT_UPLOADED, "Uploaded b.txt")
    assert [e["title"] for e in activity_service.recent(a)] == ["Uploaded a.txt"]
    assert [e["title"] for e in activity_service.recent(b)] == ["Uploaded b.txt"]


def test_type_filter():
    owner_key = f"account:{uuid4().hex}"
    activity_service.record(owner_key, ARTIFACT_CREATED, "Deck")
    activity_service.record(owner_key, DOCUMENT_UPLOADED, "Doc")
    only_docs = activity_service.recent(owner_key, types=[DOCUMENT_UPLOADED])
    assert [e["type"] for e in only_docs] == [DOCUMENT_UPLOADED]


# ── Events are produced by real actions ──────────────────────────────────────


def test_document_upload_produces_an_activity_event():
    owner = _account()
    ws = client.post("/workspaces", json={"name": "Team"}, headers=_auth(owner)).json()["workspace"]
    client.post("/upload", files={"files": ("notes.txt", io.BytesIO(b"team notes body content here"), "text/plain")},
                data={"session_id": "s"}, headers=_auth(owner, ws["id"]))
    events = client.get("/activity/recent", headers=_auth(owner, ws["id"])).json()["events"]
    assert any(e["type"] == DOCUMENT_UPLOADED and "notes.txt" in e["title"] for e in events)
    assert all(e["actor"] == "Alice" for e in events)  # acting account named


def test_workspace_member_added_produces_event():
    owner, guest = _account(), _account()
    ws = client.post("/workspaces", json={"name": "Team"}, headers=_auth(owner)).json()["workspace"]
    client.post(f"/workspaces/{ws['id']}/members", json={"email": guest["email"], "role": "editor"}, headers=_auth(owner))
    events = client.get("/activity/recent", headers=_auth(owner, ws["id"])).json()["events"]
    assert any(e["type"] == "workspace_member_added" for e in events)


def test_preference_update_produces_event():
    owner = _account()
    ws = client.post("/workspaces", json={"name": "Team"}, headers=_auth(owner)).json()["workspace"]
    client.put("/preferences", json={"key": "answer_length", "value": "concise"}, headers=_auth(owner, ws["id"]))
    events = client.get("/activity/recent", headers=_auth(owner, ws["id"])).json()["events"]
    assert any(e["type"] == "preference_updated" for e in events)


# ── HTTP: permission + scope aware ───────────────────────────────────────────


def test_personal_scope_does_not_see_workspace_activity():
    owner = _account()
    ws = client.post("/workspaces", json={"name": "Team"}, headers=_auth(owner)).json()["workspace"]
    client.post("/upload", files={"files": ("d.txt", io.BytesIO(b"shared body content"), "text/plain")},
                data={"session_id": "s"}, headers=_auth(owner, ws["id"]))
    personal = client.get("/activity/recent", headers=_auth(owner)).json()
    assert personal["scope"]["is_workspace"] is False
    assert personal["events"] == []


def test_viewer_can_see_workspace_activity():
    owner, viewer = _account(), _account()
    ws = client.post("/workspaces", json={"name": "Team"}, headers=_auth(owner)).json()["workspace"]
    workspace_service.add_member(ws["id"], viewer["id"], "viewer")
    client.post("/upload", files={"files": ("shared.txt", io.BytesIO(b"shared workspace document"), "text/plain")},
                data={"session_id": "s"}, headers=_auth(owner, ws["id"]))
    events = client.get("/activity/recent", headers=_auth(viewer, ws["id"])).json()["events"]
    assert any("shared.txt" in e["title"] for e in events)


def test_non_member_header_falls_back_to_personal():
    owner, outsider = _account(), _account()
    ws = client.post("/workspaces", json={"name": "Secret"}, headers=_auth(owner)).json()["workspace"]
    client.post("/upload", files={"files": ("c.txt", io.BytesIO(b"confidential body"), "text/plain")},
                data={"session_id": "s"}, headers=_auth(owner, ws["id"]))
    body = client.get("/activity/recent", headers=_auth(outsider, ws["id"])).json()
    assert body["scope"]["is_workspace"] is False and body["events"] == []
