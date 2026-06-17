# File: backend/tests/test_shared_resources.py
"""Shared-resource discovery for the active scope: recent artifacts, documents,
and runs — owner-scoped, permission-aware, with clean minimal metadata. Personal
and workspace scopes are isolated; non-members never see workspace resources."""

import io
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.accounts import account_service
from app.auth import make_account_token, owner_token_for
from app.core.config import settings
from app.db.database import ensure_runtime_columns
from app.main import app
from app.shared_resources import SharedResourceService
from app.workspaces import workspace_service

ensure_runtime_columns()
client = TestClient(app)


def _account():
    return account_service.register(f"u_{uuid4().hex[:10]}@example.com", "password123", "U")


def _auth(account, workspace_id=None):
    h = {"Authorization": f"Bearer {make_account_token(account['id'])}"}
    if workspace_id:
        h["X-Workspace-Id"] = workspace_id
    return h


def _seed_artifact(owner_key: str, name: str = "quarterly_review.pptx") -> None:
    token = owner_token_for(owner_key)
    owner_dir = Path(settings.artifacts_dir).resolve() / token
    owner_dir.mkdir(parents=True, exist_ok=True)
    (owner_dir / name).write_bytes(b"PK fake artifact bytes " * 60)


# ── Service-level: artifacts / documents listing ────────────────────────────


def test_recent_artifacts_returns_clean_minimal_metadata():
    svc = SharedResourceService()
    owner_key = f"account:{uuid4().hex}"
    _seed_artifact(owner_key, "team_strategy.pptx")
    items = svc.recent_artifacts(owner_key)
    assert len(items) == 1
    art = items[0]
    assert art["title"] == "Team strategy" and art["type"] == "PPTX"
    assert art["download_url"].startswith("/artifacts/") and art["filename"] == "team_strategy.pptx"
    assert art["size"]  # human-readable
    # No raw internals.
    for banned in ("owner", "owner_key", "path", "token"):
        assert banned not in art


def test_artifacts_are_scope_isolated():
    svc = SharedResourceService()
    a, b = f"account:{uuid4().hex}", f"workspace:{uuid4().hex}"
    _seed_artifact(a, "personal.pptx")
    _seed_artifact(b, "shared.pptx")
    assert {i["filename"] for i in svc.recent_artifacts(a)} == {"personal.pptx"}
    assert {i["filename"] for i in svc.recent_artifacts(b)} == {"shared.pptx"}
    assert svc.recent_artifacts(f"workspace:{uuid4().hex}") == []  # empty scope


# ── HTTP: /resources/recent is scope + permission aware ──────────────────────


def test_recent_resources_lists_workspace_documents_for_members():
    owner = _account()
    ws = client.post("/workspaces", json={"name": "Team"}, headers=_auth(owner)).json()["workspace"]
    # Upload a doc while acting in the workspace.
    client.post("/upload", files={"files": ("onboarding.txt", io.BytesIO(b"team onboarding checklist and notes"), "text/plain")},
                data={"session_id": "s"}, headers=_auth(owner, ws["id"]))

    body = client.get("/resources/recent", headers=_auth(owner, ws["id"])).json()
    assert body["scope"]["is_workspace"] is True and body["scope"]["label"] == "Team"
    names = {d["name"] for d in body["documents"]}
    assert "onboarding.txt" in names
    assert all("owner" not in d for d in body["documents"])  # clean metadata


def test_personal_scope_does_not_see_workspace_resources():
    owner = _account()
    ws = client.post("/workspaces", json={"name": "Team"}, headers=_auth(owner)).json()["workspace"]
    _seed_artifact(ws["owner_key"], "deck.pptx")
    client.post("/upload", files={"files": ("teamdoc.txt", io.BytesIO(b"shared team document body"), "text/plain")},
                data={"session_id": "s"}, headers=_auth(owner, ws["id"]))

    personal = client.get("/resources/recent", headers=_auth(owner)).json()
    assert personal["scope"]["is_workspace"] is False
    assert personal["artifacts"] == [] and personal["documents"] == []


def test_workspace_member_viewer_can_discover_resources():
    owner, viewer = _account(), _account()
    ws = client.post("/workspaces", json={"name": "Team"}, headers=_auth(owner)).json()["workspace"]
    workspace_service.add_member(ws["id"], viewer["id"], "viewer")
    _seed_artifact(ws["owner_key"], "report.pptx")

    body = client.get("/resources/recent", headers=_auth(viewer, ws["id"])).json()
    # A viewer can see/discover the shared artifact (read is allowed for all roles).
    assert any(a["filename"] == "report.pptx" for a in body["artifacts"])
    assert body["scope"]["is_workspace"] is True


def test_non_member_header_falls_back_to_personal_no_leak():
    owner, outsider = _account(), _account()
    ws = client.post("/workspaces", json={"name": "Secret"}, headers=_auth(owner)).json()["workspace"]
    _seed_artifact(ws["owner_key"], "confidential.pptx")
    # Outsider presents the workspace header but isn't a member -> personal scope.
    body = client.get("/resources/recent", headers=_auth(outsider, ws["id"])).json()
    assert body["scope"]["is_workspace"] is False
    assert all(a["filename"] != "confidential.pptx" for a in body["artifacts"])


def test_runs_are_owner_scoped():
    from app.services.trace_service import TraceService

    tracer = TraceService()
    owner_key = f"account:{uuid4().hex}"
    other_key = f"workspace:{uuid4().hex}"
    tracer.persist(tracer.build_record(
        session_id="s", run_id="r1", mode="document_qa", latency_ms=10, final_status="completed", owner=owner_key,
    ))
    tracer.persist(tracer.build_record(
        session_id="s", run_id="r2", mode="execution", latency_ms=10, final_status="completed", owner=other_key,
    ))
    svc = SharedResourceService(tracer=tracer)
    runs = svc.recent_runs(owner_key)
    assert any(r["label"] == "Document answer" for r in runs)
    # The other scope's run never appears.
    assert all(r["label"] != "Workflow run" for r in runs)
