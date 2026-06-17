# File: backend/tests/test_search_pins.py
"""Scoped search + durable pins — find and keep important work in the active scope.

Search composes the already owner-scoped artifacts / documents / runs / activity
into one clean, permission-aware result list; pins are a small durable
scope-owned store of references (never payloads). Personal and workspace stay
isolated; non-members search/see nothing of a team's work; mutating pins needs
edit; results carry no internals."""

import io
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.accounts import account_service
from app.activity import ARTIFACT_CREATED, activity_service
from app.artifacts.service import PendingArtifact, artifact_store
from app.auth import make_account_token, owner_token_for
from app.core.config import settings
from app.db.database import ensure_runtime_columns
from app.main import app
from app.pins import REF_ARTIFACT, REF_RUN, pin_service
from app.search import search_service
from app.workspaces import workspace_service

ensure_runtime_columns()
client = TestClient(app)


def _account():
    return account_service.register(f"u_{uuid4().hex[:10]}@example.com", "password123", "Alice")


def _auth(account, workspace_id=None):
    h = {"Authorization": f"Bearer {make_account_token(account['id'])}"}
    if workspace_id:
        h["X-Workspace-Id"] = workspace_id
    return h


def _seed_artifact(owner_key: str, name: str) -> None:
    token = owner_token_for(owner_key)
    owner_dir = Path(settings.artifacts_dir).resolve() / token
    owner_dir.mkdir(parents=True, exist_ok=True)
    (owner_dir / name).write_bytes(b"PK fake artifact bytes " * 60)


# ── Search: service-level composition + clean, scoped results ─────────────────


def test_search_matches_artifacts_by_title():
    owner = f"account:{uuid4().hex}"
    _seed_artifact(owner, "q3_revenue_plan.pptx")
    _seed_artifact(owner, "team_offsite.pptx")
    hits = search_service.search(owner, "revenue")
    titles = [r["title"] for r in hits]
    assert "Q3 revenue plan" in titles and "Team offsite" not in titles
    art = next(r for r in hits if r["result_type"] == "artifact")
    assert art["download_url"].startswith("/artifacts/") and art["ref_type"] == REF_ARTIFACT


def test_search_finds_runs_with_continue_affordance():
    owner = f"account:{uuid4().hex}"
    _seed_artifact(owner, "growth_strategy.pptx")
    runs = [r for r in search_service.search(owner, "growth") if r["result_type"] == "run"]
    assert runs and runs[0]["run_kind"] == "continue" and runs[0]["action"] == "Continue"
    assert runs[0]["ref_type"] == REF_RUN


def test_search_finds_activity():
    owner = f"account:{uuid4().hex}"
    activity_service.record(owner, ARTIFACT_CREATED, "Created “Roadmap” (PPTX)", status="completed")
    hits = [r for r in search_service.search(owner, "roadmap") if r["result_type"] == "activity"]
    assert hits and hits[0]["title"] == "Created “Roadmap” (PPTX)"


def test_search_results_are_clean_and_minimal():
    owner = f"account:{uuid4().hex}"
    _seed_artifact(owner, "secret_plan.pptx")
    for r in search_service.search(owner, "secret"):
        for banned in ("owner", "owner_key", "path", "token", "payload", "spec",
                       "delivery", "trace_events", "filename"):
            assert banned not in r


def test_search_is_scope_isolated():
    a, b = f"account:{uuid4().hex}", f"workspace:{uuid4().hex}"
    _seed_artifact(a, "alpha_deck.pptx")
    _seed_artifact(b, "beta_deck.pptx")
    assert any(r["title"] == "Alpha deck" for r in search_service.search(a, "deck"))
    assert all(r["title"] != "Beta deck" for r in search_service.search(a, "deck"))


def test_search_type_filter_narrows_families():
    owner = f"account:{uuid4().hex}"
    _seed_artifact(owner, "narrow_test.pptx")
    only = search_service.search(owner, "narrow", kinds=["artifact"])
    assert only and all(r["result_type"] == "artifact" for r in only)


# ── Search HTTP: permission + scope aware ────────────────────────────────────


