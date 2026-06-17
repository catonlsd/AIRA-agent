# File: backend/tests/test_workspace_scope_behavior.py
"""Workspace-scoped behavior: preference precedence (personal < workspace <
current turn), isolated workspace quotas with their own limits, and scoped
document collections. Personal mode is unchanged; scope stays explicit."""

from uuid import uuid4

import pytest

import app.core.llm as llm_module
from app.accounts import account_service
from app.assistant_supervisor import AssistantSupervisor
from app.auth import ResourceScope, SCOPE_ACCOUNT, SCOPE_WORKSPACE, make_account_token
from app.context_builder import build_turn_context
from app.memory.preference_memory import preference_memory
from app.usage_limits import KIND_EXECUTION, quota_service, usage_limiter
from app.workspaces import workspace_service


def _account_and_workspace():
    acct = account_service.register(f"u_{uuid4().hex[:10]}@example.com", "password123", "U")
    ws = workspace_service.create(acct["id"], "Team")
    return acct, ws


def _workspace_scope(account_id, workspace_id, name="Team", role="owner"):
    # The account created the workspace, so it acts as owner here.
    return ResourceScope(
        kind=SCOPE_WORKSPACE, subject=workspace_id,
        account_id=account_id, workspace_id=workspace_id, label=name, role=role,
    )


# ── Preference precedence ────────────────────────────────────────────────────


def test_effective_layers_personal_then_workspace():
    acct, ws = _account_and_workspace()
    personal_owner = f"account:{acct['id']}"
    workspace_owner = ws["owner_key"]

    preference_memory.set(personal_owner, "answer_style", "code_first")   # personal-only
    preference_memory.set(personal_owner, "answer_length", "detailed")
    preference_memory.set(workspace_owner, "answer_length", "concise")     # workspace overrides

    effective = preference_memory.effective([personal_owner, workspace_owner])
    assert effective["answer_length"] == "concise"        # workspace wins where set
    assert effective["answer_style"] == "code_first"      # personal fills the gap


@pytest.mark.asyncio
async def test_workspace_default_shapes_answer_then_current_turn_overrides(monkeypatch):
    captured = {}

    def _capture(self, system, prompt, temperature=0.2):
        captured["system"] = system
        return "ok"

    monkeypatch.setattr(llm_module.LLMClient, "generate", _capture)
    acct, ws = _account_and_workspace()
    preference_memory.set(f"account:{acct['id']}", "answer_length", "detailed")  # personal
    preference_memory.set(ws["owner_key"], "answer_length", "concise")            # workspace

    supervisor = AssistantSupervisor()
    scope = _workspace_scope(acct["id"], ws["id"])
    ctx = build_turn_context("tell me about python", session_id="s", scope=scope)
    await supervisor.run_turn(ctx)

    # Acting in workspace scope -> the workspace's "concise" default shapes the
    # answer-style prompt (not the personal "detailed"). The directive still says
    # the current message overrides — current turn always wins at answer time.
    assert "concise" in captured["system"]
    assert "current message" in captured["system"]


@pytest.mark.asyncio
async def test_personal_scope_uses_personal_preferences(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        llm_module.LLMClient, "generate",
        lambda self, system, prompt, temperature=0.2: captured.setdefault("system", system) or "ok",
    )
    acct, ws = _account_and_workspace()
    preference_memory.set(f"account:{acct['id']}", "answer_length", "detailed")
    preference_memory.set(ws["owner_key"], "answer_length", "concise")

    supervisor = AssistantSupervisor()
    # Personal (account) scope -> personal preference applies, NOT the workspace's.
    scope = ResourceScope(kind=SCOPE_ACCOUNT, subject=acct["id"], account_id=acct["id"], label="Personal")
    ctx = build_turn_context("tell me about rust", session_id="s", scope=scope)
    await supervisor.run_turn(ctx)
    assert "thorough" in captured["system"] or "detailed" in captured["system"]


