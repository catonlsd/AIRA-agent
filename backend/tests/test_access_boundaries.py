# File: backend/tests/test_access_boundaries.py
"""Auth / ownership / access boundaries: principal resolution, guided-flow
ownership, artifact download protection, and document retrieval scoping."""

import pytest
from fastapi.testclient import TestClient

from app.auth import Principal, owner_token_for, resolve_principal
from app.clarification import plan_store
from app.guided_flow_store import guided_flow_store


# ── Principal / identity abstraction ─────────────────────────────────────────


def test_session_principal_owns_a_stable_scope():
    p = resolve_principal(session_id="abc")
    assert p.kind == "session"
    assert p.authenticated is False
    assert p.owner_key == "session:abc"
    # Owner token is opaque and stable.
    assert p.owner_token == owner_token_for("session:abc")
    assert p.owner_token != "session:abc"


def test_api_key_principal_when_configured(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "api_key", "secret-key")
    p = resolve_principal(api_key="secret-key", session_id="abc")
    assert p.kind == "api_key"
    assert p.authenticated is True
    # The API-key principal owns a different scope than the bare session.
    assert p.owner_key != "session:abc"


def test_wrong_api_key_does_not_authenticate(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "api_key", "secret-key")
    p = resolve_principal(api_key="WRONG", session_id="abc")
    assert p.authenticated is False
    assert p.kind == "session"  # falls back to the session, never the key


def test_distinct_owners_have_distinct_tokens():
    assert owner_token_for("session:a") != owner_token_for("session:b")


# ── Guided-flow ownership ────────────────────────────────────────────────────


def test_guided_flow_state_is_owner_scoped():
    guided_flow_store.set("owner-A", "plan", {"goal": "A's plan"})
    # Another owner sees nothing and cannot consume it.
    assert guided_flow_store.peek("owner-B", "plan") is None
    assert guided_flow_store.consume("owner-B", "plan") is None
    # The real owner can.
    assert guided_flow_store.peek("owner-A", "plan") == {"goal": "A's plan"}
    assert guided_flow_store.consume("owner-A", "plan") == {"goal": "A's plan"}


@pytest.mark.asyncio
async def test_one_owner_cannot_approve_anothers_plan():
    from app.assistant_supervisor import AssistantSupervisor
    from app.context_builder import build_turn_context
    from app.supervisor_reasoning import reason_about_turn

    supervisor = AssistantSupervisor()
    goal = "Build me a RAG system"

    # Owner A drives to a pending clarification (owner = session id by default).
    ctx_a = build_turn_context(goal, session_id="user-A", run_id="a1")
    reasoning = reason_about_turn(goal)
    await supervisor._dispatch_non_chat(goal, reasoning.classification, ctx_a, reasoning=reasoning)
    assert plan_store.get("user-A") is None  # it's a clarification, not a plan yet
    from app.clarification import clarification_store

    assert clarification_store.get("user-A") is not None

    # Owner B answering with A's selection codes resolves nothing in B's scope.
    reply = "1A, 2A, 3A"
    ctx_b = build_turn_context(reply, session_id="user-B", run_id="b1")
    result = await supervisor._dispatch(reply, ctx_b)
    # B has no pending flow -> routed normally, never resumes A's task.
    assert result["decision"] != "plan_ready"
    assert clarification_store.get("user-A") is not None  # A's flow untouched


# ── Artifact download protection ─────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "artifacts_dir", str(tmp_path / "artifacts"))
    return TestClient(__import__("app.main", fromlist=["app"]).app), tmp_path / "artifacts"


def _write_artifact(root, owner_token, filename, content=b"PK\x03\x04 fake"):
    from pathlib import Path

    d = Path(root) / owner_token
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_bytes(content)


def test_owner_can_download_own_artifact(client):
    c, root = client
    token = owner_token_for("session:me")
    _write_artifact(root, token, "report.pptx")
    resp = c.get(f"/artifacts/{token}/report.pptx")
    assert resp.status_code == 200


def test_guessed_filename_without_owner_token_is_blocked(client):
    c, root = client
    token = owner_token_for("session:victim")
    _write_artifact(root, token, "secret.pptx")
    # Knowing the filename but not the owner token must not grant access.
    assert c.get("/artifacts/wrong-owner/secret.pptx").status_code == 404
    assert c.get("/artifacts/secret.pptx").status_code == 404  # legacy unscoped path gone


def test_path_traversal_is_blocked(client):
    c, _ = client
    assert c.get("/artifacts/..%2f..%2fmain.py").status_code in (404, 400)
    token = owner_token_for("session:me")
    assert c.get(f"/artifacts/{token}/..%2f..%2fsecret.pptx").status_code in (404, 400)


def test_authenticated_caller_cannot_reach_another_owner(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "api_key", "k")
    c, root = client
    other = owner_token_for("session:other")
    _write_artifact(root, other, "theirs.pptx")
    # Authenticated as a different principal -> 404 for another owner's artifact.
    resp = c.get(f"/artifacts/{other}/theirs.pptx", headers={"X-API-Key": "k"})
    assert resp.status_code == 404


# ── Document retrieval scoping ───────────────────────────────────────────────


def test_document_retrieval_is_owner_isolated():
    from uuid import uuid4

    from app.rag.embedding_provider import HashingEmbeddingProvider
    from app.services.document_qa_service import DocumentQnAService
    from app.services.vector_store_service import ChromaVectorStore

    store = ChromaVectorStore(f"acl_docs_{uuid4().hex[:8]}", ephemeral=True)
    svc = DocumentQnAService(store=store, embeddings=HashingEmbeddingProvider())

    svc.ingest(document_id=1, document_name="alice.pdf",
               pages=[{"page": 1, "text": "Alice's secret revenue is 40 million."}], owner="alice")
    svc.ingest(document_id=2, document_name="bob.pdf",
               pages=[{"page": 1, "text": "Bob's secret budget is 9 dollars."}], owner="bob")

    alice_hits = svc.retrieve("secret", k=5, owner="alice")
    assert alice_hits and all(h.document_name == "alice.pdf" for h in alice_hits)
    bob_hits = svc.retrieve("secret", k=5, owner="bob")
    assert bob_hits and all(h.document_name == "bob.pdf" for h in bob_hits)
    # No cross-owner leakage.
    assert all("Bob" not in h.text for h in alice_hits)


@pytest.mark.asyncio
async def test_document_answer_scopes_to_caller_owner(monkeypatch):
    from app.assistant_supervisor import AssistantSupervisor
    from app.context_builder import build_turn_context

    supervisor = AssistantSupervisor()
    captured = {}

    class _Docs:
        def answer(self, query, history=None, owner=None, **kwargs):
            captured["owner"] = owner
            return {"mode": "document_qa", "message": "x", "final_answer": "x",
                    "sources": [], "meta": {"has_evidence": True}, "status": "completed",
                    "decision": "document_qa_completed", "artifacts": [], "approval_summary": None}

    supervisor._documents = _Docs()
    from app.supervisor_reasoning import reason_about_turn

    goal = "what does the uploaded document say?"
    ctx = build_turn_context(goal, session_id="user-X", run_id="x", uploaded_file_names=["d.pdf"])
    reasoning = reason_about_turn(goal, has_uploaded_files=True, uploaded_file_names=["d.pdf"])
    await supervisor._dispatch_non_chat(goal, reasoning.classification, ctx, reasoning=reasoning)
    assert captured["owner"] == "user-X"  # scoped to the caller, not global
