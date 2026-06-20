# File: backend/tests/test_incident_sync.py
"""External incident sync — operator-only OUTBOUND export of incident transitions.

An operator configures a sync target (secret stored, never returned). Real incident
transitions (opened / acknowledged / assigned / recovered / …) are mirrored to every
enabled target as a durable, curated `IncidentSyncRecord` correlated to the source
incident. A failed send is honest (terminal `failed` after the bounded attempt cap)
and operator-redrivable. Strictly operator-gated; secrets and raw internals never
leak; the user product gains nothing."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.accounts import account_service
from app.auth import make_account_token
import app.core.config as config_mod
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


@pytest.fixture
def capture_send(monkeypatch):
    """Make the injectable transport succeed and record outbound payloads. Returns a
    stable external ref + url so linkage is exercised."""
    import json as _json
    sent: list[dict] = []

    def _ok(self, url, body_json, secret, adapter=None):
        sent.append({"url": url, "body": _json.loads(body_json), "secret": secret,
                     "adapter": getattr(adapter, "kind", None)})
        return (True, 200, None, "ext-123", "https://ext.example.com/i/ext-123")

    monkeypatch.setattr(type(incident_sync_service), "_send", _ok)
    return sent


def _account():
    return account_service.register(f"u_{uuid4().hex[:10]}@example.com", "password123", "Alice")


def _alert(job_id="J1", classification="stuck", severity="critical"):
    return {"classification": classification, "severity": severity, "job_id": job_id, "reason": "x"}


# ── Target CRUD ──────────────────────────────────────────────────────────────


def test_target_crud_and_secret_never_returned():
    t = incident_sync_service.create_target(name="pd", url="https://hooks.example.com/i",
                                            kind="pagerduty", secret="shh", sync_actions="opened,recovered")
    assert t["has_secret"] is True and "secret" not in t and t["kind"] == "pagerduty"
    assert t["sync_actions"] == "opened,recovered"
    listed = incident_sync_service.list_targets()
    assert len(listed) == 1 and all("secret" not in row for row in listed)
    upd = incident_sync_service.update_target(t["id"], enabled=False)
    assert upd["enabled"] is False
    assert incident_sync_service.delete_target(t["id"]) is True
    assert incident_sync_service.list_targets() == []


def test_invalid_target_is_rejected():
    assert incident_sync_service.create_target(name="x", url="ftp://nope") is None
    assert incident_sync_service.create_target(name="", url="https://h.example.com") is None
    assert incident_sync_service.create_target(name="x", url="https://h.example.com", kind="weird") is None


def test_invalid_sync_config_rejected():
    from app.core.config import Settings
    with pytest.raises(ValueError):
        Settings(incident_sync_max_attempts=0)


# ── Real export of incident transitions ──────────────────────────────────────


def test_incident_open_exports_to_enabled_target(capture_send):
    incident_sync_service.create_target(name="t", url="https://h.example.com/i", secret="k")
    incident_service.observe([_alert(job_id="sync-open")])
    inc = next(i for i in incident_service.list() if i["subject"] == "sync-open")
    records = incident_sync_service.list_records(incident_id=inc["id"])
    assert len(records) == 1
    rec = records[0]
    assert rec["status"] == "synced" and rec["action"] == "opened"
    assert rec["incident_id"] == inc["id"] and rec["signal"] == inc["signal"]
    assert rec["external_ref"] == "ext-123"
    # The outbound payload is curated: identity + snapshot, signed, no secret in body.
    body = capture_send[0]["body"]
    assert body["type"] == "incident.transition" and body["incident"]["id"] == inc["id"]
    assert capture_send[0]["secret"] == "k" and "secret" not in str(body)


def test_action_allowlist_filters_what_is_mirrored(capture_send):
    incident_sync_service.create_target(name="t", url="https://h.example.com/i", sync_actions="acknowledged")
    incident_service.observe([_alert(job_id="filt-1")])  # opened -> NOT in allow-list
    inc = next(i for i in incident_service.list() if i["subject"] == "filt-1")
    assert incident_sync_service.list_records(incident_id=inc["id"]) == []
    incident_service.acknowledge(inc["id"], actor="alice")  # acknowledged -> mirrored
    recs = incident_sync_service.list_records(incident_id=inc["id"])
    assert len(recs) == 1 and recs[0]["action"] == "acknowledged" and recs[0]["actor"] == "alice"


def test_assignment_and_note_transitions_are_mirrored(capture_send):
    incident_sync_service.create_target(name="t", url="https://h.example.com/i")
    incident_service.observe([_alert(job_id="mir-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "mir-1")
    incident_service.assign(inc["id"], "jordan", actor="jordan")
    incident_service.set_note(inc["id"], "investigating", actor="jordan")
    actions = [r["action"] for r in incident_sync_service.list_records(incident_id=inc["id"])]
    assert "assigned" in actions and "note_updated" in actions
    note_rec = next(r for r in incident_sync_service.list_records(incident_id=inc["id"]) if r["action"] == "note_updated")
    assert note_rec["assignee"] == "jordan" and note_rec["note"] == "investigating"


def test_disabled_target_is_not_synced(capture_send):
    t = incident_sync_service.create_target(name="t", url="https://h.example.com/i")
    incident_sync_service.update_target(t["id"], enabled=False)
    incident_service.observe([_alert(job_id="off-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "off-1")
    assert incident_sync_service.list_records(incident_id=inc["id"]) == []


# ── Failure, bounded retry & redrive ─────────────────────────────────────────


def test_failed_sync_is_terminal_after_cap_then_redrivable(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "incident_sync_max_attempts", 1)
    incident_sync_service.create_target(name="t", url="https://h.example.com/i")

    def _fail(self, url, body_json, secret, adapter=None):
        return (False, 500, "HTTP500", None, None)
    monkeypatch.setattr(type(incident_sync_service), "_send", _fail)

    incident_service.observe([_alert(job_id="fail-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "fail-1")
    rec = incident_sync_service.list_records(incident_id=inc["id"])[0]
    assert rec["status"] == "failed" and rec["attempts"] == 1 and rec["last_error"] == "HTTP500"

    # Now the transport recovers; redrive schedules a fresh linked record that succeeds.
    def _ok(self, url, body_json, secret, adapter=None):
        return (True, 200, None, "ext-9", "https://ext.example.com/i/ext-9")
    monkeypatch.setattr(type(incident_sync_service), "_send", _ok)
    result = incident_sync_service.redrive(rec["id"])
    assert result["ok"] and result["record"]["status"] == "synced"
    assert result["record"]["is_redrive"] is True and result["record"]["redrive_of"] == rec["id"]
    # A synced (non-failed) record cannot be redriven.
    assert incident_sync_service.redrive(result["record"]["id"])["ok"] is False


# ── HTTP gating + separation ─────────────────────────────────────────────────


def test_sync_endpoints_require_operator(op):
    assert client.get("/operator/incident-targets", headers=OP).status_code == 200
    acct = _account()
    auth = {"Authorization": f"Bearer {make_account_token(acct['id'])}"}
    assert client.get("/operator/incident-targets", headers=auth).status_code in (401, 403)
    assert client.get("/operator/incident-sync", headers=auth).status_code in (401, 403)
    assert client.post("/operator/incident-targets", headers=auth,
                       json={"name": "x", "url": "https://h.example.com"}).status_code in (401, 403)
    assert client.get("/operator/incident-sync/nope", headers=OP).status_code == 404
    assert client.post("/operator/incident-sync/nope/redrive", headers=OP).status_code == 404


def test_sync_target_http_lifecycle_hides_secret(op):
    created = client.post("/operator/incident-targets", headers=OP,
                          json={"name": "pd", "url": "https://h.example.com/i", "secret": "topsecret"}).json()["target"]
    assert created["has_secret"] is True and "topsecret" not in str(created)
    listed = client.get("/operator/incident-targets", headers=OP).json()["targets"]
    assert "topsecret" not in str(listed)
    assert client.delete(f"/operator/incident-targets/{created['id']}", headers=OP).json()["ok"] is True


def test_sync_records_curated_over_http(op, capture_send):
    client.post("/operator/incident-targets", headers=OP, json={"name": "t", "url": "https://h.example.com/i"})
    incident_service.observe([_alert(job_id="http-sync")])
    inc = next(i for i in incident_service.list() if i["subject"] == "http-sync")
    records = client.get(f"/operator/incident-sync?incident_id={inc['id']}", headers=OP).json()["records"]
    assert len(records) == 1 and records[0]["status"] == "synced"
    # Curated payload — no raw internals / secrets.
    assert "payload_json" not in str(records) and "secret" not in str(records)


def test_no_sync_fields_leak_into_user_routes(capture_send):
    from app.execution_queue import execution_queue
    incident_sync_service.create_target(name="t", url="https://h.example.com/i")
    owner = _account()
    job = execution_queue.enqueue(f"account:{owner['id']}", "noop", {}, title="T")
    auth = {"Authorization": f"Bearer {make_account_token(owner['id'])}"}
    user_job = client.get(f"/jobs/{job['id']}", headers=auth).json()["job"]
    for operator_only in ("target_id", "sync_actions", "external_ref", "external_url", "has_secret"):
        assert operator_only not in user_job
    # No user-facing incident-sync routes exist.
    assert client.get("/incident-sync").status_code == 404
    assert client.get("/incident-targets").status_code == 404


# ── G-6: adapters, external linkage & sync health ────────────────────────────


def test_successful_sync_records_external_ref_url_and_links(capture_send):
    incident_sync_service.create_target(name="t", url="https://h.example.com/i")
    incident_service.observe([_alert(job_id="link-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "link-1")
    rec = incident_sync_service.list_records(incident_id=inc["id"])[0]
    assert rec["external_ref"] == "ext-123" and rec["external_url"].endswith("/ext-123")
    status = incident_sync_service.incident_sync_status(inc["id"])
    assert status["linked"] is True and len(status["links"]) == 1
    link = status["links"][0]
    assert link["external_ref"] == "ext-123" and link["external_url"].endswith("/ext-123")
    assert status["summary"]["synced"] is True and status["summary"]["behind"] is False


def test_link_is_not_invented_when_target_returns_none(monkeypatch):
    incident_sync_service.create_target(name="t", url="https://h.example.com/i")

    def _ok_noref(self, url, body_json, secret, adapter=None):
        return (True, 200, None, None, None)  # success but no ref/url returned
    monkeypatch.setattr(type(incident_sync_service), "_send", _ok_noref)

    incident_service.observe([_alert(job_id="noref-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "noref-1")
    status = incident_sync_service.incident_sync_status(inc["id"])
    # Synced, link row exists, but no fabricated ref/url.
    assert status["summary"]["synced"] is True and status["linked"] is True
    assert status["links"][0]["external_ref"] is None and status["links"][0]["external_url"] is None


def test_sync_behind_then_recovered_after_redrive(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "incident_sync_max_attempts", 1)
    incident_sync_service.create_target(name="t", url="https://h.example.com/i")

    def _fail(self, url, body_json, secret, adapter=None):
        return (False, 503, "HTTP503", None, None)
    monkeypatch.setattr(type(incident_sync_service), "_send", _fail)
    incident_service.observe([_alert(job_id="behind-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "behind-1")
    behind = incident_sync_service.incident_sync_status(inc["id"])
    assert behind["summary"]["behind"] is True and behind["linked"] is False
    assert behind["summary"]["last_error"] == "HTTP503"

    def _ok(self, url, body_json, secret, adapter=None):
        return (True, 200, None, "ext-7", "https://ext.example.com/i/ext-7")
    monkeypatch.setattr(type(incident_sync_service), "_send", _ok)
    failed = incident_sync_service.list_records(incident_id=inc["id"])[0]
    incident_sync_service.redrive(failed["id"])
    after = incident_sync_service.incident_sync_status(inc["id"])
    assert after["summary"]["behind"] is False and after["linked"] is True
    assert after["summary"]["recovered_after_redrive"] is True
    assert after["links"][0]["external_ref"] == "ext-7"


def test_pagerduty_adapter_shapes_payload_specifically(monkeypatch):
    incident_sync_service.create_target(name="pd", url="https://h.example.com/pd", kind="pagerduty")
    captured: dict = {}

    def _capture(self, url, body_json, secret, adapter=None):
        import json as _json
        captured["body"] = _json.loads(body_json)
        captured["adapter"] = getattr(adapter, "kind", None)
        return (True, 202, None, "pd-key-1", None)
    monkeypatch.setattr(type(incident_sync_service), "_send", _capture)

    incident_service.observe([_alert(job_id="pd-1")])
    # PagerDuty-style envelope, not the generic shape.
    assert captured["adapter"] == "pagerduty"
    assert captured["body"]["event_action"] == "trigger"
    assert captured["body"]["dedup_key"] and "payload" in captured["body"]
    assert "incident" not in captured["body"]  # reshaped, not the generic envelope
    inc = next(i for i in incident_service.list() if i["subject"] == "pd-1")
    assert incident_sync_service.incident_sync_status(inc["id"])["links"][0]["external_ref"] == "pd-key-1"


def test_incident_sync_status_and_target_health_over_http(op, capture_send):
    tgt = client.post("/operator/incident-targets", headers=OP,
                      json={"name": "t", "url": "https://h.example.com/i"}).json()["target"]
    incident_service.observe([_alert(job_id="status-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "status-1")
    status = client.get(f"/operator/incidents/{inc['id']}/sync", headers=OP).json()
    assert status["linked"] is True and status["links"][0]["external_url"].endswith("/ext-123")
    health = client.get(f"/operator/incident-targets/{tgt['id']}/health", headers=OP).json()["target"]
    assert health["health"] == "healthy" and health["recent"]["synced"] >= 1
    assert health["has_secret"] is False and "secret_value" not in health
    # Gating + 404s.
    acct = _account()
    auth = {"Authorization": f"Bearer {make_account_token(acct['id'])}"}
    assert client.get(f"/operator/incidents/{inc['id']}/sync", headers=auth).status_code in (401, 403)
    assert client.get(f"/operator/incident-targets/{tgt['id']}/health", headers=auth).status_code in (401, 403)
    assert client.get("/operator/incidents/nope/sync", headers=OP).status_code == 404
    assert client.get("/operator/incident-targets/nope/health", headers=OP).status_code == 404
