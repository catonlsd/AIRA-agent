# File: backend/tests/test_usage_limits.py
"""Per-principal usage quotas + execution-safety boundaries: windowed rate
limits, pending-flow caps, honest limit-hit behaviour, principal-aware request
rate limiting, and config validation."""

from uuid import uuid4

import pytest

from app.assistant_supervisor import AssistantSupervisor
from app.context_builder import build_turn_context
from app.guided_flow_store import guided_flow_store
from app.supervisor_reasoning import reason_about_turn
from app.usage_limits import (
    KIND_ARTIFACT,
    KIND_EXECUTION,
    KIND_STARTUP,
    QuotaService,
    UsageLimiter,
    quota_service,
    usage_limiter,
)


# ── Windowed limiter primitive ───────────────────────────────────────────────


def test_limiter_counts_within_window():
    usage_limiter.reset()
    assert usage_limiter.count_in_window("o1", "k", 3600) == 0
    usage_limiter.record("o1", "k")
    usage_limiter.record("o1", "k")
    assert usage_limiter.count_in_window("o1", "k", 3600) == 2
    # A different owner is unaffected.
    assert usage_limiter.count_in_window("o2", "k", 3600) == 0


def test_limiter_check_respects_limit():
    usage_limiter.reset()
    assert usage_limiter.check("o", "k", limit=2, window_seconds=3600) is True
    usage_limiter.record("o", "k")
    usage_limiter.record("o", "k")
    assert usage_limiter.check("o", "k", limit=2, window_seconds=3600) is False


def test_quota_service_blocks_then_logs(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "execution_starts_per_window", 1)
    usage_limiter.reset()
    assert quota_service.check_windowed("o", KIND_EXECUTION).allowed is True
    quota_service.record("o", KIND_EXECUTION)
    decision = quota_service.check_windowed("o", KIND_EXECUTION)
    assert decision.allowed is False
    assert "rate-limited" in decision.message.lower()


def test_quotas_disabled_allows_everything(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "quotas_enabled", False)
    monkeypatch.setattr(settings, "execution_starts_per_window", 1)
    usage_limiter.reset()
    quota_service.record("o", KIND_EXECUTION)
    quota_service.record("o", KIND_EXECUTION)
    assert quota_service.check_windowed("o", KIND_EXECUTION).allowed is True


# ── Pending-flow cap ─────────────────────────────────────────────────────────


def test_pending_flow_cap(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "max_pending_flows_per_owner", 1)
    guided_flow_store.clear_all()
    guided_flow_store.set("owner", "plan", {"x": 1})
    decision = quota_service.check_pending_flows("owner")
    assert decision.allowed is False
    assert "pending approval flows" in decision.message
    # A different owner is unaffected.
    assert quota_service.check_pending_flows("other").allowed is True


# ── Supervisor enforcement (honest, state-preserving) ────────────────────────


@pytest.mark.asyncio
async def test_too_many_pending_flows_blocks_new_clarification(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "max_pending_flows_per_owner", 1)
    guided_flow_store.clear_all()
    # Pre-load one pending flow for this owner.
    guided_flow_store.set("user", "artifact", {"x": 1})

    supervisor = AssistantSupervisor()
    goal = "Build me a RAG system"
    ctx = build_turn_context(goal, session_id="user", run_id="r")
    reasoning = reason_about_turn(goal)
    result = await supervisor._dispatch_non_chat(goal, reasoning.classification, ctx, reasoning=reasoning)

    assert result["meta"].get("rate_limited") is True
    assert "pending approval flows" in result["message"]
    # The pre-existing flow is untouched (state not corrupted).
    assert guided_flow_store.peek("user", "artifact") == {"x": 1}


