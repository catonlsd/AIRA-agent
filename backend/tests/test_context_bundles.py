# File: backend/tests/test_context_bundles.py
"""Multi-item attached context + durable handoff bundles.

Several documents/artifacts/runs can be attached to the next turn (deduped,
honest per-item semantics), removed one at a time or cleared, and saved as a
scope-owned bundle of references (never payloads) that reloads by re-resolving
access in the current scope. Personal and workspace stay isolated; non-members
can't load workspace bundles; mutating bundles needs edit."""

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.accounts import account_service
from app.activity import RUN_FAILED, activity_service
from app.auth import make_account_token, owner_token_for
from app.bundles import bundle_service
from app.chat_context import chat_context_service
from app.core.config import settings
from app.db.database import ensure_runtime_columns
from app.main import app
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


# ── Multi-item attached context (service-level) ──────────────────────────────


def test_attach_multiple_items_of_different_types():
    owner, session = f"account:{uuid4().hex}", "s1"
    _seed_artifact(owner, "roadmap.pptx")
    activity_service.record(owner, RUN_FAILED, "Build run didn't finish", status="failed")
    chat_context_service.attach(owner, session, "artifact", "roadmap.pptx")
    chat_context_service.attach(owner, session, "run", "artifact:roadmap.pptx")
    chat_context_service.attach(owner, session, "run", "failed:0")
    items = chat_context_service.items(owner, session)
    assert len(items) == 3
    # Honest, distinct semantics survive — never flattened to a generic attachment.
    actions = {i["ref_type"]: i["action"] for i in items}
    assert actions["artifact"] == "revise"
    roles = {i["role"] for i in items}
    assert {"artifact to revise", "prior run"} <= roles


def test_duplicate_attachment_is_deduped():
    owner, session = f"account:{uuid4().hex}", "s1"
    _seed_artifact(owner, "deck.pptx")
    chat_context_service.attach(owner, session, "artifact", "deck.pptx")
    chat_context_service.attach(owner, session, "artifact", "deck.pptx")
    assert len(chat_context_service.items(owner, session)) == 1


def test_remove_one_and_clear_all():
    owner, session = f"account:{uuid4().hex}", "s1"
    _seed_artifact(owner, "a.pptx")
    _seed_artifact(owner, "b.pptx")
    chat_context_service.attach(owner, session, "artifact", "a.pptx")
    chat_context_service.attach(owner, session, "artifact", "b.pptx")
    assert chat_context_service.remove(owner, session, "artifact", "a.pptx") is True
    remaining = chat_context_service.items(owner, session)
    assert [i["ref_id"] for i in remaining] == ["b.pptx"]
    chat_context_service.clear(owner, session)
    assert chat_context_service.items(owner, session) == []


def test_inaccessible_item_is_not_attached_among_many():
    owner, other, session = f"account:{uuid4().hex}", f"workspace:{uuid4().hex}", "s1"
    _seed_artifact(owner, "mine.pptx")
    _seed_artifact(other, "theirs.pptx")
    result = chat_context_service.attach_many(
        owner, session,
        [{"ref_type": "artifact", "ref_id": "mine.pptx"}, {"ref_type": "artifact", "ref_id": "theirs.pptx"}],
    )
    assert result["attached"] == 1 and result["skipped"] == 1
    assert [i["ref_id"] for i in result["items"]] == ["mine.pptx"]


def test_attached_items_payload_is_clean():
    owner, session = f"account:{uuid4().hex}", "s1"
    _seed_artifact(owner, "secret.pptx")
    chat_context_service.attach(owner, session, "artifact", "secret.pptx")
    for item in chat_context_service.items(owner, session):
        for banned in ("owner", "owner_key", "path", "token", "spec", "delivery", "payload", "filename"):
            assert banned not in item


# ── Multi-item HTTP ──────────────────────────────────────────────────────────


def test_attach_items_endpoint_and_get_list():
    owner = _account()
    _seed_artifact(f"account:{owner['id']}", "x.pptx")
    _seed_artifact(f"account:{owner['id']}", "y.pptx")
    res = client.post("/chat/context/items", json={"session_id": "s", "items": [
        {"ref_type": "artifact", "ref_id": "x.pptx"},
        {"ref_type": "artifact", "ref_id": "y.pptx"},
    ]}, headers=_auth(owner)).json()
    assert res["attached"] == 2
    got = client.get("/chat/context", params={"session_id": "s"}, headers=_auth(owner)).json()
    assert len(got["items"]) == 2 and got["prompt"]  # a revise starter is offered