def test_stated_preference_in_workspace_scope_writes_workspace_default(monkeypatch):
    monkeypatch.setattr(llm_module.LLMClient, "generate", lambda self, s, p, t=0.2: "ok")
    acct, ws = _account_and_workspace()
    supervisor = AssistantSupervisor()
    scope = _workspace_scope(acct["id"], ws["id"])
    ctx = build_turn_context("From now on, keep answers concise.", session_id="s", scope=scope)
    supervisor._prime_memory(ctx)
    # The stated preference became a WORKSPACE default, not a personal one.
    assert preference_memory.get(ws["owner_key"]) == {"answer_length": "concise"}
    assert preference_memory.get(f"account:{acct['id']}") == {}


# ── Workspace quotas (isolated + independently tunable) ──────────────────────


def test_personal_and_workspace_quotas_are_isolated(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "execution_starts_per_window", 1)
    monkeypatch.setattr(settings, "workspace_execution_starts_per_window", 1)
    usage_limiter.reset()

    personal = "account:acc-1"
    workspace = "workspace:ws-1"
    # Exhaust the personal quota.
    quota_service.record(personal, KIND_EXECUTION)
    assert quota_service.check_windowed(personal, KIND_EXECUTION).allowed is False
    # The workspace quota is a separate counter — still allowed.
    assert quota_service.check_windowed(workspace, KIND_EXECUTION).allowed is True


def test_workspace_uses_its_own_limit(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "execution_starts_per_window", 1)        # personal: tight
    monkeypatch.setattr(settings, "workspace_execution_starts_per_window", 3)  # workspace: looser
    usage_limiter.reset()

    workspace = "workspace:ws-2"
    quota_service.record(workspace, KIND_EXECUTION)
    quota_service.record(workspace, KIND_EXECUTION)
    # Two recorded, workspace limit is 3 -> still allowed (personal limit of 1 ignored).
    assert quota_service.check_windowed(workspace, KIND_EXECUTION).allowed is True
    quota_service.record(workspace, KIND_EXECUTION)
    assert quota_service.check_windowed(workspace, KIND_EXECUTION).allowed is False


def test_invalid_workspace_quota_config_fails_clearly():
    from app.core.config import Settings

    with pytest.raises(Exception):
        Settings(workspace_execution_starts_per_window=0)


# ── Scoped document collections (personal vs workspace isolation) ────────────


def test_documents_are_isolated_by_scope():
    from app.rag.embedding_provider import HashingEmbeddingProvider
    from app.services.document_qa_service import DocumentQnAService
    from app.services.vector_store_service import ChromaVectorStore

    service = DocumentQnAService(
        embeddings=HashingEmbeddingProvider(),
        store=ChromaVectorStore(f"scope_{uuid4().hex[:8]}", ephemeral=True),
    )
    # Same document id space, different owners (personal account vs workspace).
    service.ingest(document_id=1, document_name="personal.pdf",
                   pages=[{"page": 1, "text": "Personal note: my private API key rotation plan."}],
                   owner="account:acc-9")
    service.ingest(document_id=2, document_name="team.pdf",
                   pages=[{"page": 1, "text": "Team note: the shared onboarding checklist for new hires."}],
                   owner="workspace:ws-9")

    # Personal retrieval only sees personal docs; workspace retrieval only its own.
    personal_hits = service.retrieve("what is the plan", k=5, owner="account:acc-9")
    assert personal_hits and all(c.document_name == "personal.pdf" for c in personal_hits)

    workspace_hits = service.retrieve("onboarding checklist", k=5, owner="workspace:ws-9")
    assert workspace_hits and all(c.document_name == "team.pdf" for c in workspace_hits)

    # A different workspace sees nothing from ws-9 (no cross-workspace leakage).
    other_ws = service.retrieve("onboarding checklist", k=5, owner="workspace:ws-OTHER")
    assert other_ws == []
