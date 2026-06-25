# File: backend/tests/test_operator_incidents.py
"""Operator incident workflow — acknowledge, silence (bounded), honest recovery.

A recurring operational condition gets a durable identity (the alert signal). An
operator can acknowledge it (being worked) or silence it for a BOUNDED window
(mutes alert routing for that signal — distinct from suppression/cooldown). A
silenced incident still exists; it auto-reopens on expiry; a cleared condition
recovers honestly. Operator-only, clean payloads, no leak into the user product."""

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.accounts import account_service
from app.auth import make_account_token
import app.core.config as config_mod
from app.db.database import SessionLocal, ensure_runtime_columns
from app.db.models import OperatorIncident
from app.execution_queue import execution_queue
from app.incidents import incident_service, signal_of
from app.job_handlers import register_default_handlers
from app.main import app
from app.middleware import reset_rate_limit
from app.webhooks import delivery_service

ensure_runtime_columns()
register_default_handlers()
client = TestClient(app)
OP = {"X-API-Key": "service-secret"}


@pytest.fixture
def op(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "api_key", "service-secret")
    reset_rate_limit()
    yield


def _account():
    return account_service.register(f"u_{uuid4().hex[:10]}@example.com", "password123", "Alice")


def _alert(classification="stuck", severity="critical", job_id=None):
    return {"classification": classification, "severity": severity, "job_id": job_id or "J1", "reason": "x"}


# ── Open / acknowledge ───────────────────────────────────────────────────────