@pytest.mark.asyncio
async def test_execution_start_quota_blocks_without_consuming_plan(monkeypatch, tmp_path):
    from app.core.config import settings
    from tools.filesystem.file_tool import FileTool

    monkeypatch.setattr(FileTool, "_workspace_root", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(settings, "execution_starts_per_window", 1)

    import app.assistant_supervisor as sup_module

    def _gen(self, system, prompt, temperature=0.2):
        if "JSON array" in system or "JSON array" in prompt:
            return '[{"path": "app/main.py", "purpose": "entry"}]'
        return "print('ok')\n"

    monkeypatch.setattr(sup_module.LLMClient, "generate", _gen)
    usage_limiter.reset()
    guided_flow_store.clear_all()

    supervisor = AssistantSupervisor()
    session = "quota-exec"
    goal = "Build me a RAG system"
    reply = (
        "Clarification response:\n"
        f"Original request: {goal}\n"
        "Stack: Next.js + FastAPI + FAISS\n"
        "Tools: Hybrid search + citations\n"
        "Output format: Backend implementation"
    )

    # Use up the single execution-start allowance.
    quota_service.record(session, KIND_EXECUTION)

    # Drive to a pending plan.
    ctx = build_turn_context(goal, session_id=session, run_id="q1")
    reasoning = reason_about_turn(goal)
    await supervisor._dispatch_non_chat(goal, reasoning.classification, ctx, reasoning=reasoning)
    ctx2 = build_turn_context(reply, session_id=session, run_id="q2")
    await supervisor._dispatch(reply, ctx2)
    from app.clarification import plan_store

    assert plan_store.get(session) is not None  # plan is ready

    # Approve -> quota blocks; the plan stays pending (NOT consumed/run).
    ctx3 = build_turn_context("approve plan", session_id=session, run_id="q3")
    blocked = await supervisor._dispatch("approve plan", ctx3)
    assert blocked["decision"] == "rate_limited"
    assert blocked["meta"]["limit_kind"] == KIND_EXECUTION
    assert plan_store.get(session) is not None  # preserved for retry


@pytest.mark.asyncio
async def test_artifact_generation_quota_enforced(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "artifact_generations_per_window", 1)
    monkeypatch.setattr(settings, "max_pending_flows_per_owner", 100)
    monkeypatch.setattr(
        __import__("app.assistant_supervisor", fromlist=["LLMClient"]).LLMClient,
        "generate",
        lambda self, system, prompt, temperature=0.2: "",
    )
    usage_limiter.reset()
    guided_flow_store.clear_all()

    supervisor = AssistantSupervisor()
    session = "quota-artifact"
    quota_service.record(session, KIND_ARTIFACT)  # exhaust the allowance

    ctx = build_turn_context("Make me a PPT on energy", session_id=session, run_id="p1")
    await supervisor._dispatch("Make me a PPT on energy", ctx)  # -> plan_ready
    ctx2 = build_turn_context("approve", session_id=session, run_id="p2")
    blocked = await supervisor._dispatch("approve", ctx2)
    assert blocked["decision"] == "rate_limited"
    assert blocked["meta"]["limit_kind"] == KIND_ARTIFACT
    from app.artifacts.service import artifact_store

    assert artifact_store.get(session) is not None  # preserved for retry


# ── Principal-aware request rate limiting (middleware) ───────────────────────


def test_request_rate_limit_is_principal_aware(monkeypatch):
    from app.accounts import account_service
    from app.auth import make_account_token
    from app.core.config import settings
    from app.middleware import reset_rate_limit

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_per_minute", 2)
    reset_rate_limit()

    from fastapi.testclient import TestClient

    client = TestClient(__import__("app.main", fromlist=["app"]).app)
    account = account_service.register(
        f"rate_{uuid4().hex[:10]}@example.com", "password123", "Rate Test"
    )
    headers = {"Authorization": f"Bearer {make_account_token(account['id'])}"}
    # Two allowed, third blocked for this principal.
    assert client.get("/aira-x/overview", headers=headers).status_code in (200, 500)
    assert client.get("/aira-x/overview", headers=headers).status_code in (200, 500)
    assert client.get("/aira-x/overview", headers=headers).status_code == 429


# ── Config validation ────────────────────────────────────────────────────────


def test_invalid_quota_config_fails_clearly():
    from app.core.config import Settings

    with pytest.raises(Exception):
        Settings(max_pending_flows_per_owner=0)
    with pytest.raises(Exception):
        Settings(execution_starts_per_window=-5)


def test_sane_quota_config_loads():
    from app.core.config import Settings

    s = Settings(max_pending_flows_per_owner=3, execution_starts_per_window=10)
    assert s.max_pending_flows_per_owner == 3
    assert s.execution_starts_per_window == 10


def test_separate_limiter_instances_share_durable_state():
    usage_limiter.reset()
    UsageLimiter().record("shared-owner", "k")
    # A different instance == different process; the count is read from the DB.
    assert UsageLimiter().count_in_window("shared-owner", "k", 3600) == 1
