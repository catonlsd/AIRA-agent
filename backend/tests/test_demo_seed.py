"""Phase 6 — deterministic, operator-only incident-sync demo seed.

Proves the showcase data is realistic, deterministic, idempotent, namespaced (never
touches real data), and operator-gated + feature-flagged.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.accounts import account_service
from app.auth import make_account_token
import app.core.config as config_mod
from app import demo_seed
from app.incident_sync import incident_sync_service
from app.incidents import incident_service
from app.main import app
from app.middleware import reset_rate_limit

client = TestClient(app)
OP = {"X-API-Key": "service-secret"}


@pytest.fixture
def op(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "api_key", "service-secret")
    reset_rate_limit()
    yield


def _account():
    return account_service.register(f"u_{uuid4().hex[:10]}@example.com", "password123", "Alice")


def _auth():
    return {"Authorization": f"Bearer {make_account_token(_account()['id'])}"}


# ── scenario shape ────────────────────────────────────────────────────────────


def test_demo_seed_creates_deterministic_scenario():
    manifest = demo_seed.seed()
    assert manifest["counts"] == {"targets": 6, "incidents": 5, "links": 5,
                                  "check_events": 11, "reconciliation_events": 8, "sync_records": 6}
    assert manifest["demo"] is True and manifest["namespace"] == demo_seed.DEMO_HOST
    assert len(manifest["tour"]) >= 5 and all("look_at" in s and "shows" in s for s in manifest["tour"])

    metrics = incident_sync_service.incident_metrics()
    # Honest readiness variety — every state set from real evidence, not faked.
    assert metrics["readiness"]["distribution"] == {
        "ready": 2, "stale": 1, "unverified": 1, "auth_failed": 1, "disabled": 1}
    assert metrics["readiness"]["enabled"] == 5 and metrics["readiness"]["ready"] == 2
    # A populated, deterministic SLO + drift picture.
    assert metrics["slo"]["target_readiness_pct"] == 40.0          # 2 ready / 5 enabled
    assert metrics["drift"]["backlog"] == 3
    assert metrics["drift"]["by_status"] == {"drifted": 1, "missing_external": 1, "stale": 1}
    assert metrics["drift"]["oldest"] is not None
    # A live candidate alert the dashboard can show off (repeated auth failures).
    codes = {a["code"] for a in metrics["alerts"]}
    assert "repeated_auth_failures" in codes


def test_demo_seed_lights_up_attention_and_drift_recovery():
    demo_seed.seed()
    # The attention triage list reflects exactly the non-ready, non-disabled targets.
    states = sorted(t["readiness"]["state"] for t in incident_sync_service.targets_needing_attention())
    assert states == ["auth_failed", "stale", "unverified"]
    # The drifted incident offers the deterministic, deliberate recovery action.
    status = incident_sync_service.incident_sync_status("demo-inc-2", incident_state="open")
    assert status["summary"]["link_status"] == "drifted"
    assert status["summary"]["recommended_action"] == "apply_resolved"


def test_demo_seed_secrets_never_returned():
    demo_seed.seed()
    targets = incident_sync_service.list_targets()
    demo = [t for t in targets if t["name"].endswith("(demo)")]
    assert len(demo) == 6
    # Rich targets carry a secret for HMAC signing, but it is never exposed.
    assert any(t["has_secret"] for t in demo)
    assert demo_seed.DEMO_SECRET not in str(targets)


# ── idempotency + isolation (never touches real data) ─────────────────────────


def test_demo_seed_is_idempotent():
    first = demo_seed.seed()["counts"]
    second = demo_seed.seed()["counts"]
    assert first == second                                          # no accumulation
    assert len(incident_sync_service.list_targets()) == 6           # not 12


def test_demo_reset_removes_only_the_demo_namespace():
    # A REAL (non-demo) target + incident must survive a demo reset.
    real_target = incident_sync_service.create_target(name="real-prod", url="https://real.example.com/hook")
    incident_service.observe([{"classification": "stuck", "severity": "critical",
                               "job_id": "real-job", "reason": "x"}])
    real_incident = next(i for i in incident_service.list() if i["subject"] == "real-job")

    demo_seed.seed()
    assert len(incident_sync_service.list_targets()) == 7           # 6 demo + 1 real

    removed = demo_seed.reset()
    assert removed["targets"] == 6 and removed["incidents"] == 5
    # The real entities are untouched.
    survivors = incident_sync_service.list_targets()
    assert len(survivors) == 1 and survivors[0]["id"] == real_target["id"]
    assert incident_service.get(real_incident["id"]) is not None
    # And no demo entities remain.
    assert incident_sync_service.incident_metrics()["readiness"]["total"] == 1


def test_demo_status_reflects_presence():
    before = demo_seed.status()
    assert before["present"] is False and before["tour"] == []
    demo_seed.seed()
    after = demo_seed.status()
    assert after["present"] is True and after["counts"]["targets"] == 6
    assert len(after["tour"]) >= 5


# ── HTTP gating + feature flag ────────────────────────────────────────────────


def test_demo_endpoints_require_operator(op):
    seeded = client.post("/operator/demo/seed", headers=OP).json()
    assert seeded["counts"]["targets"] == 6
    assert client.get("/operator/demo/status", headers=OP).json()["present"] is True
    assert client.post("/operator/demo/reset", headers=OP).json()["removed"]["targets"] == 6
    # Operator-only: a normal account token is rejected on every demo route.
    auth = _auth()
    assert client.post("/operator/demo/seed", headers=auth).status_code in (401, 403)
    assert client.post("/operator/demo/reset", headers=auth).status_code in (401, 403)
    assert client.get("/operator/demo/status", headers=auth).status_code in (401, 403)


def test_demo_seed_can_be_disabled(op, monkeypatch):
    monkeypatch.setattr(config_mod.settings, "demo_seed_enabled", False)
    # Writes are blocked when the feature flag is off…
    assert client.post("/operator/demo/seed", headers=OP).status_code == 403
    assert client.post("/operator/demo/reset", headers=OP).status_code == 403
    # …but the read-only status still works for the operator (reports disabled).
    status = client.get("/operator/demo/status", headers=OP).json()
    assert status["enabled"] is False and status["present"] is False