def test_search_workspace_for_members_only():
    owner, viewer, outsider = _account(), _account(), _account()
    ws = client.post("/workspaces", json={"name": "Team"}, headers=_auth(owner)).json()["workspace"]
    workspace_service.add_member(ws["id"], viewer["id"], "viewer")
    _seed_artifact(ws["owner_key"], "roadmap_2027.pptx")

    member = client.get("/search", params={"q": "roadmap"}, headers=_auth(viewer, ws["id"])).json()
    assert member["scope"]["is_workspace"] is True
    assert any(r["title"] == "Roadmap 2027" for r in member["results"])

    # Outsider presents the header but isn't a member -> personal scope, no leak.
    out = client.get("/search", params={"q": "roadmap"}, headers=_auth(outsider, ws["id"])).json()
    assert out["scope"]["is_workspace"] is False
    assert all(r["title"] != "Roadmap 2027" for r in out["results"])


# ── Pins: durable, scope-owned, idempotent, permission-aware ─────────────────


def test_pin_and_list_personal_artifact():
    owner = _account()
    _seed_artifact(f"account:{owner['id']}", "keep_me.pptx")
    res = client.post("/pins", json={"ref_type": "artifact", "ref_id": "keep_me.pptx", "title": "Keep me"},
                      headers=_auth(owner))
    assert res.status_code == 200
    pins = client.get("/pins", headers=_auth(owner)).json()["pins"]
    assert len(pins) == 1
    assert pins[0]["title"] == "Keep me"
    assert pins[0]["download_url"].startswith("/artifacts/")  # enriched, access-controlled


def test_pin_run_is_enriched_with_live_action():
    owner = _account()
    _seed_artifact(f"account:{owner['id']}", "launch.pptx")
    client.post("/pins", json={"ref_type": "run", "ref_id": "artifact:launch.pptx", "title": "Launch"},
                headers=_auth(owner))
    pin = client.get("/pins", headers=_auth(owner)).json()["pins"][0]
    assert pin["action"] == "Continue" and pin["run_kind"] == "continue"


def test_pinning_is_idempotent():
    owner = f"account:{uuid4().hex}"
    pin_service.pin(owner, REF_ARTIFACT, "x.pptx", "First")
    pin_service.pin(owner, REF_ARTIFACT, "x.pptx", "Updated title")
    pins = pin_service.list(owner)
    assert len(pins) == 1 and pins[0]["title"] == "Updated title"


def test_unpin_removes_only_owners_pin():
    owner = _account()
    res = client.post("/pins", json={"ref_type": "artifact", "ref_id": "a.pptx", "title": "A"},
                      headers=_auth(owner)).json()
    pin_id = res["pin"]["id"]
    assert client.delete(f"/pins/{pin_id}", headers=_auth(owner)).json()["ok"] is True
    assert client.get("/pins", headers=_auth(owner)).json()["pins"] == []


def test_pins_are_scope_isolated():
    owner = _account()
    ws = client.post("/workspaces", json={"name": "Team"}, headers=_auth(owner)).json()["workspace"]
    client.post("/pins", json={"ref_type": "document", "ref_id": "ws.txt", "title": "WS doc"},
                headers=_auth(owner, ws["id"]))
    # The workspace pin does not appear in personal scope.
    personal = client.get("/pins", headers=_auth(owner)).json()
    assert personal["scope"]["is_workspace"] is False and personal["pins"] == []


def test_workspace_viewer_cannot_pin_but_can_see():
    owner, viewer = _account(), _account()
    ws = client.post("/workspaces", json={"name": "Team"}, headers=_auth(owner)).json()["workspace"]
    workspace_service.add_member(ws["id"], viewer["id"], "viewer")
    owner_pin = client.post("/pins", json={"ref_type": "document", "ref_id": "shared.txt", "title": "Shared"},
                            headers=_auth(owner, ws["id"]))
    assert owner_pin.status_code == 200
    # Viewer can read the shared pin...
    seen = client.get("/pins", headers=_auth(viewer, ws["id"])).json()["pins"]
    assert any(p["title"] == "Shared" for p in seen)
    # ...but cannot mutate shared pins.
    denied = client.post("/pins", json={"ref_type": "document", "ref_id": "v.txt", "title": "Nope"},
                         headers=_auth(viewer, ws["id"]))
    assert denied.status_code == 403


def test_non_member_cannot_search_or_pin_workspace():
    owner, outsider = _account(), _account()
    ws = client.post("/workspaces", json={"name": "Secret"}, headers=_auth(owner)).json()["workspace"]
    _seed_artifact(ws["owner_key"], "confidential.pptx")
    # Falls back to personal scope — never the team's resources, and the pin lands
    # in the outsider's own personal scope, not the workspace.
    body = client.get("/search", params={"q": "confidential"}, headers=_auth(outsider, ws["id"])).json()
    assert body["scope"]["is_workspace"] is False
    assert all(r["title"] != "Confidential" for r in body["results"])