def test_incident_opens_for_a_condition_then_acknowledged():
    incident_service.observe([_alert(job_id="open-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "open-1")
    assert inc["state"] == "open" and inc["classification"] == "stuck"
    acked = incident_service.acknowledge(inc["id"])
    assert acked["state"] == "acknowledged" and acked["acknowledged"] is True


def test_repeated_condition_bumps_occurrences_not_duplicates():
    a = _alert(job_id="rep-1")
    for _ in range(3):
        incident_service.observe([a])
    matching = [i for i in incident_service.list() if i["subject"] == "rep-1"]
    assert len(matching) == 1 and matching[0]["occurrences"] == 3


# ── Silence: bounded + gates routing + distinct from suppression ─────────────


def test_silence_is_bounded_and_mutes_routing(monkeypatch):
    # A destination that would normally receive the alert.
    delivery_service.create_destination(name="d", url="https://h.example.com/x",
                                        subscription="alerts", min_severity="warning")
    alert = _alert(job_id="sil-1")
    incident_service.observe([alert])
    inc = next(i for i in incident_service.list() if i["subject"] == "sil-1")
    # Silence beyond the cap is clamped, never infinite.
    monkeypatch.setattr(config_mod.settings, "incident_max_silence_seconds", 600)
    sil = incident_service.silence(inc["id"], seconds=999999)
    assert sil["state"] == "silenced" and sil["silenced_until"] is not None
    # Routing now SKIPS the silenced signal (counted as silenced, not routed).
    result = delivery_service.route_alerts_detailed([alert])
    assert result["silenced"] >= 1 and result["routed"] == 0
    # ...but the incident still EXISTS (silence is not a black hole).
    assert any(i["id"] == inc["id"] for i in incident_service.list())


def test_silence_expiry_reopens_honestly():
    alert = _alert(job_id="exp-1")
    incident_service.observe([alert])
    inc = next(i for i in incident_service.list() if i["subject"] == "exp-1")
    incident_service.silence(inc["id"], seconds=300)
    # Force the silence window into the past.
    with SessionLocal() as s:
        from app.incidents import _now
        s.get(OperatorIncident, inc["id"]).silenced_until = _now() - timedelta(seconds=10)
        s.commit()
    # Expired silence no longer mutes routing…
    assert signal_of(alert) not in incident_service.silenced_signals()
    # …and observing the recurring condition reopens it as a fresh episode.
    incident_service.observe([alert])
    reopened = incident_service.get(inc["id"])
    assert reopened["state"] == "open" and reopened["silenced_until"] is None


def test_unsilence_returns_to_open_or_acknowledged():
    incident_service.observe([_alert(job_id="uns-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "uns-1")
    incident_service.acknowledge(inc["id"])
    incident_service.silence(inc["id"], seconds=300)
    back = incident_service.unsilence(inc["id"])
    assert back["state"] == "acknowledged"  # ack survives a silence/unsilence


# ── Honest recovery ──────────────────────────────────────────────────────────


def test_condition_clearing_recovers_the_incident():
    alert = _alert(job_id="rec-1")
    incident_service.observe([alert])
    inc = next(i for i in incident_service.list() if i["subject"] == "rec-1")
    incident_service.acknowledge(inc["id"])
    # Next sweep: the signal is no longer active -> recovered.
    incident_service.recover_stale([])  # nothing active now
    recovered = incident_service.get(inc["id"])
    assert recovered["state"] == "recovered" and recovered["recovered_at"]


def test_recovered_condition_recurs_as_fresh_episode():
    alert = _alert(job_id="reo-1")
    incident_service.observe([alert]); inc = next(i for i in incident_service.list() if i["subject"] == "reo-1")
    incident_service.recover_stale([])  # recovered
    incident_service.observe([alert])   # it's back
    again = incident_service.get(inc["id"])
    assert again["state"] == "open" and again["recovered_at"] is None


# ── Distinctness: silence != suppression != cooldown ─────────────────────────


def test_silence_is_independent_of_delivery_suppression(monkeypatch):
    # Suppression is per-(destination, signal, window); silence is per-signal,
    # operator-driven. A non-silenced signal still routes (subject to suppression).
    monkeypatch.setattr(config_mod.settings, "webhook_suppress_seconds", 0)
    delivery_service.create_destination(name="d2", url="https://h.example.com/y",
                                        subscription="alerts", min_severity="warning")
    alert = _alert(job_id="dist-1")
    incident_service.observe([alert])
    assert delivery_service.route_alerts_detailed([alert])["routed"] >= 1  # not silenced -> routes


# ── HTTP gating + clean payload + separation ─────────────────────────────────


def test_incident_endpoints_require_operator(op):
    assert client.get("/operator/incidents", headers=OP).status_code == 200
    acct = _account()
    auth = {"Authorization": f"Bearer {make_account_token(acct['id'])}"}
    assert client.get("/operator/incidents", headers=auth).status_code in (401, 403)
    assert client.post("/operator/incidents/none/ack", headers=auth).status_code in (401, 403)
    assert client.post("/operator/incidents/none/ack", headers=OP).status_code == 404


def test_incident_actions_over_http(op):
    incident_service.observe([_alert(job_id="http-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "http-1")
    acked = client.post(f"/operator/incidents/{inc['id']}/ack", headers=OP).json()["incident"]
    assert acked["state"] == "acknowledged"
    sil = client.post(f"/operator/incidents/{inc['id']}/silence", headers=OP, json={"seconds": 60}).json()["incident"]
    assert sil["state"] == "silenced" and sil["silenced_until"]
    noted = client.patch(f"/operator/incidents/{inc['id']}", headers=OP, json={"note": "watching"}).json()["incident"]
    assert noted["note"] == "watching"
    # Payload is curated — no raw internals.
    assert "payload_json" not in str(noted) and "secret" not in str(noted)


def test_invalid_silence_config_rejected():
    from app.core.config import Settings
    with pytest.raises(ValueError):
        Settings(incident_max_silence_seconds=0)


def test_no_incident_fields_leak_into_user_routes():
    owner = _account()
    job = execution_queue.enqueue(f"account:{owner['id']}", "noop", {}, title="T")
    auth = {"Authorization": f"Bearer {make_account_token(owner['id'])}"}
    user_job = client.get(f"/jobs/{job['id']}", headers=auth).json()["job"]
    for operator_only in ("state", "silenced_until", "acknowledged", "signal", "occurrences", "assignee"):
        assert operator_only not in user_job
    # And no user-facing incidents route exists.
    assert client.get("/incidents").status_code == 404


# ── Collaboration (G-4): assignment, notes & action trail ────────────────────


def test_assign_unassign_and_reassign_are_durable():
    incident_service.observe([_alert(job_id="asg-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "asg-1")
    assert inc["assignee"] is None
    owned = incident_service.assign(inc["id"], "  alice  ", actor="alice")
    assert owned["assignee"] == "alice" and owned["assigned_at"]
    re = incident_service.assign(inc["id"], "bob", actor="bob")
    assert re["assignee"] == "bob"
    free = incident_service.unassign(inc["id"], actor="bob")
    assert free["assignee"] is None and free["assigned_at"] is None
    # The trail records the ownership lifecycle distinctly.
    actions = [e["action"] for e in incident_service.history(inc["id"])]
    assert actions == ["opened", "assigned", "reassigned", "unassigned"]


def test_assignment_survives_reopen_after_recovery():
    alert = _alert(job_id="asg-keep")
    incident_service.observe([alert])
    inc = next(i for i in incident_service.list() if i["subject"] == "asg-keep")
    incident_service.assign(inc["id"], "carol")
    incident_service.recover_stale([])          # recovers
    incident_service.observe([alert])           # recurs -> reopened
    again = incident_service.get(inc["id"])
    assert again["state"] == "open" and again["assignee"] == "carol"  # owner still owns it


def test_history_trail_is_curated_and_ordered():
    incident_service.observe([_alert(job_id="hist-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "hist-1")
    incident_service.acknowledge(inc["id"], actor="alice")
    incident_service.assign(inc["id"], "alice", actor="alice")
    incident_service.set_note(inc["id"], "rebooting worker", actor="alice")
    incident_service.silence(inc["id"], seconds=60, actor="alice")
    incident_service.unsilence(inc["id"], actor="bob")
    trail = incident_service.history(inc["id"])
    assert [e["action"] for e in trail] == [
        "opened", "acknowledged", "assigned", "note_updated", "silenced", "unsilenced",
    ]
    note_evt = next(e for e in trail if e["action"] == "note_updated")
    assert note_evt["actor"] == "alice" and note_evt["detail"] == "rebooting worker"
    # Curated: no raw internals, bounded fields only.
    assert all(set(e) == {"action", "actor", "detail", "state", "at"} for e in trail)


def test_collab_actions_over_http(op):
    incident_service.observe([_alert(job_id="collab-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "collab-1")
    hdr = {**OP, "X-Operator-Name": "oncall-jordan"}
    owned = client.post(f"/operator/incidents/{inc['id']}/assign", headers=hdr, json={"assignee": "jordan"}).json()["incident"]
    assert owned["assignee"] == "jordan"
    history = client.get(f"/operator/incidents/{inc['id']}/history", headers=OP).json()["history"]
    assign_evt = next(e for e in history if e["action"] == "assigned")
    assert assign_evt["actor"] == "oncall-jordan"  # declared operator recorded as actor
    freed = client.post(f"/operator/incidents/{inc['id']}/unassign", headers=OP).json()["incident"]
    assert freed["assignee"] is None
    # Empty assignee is rejected by validation (422), not a silent no-op.
    assert client.post(f"/operator/incidents/{inc['id']}/assign", headers=OP, json={"assignee": ""}).status_code == 422


def test_collab_endpoints_require_operator(op):
    incident_service.observe([_alert(job_id="collab-gate")])
    inc = next(i for i in incident_service.list() if i["subject"] == "collab-gate")
    acct = _account()
    auth = {"Authorization": f"Bearer {make_account_token(acct['id'])}"}
    assert client.post(f"/operator/incidents/{inc['id']}/assign", headers=auth, json={"assignee": "x"}).status_code in (401, 403)
    assert client.post(f"/operator/incidents/{inc['id']}/unassign", headers=auth).status_code in (401, 403)
    assert client.get(f"/operator/incidents/{inc['id']}/history", headers=auth).status_code in (401, 403)
    # Missing incident -> 404 for operator.
    assert client.get("/operator/incidents/nope/history", headers=OP).status_code == 404