def test_remove_one_item_over_http():
    owner = _account()
    _seed_artifact(f"account:{owner['id']}", "keep.pptx")
    _seed_artifact(f"account:{owner['id']}", "drop.pptx")
    client.post("/chat/context", json={"ref_type": "artifact", "ref_id": "keep.pptx", "session_id": "s"}, headers=_auth(owner))
    client.post("/chat/context", json={"ref_type": "artifact", "ref_id": "drop.pptx", "session_id": "s"}, headers=_auth(owner))
    res = client.delete("/chat/context/item", params={"ref_type": "artifact", "ref_id": "drop.pptx", "session_id": "s"},
                        headers=_auth(owner)).json()
    assert res["ok"] is True and [i["ref_id"] for i in res["items"]] == ["keep.pptx"]


# ── Bundles ──────────────────────────────────────────────────────────────────


def test_create_list_load_and_delete_bundle():
    owner = _account()
    _seed_artifact(f"account:{owner['id']}", "strategy.pptx")
    _seed_artifact(f"account:{owner['id']}", "roadmap.pptx")
    # Attach two items, then save them as a bundle.
    client.post("/chat/context/items", json={"session_id": "s", "items": [
        {"ref_type": "artifact", "ref_id": "strategy.pptx"},
        {"ref_type": "artifact", "ref_id": "roadmap.pptx"},
    ]}, headers=_auth(owner))
    bundle = client.post("/bundles", json={"name": "Q3 planning pack", "session_id": "s"}, headers=_auth(owner)).json()["bundle"]
    assert bundle["name"] == "Q3 planning pack" and bundle["count"] == 2

    listed = client.get("/bundles", headers=_auth(owner)).json()["bundles"]
    assert any(b["id"] == bundle["id"] for b in listed)

    # Load it into a fresh session — references re-resolve into attached context.
    loaded = client.post(f"/bundles/{bundle['id']}/load", json={"session_id": "fresh"}, headers=_auth(owner)).json()
    assert loaded["attached"] == 2 and len(loaded["items"]) == 2

    assert client.delete(f"/bundles/{bundle['id']}", headers=_auth(owner)).json()["ok"] is True
    assert client.get("/bundles", headers=_auth(owner)).json()["bundles"] == []


def test_bundle_stores_references_not_payloads():
    owner = f"account:{uuid4().hex}"
    bundle = bundle_service.create(owner, "Pack", [
        {"ref_type": "artifact", "ref_id": "a.pptx", "title": "A", "prompt": "secret prompt", "download_url": "/x"},
    ])
    refs = bundle_service.item_refs(owner, bundle["id"])
    assert refs == [{"ref_type": "artifact", "ref_id": "a.pptx", "title": "A"}]
    # The clean listing never carries prompts/urls/payloads.
    for item in bundle["items"]:
        assert set(item) == {"ref_type", "title"}


def test_creating_empty_bundle_is_rejected():
    owner = _account()
    res = client.post("/bundles", json={"name": "Empty", "session_id": "nope"}, headers=_auth(owner))
    assert res.status_code == 400


def test_bundles_are_scope_isolated_and_workspace_aware():
    owner, viewer, outsider = _account(), _account(), _account()
    ws = client.post("/workspaces", json={"name": "Team"}, headers=_auth(owner)).json()["workspace"]
    workspace_service.add_member(ws["id"], viewer["id"], "viewer")
    _seed_artifact(ws["owner_key"], "shared.pptx")
    client.post("/chat/context", json={"ref_type": "artifact", "ref_id": "shared.pptx", "session_id": "s"},
                headers=_auth(owner, ws["id"]))
    bundle = client.post("/bundles", json={"name": "Team pack", "session_id": "s"},
                         headers=_auth(owner, ws["id"])).json()["bundle"]

    # A member sees the shared bundle...
    member_view = client.get("/bundles", headers=_auth(viewer, ws["id"])).json()["bundles"]
    assert any(b["id"] == bundle["id"] for b in member_view)
    # ...and a non-member never does (falls back to personal scope).
    out_view = client.get("/bundles", headers=_auth(outsider, ws["id"])).json()
    assert out_view["scope"]["is_workspace"] is False
    assert all(b["id"] != bundle["id"] for b in out_view["bundles"])
    # The workspace bundle isn't loadable by an outsider — 404, no leak.
    denied = client.post(f"/bundles/{bundle['id']}/load", json={"session_id": "s"}, headers=_auth(outsider, ws["id"]))
    assert denied.status_code == 404


def test_workspace_viewer_cannot_create_bundle():
    owner, viewer = _account(), _account()
    ws = client.post("/workspaces", json={"name": "Team"}, headers=_auth(owner)).json()["workspace"]
    workspace_service.add_member(ws["id"], viewer["id"], "viewer")
    _seed_artifact(ws["owner_key"], "doc.pptx")
    client.post("/chat/context", json={"ref_type": "artifact", "ref_id": "doc.pptx", "session_id": "s"},
                headers=_auth(viewer, ws["id"]))
    # Viewer can attach for their own turn, but can't save a shared bundle.
    denied = client.post("/bundles", json={"name": "Nope", "session_id": "s"}, headers=_auth(viewer, ws["id"]))
    assert denied.status_code == 403
