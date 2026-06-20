# File: backend/tests/test_incident_sync.py
"""External incident sync — operator-only OUTBOUND export of incident transitions.

An operator configures a sync target (secret stored, never returned). Real incident
transitions (opened / acknowledged / assigned / recovered / …) are mirrored to every
enabled target as a durable, curated `IncidentSyncRecord` correlated to the source
incident. A failed send is honest (terminal `failed` after the bounded attempt cap)
and operator-redrivable. Strictly operator-gated; secrets and raw internals never
leak; the user product gains nothing."""

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.accounts import account_service
from app.auth import make_account_token
import app.core.config as config_mod
from app.db.database import SessionLocal
from app.db.models import IncidentExternalLink
from app.incident_sync import incident_sync_service, classify_link_status, _now
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


# ── G-7: bounded inbound refresh, drift & staleness ──────────────────────────


def _fetch_returning(monkeypatch, *, ok=True, exists=True, status=None, url=None, err=None,
                     assignee=None, severity=None, updated_at=None, comment_count=None):
    """Stub the injectable inbound transport. `_fetch` now returns (ok, snapshot, err)
    where snapshot is the bounded `_external_state` dict."""
    from app.incident_sync import _external_state
    snap = None if exists is None and status is None else _external_state(
        exists=exists, status=status, url=url, assignee=assignee, severity=severity,
        updated_at=updated_at, comment_count=comment_count)

    def _fake(self, target_url, ref, secret, adapter=None):
        return (ok, snap, err)
    monkeypatch.setattr(type(incident_sync_service), "_fetch", _fake)


def test_classify_link_status_is_pure_and_bounded():
    now = _now()
    recent, old = now - timedelta(minutes=1), now - timedelta(days=2)
    # Never linked.
    assert classify_link_status(local_state="open", last_synced_at=None, last_checked_at=None,
                                external_exists=None, external_status=None, now=now, stale_seconds=3600)[0] == "never_linked"
    # Missing external.
    assert classify_link_status(local_state="open", last_synced_at=recent, last_checked_at=now,
                                external_exists=False, external_status=None, now=now, stale_seconds=3600)[0] == "missing_external"
    # Drift: external resolved while local still open.
    assert classify_link_status(local_state="open", last_synced_at=recent, last_checked_at=now,
                                external_exists=True, external_status="resolved", now=now, stale_seconds=3600)[0] == "drifted"
    # Drift: local recovered while external still open.
    assert classify_link_status(local_state="recovered", last_synced_at=recent, last_checked_at=now,
                                external_exists=True, external_status="open", now=now, stale_seconds=3600)[0] == "drifted"
    # Stale by age.
    assert classify_link_status(local_state="open", last_synced_at=old, last_checked_at=None,
                                external_exists=None, external_status=None, now=now, stale_seconds=3600)[0] == "stale"
    # Refreshed & aligned.
    assert classify_link_status(local_state="open", last_synced_at=recent, last_checked_at=now,
                                external_exists=True, external_status="open", now=now, stale_seconds=3600)[0] == "refreshed"
    # Linked (synced, not yet checked, fresh).
    assert classify_link_status(local_state="open", last_synced_at=recent, last_checked_at=None,
                                external_exists=None, external_status=None, now=now, stale_seconds=3600)[0] == "linked"


def test_refresh_detects_external_resolved_drift(capture_send, monkeypatch):
    incident_sync_service.create_target(name="t", url="https://h.example.com/i")
    incident_service.observe([_alert(job_id="drift-ext")])
    inc = next(i for i in incident_service.list() if i["subject"] == "drift-ext")
    # Externally resolved, but the local incident is still open → drift.
    _fetch_returning(monkeypatch, ok=True, exists=True, status="resolved")
    status = incident_sync_service.refresh(inc["id"])
    assert status["summary"]["link_status"] == "drifted"
    assert status["links"][0]["external_status"] == "resolved" and status["links"][0]["last_checked_at"]
    # Refresh NEVER mutates the local incident.
    assert incident_service.get(inc["id"])["state"] == "open"


def test_refresh_detects_missing_external(capture_send, monkeypatch):
    incident_sync_service.create_target(name="t", url="https://h.example.com/i")
    incident_service.observe([_alert(job_id="gone-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "gone-1")
    _fetch_returning(monkeypatch, ok=True, exists=False, status="missing")
    status = incident_sync_service.refresh(inc["id"])
    assert status["summary"]["link_status"] == "missing_external"
    assert status["links"][0]["external_exists"] is False


def test_refresh_aligned_marks_refreshed(capture_send, monkeypatch):
    incident_sync_service.create_target(name="t", url="https://h.example.com/i")
    incident_service.observe([_alert(job_id="ok-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "ok-1")
    _fetch_returning(monkeypatch, ok=True, exists=True, status="open")
    status = incident_sync_service.refresh(inc["id"])
    assert status["summary"]["link_status"] == "refreshed" and status["summary"]["refresh_supported"] is True


def test_unsupported_adapter_stays_outbound_only(capture_send, monkeypatch):
    incident_sync_service.create_target(name="j", url="https://h.example.com/j", kind="jira")
    incident_service.observe([_alert(job_id="jira-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "jira-1")
    # Even if a refresh is attempted, the jira adapter is outbound-only → no inbound state.
    called = {"n": 0}
    def _should_not_run(self, target_url, ref, secret, adapter=None):
        called["n"] += 1
        return (True, {"exists": True, "status": "resolved"}, None)
    monkeypatch.setattr(type(incident_sync_service), "_fetch", _should_not_run)
    status = incident_sync_service.refresh(inc["id"])
    assert called["n"] == 0  # outbound-only adapter is honestly skipped
    assert status["summary"]["refresh_supported"] is False
    assert status["links"][0]["external_status"] is None and status["links"][0]["last_checked_at"] is None


def test_stale_link_detected_by_age(capture_send):
    incident_sync_service.create_target(name="t", url="https://h.example.com/i")
    incident_service.observe([_alert(job_id="stale-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "stale-1")
    # Age the last successful sync past the default stale window (24h).
    with SessionLocal() as s:
        link = s.query(IncidentExternalLink).filter(IncidentExternalLink.incident_id == inc["id"]).first()
        link.last_synced_at = _now() - timedelta(days=2)
        s.commit()
    status = incident_sync_service.incident_sync_status(inc["id"], incident_state="open")
    assert status["summary"]["link_status"] == "stale"


def test_refresh_without_links_is_409_over_http(op):
    incident_service.observe([_alert(job_id="nolink-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "nolink-1")
    assert client.post(f"/operator/incidents/{inc['id']}/sync/refresh", headers=OP).status_code == 409


def test_refresh_and_drift_over_http(op, capture_send, monkeypatch):
    client.post("/operator/incident-targets", headers=OP, json={"name": "t", "url": "https://h.example.com/i"})
    incident_service.observe([_alert(job_id="http-drift")])
    inc = next(i for i in incident_service.list() if i["subject"] == "http-drift")
    _fetch_returning(monkeypatch, ok=True, exists=True, status="resolved")
    refreshed = client.post(f"/operator/incidents/{inc['id']}/sync/refresh", headers=OP).json()
    assert refreshed["summary"]["link_status"] == "drifted"
    drift = client.get("/operator/incident-sync/drift", headers=OP).json()["links"]
    assert any(link["incident_id"] == inc["id"] and link["link_status"] == "drifted" for link in drift)
    # Gating.
    acct = _account()
    auth = {"Authorization": f"Bearer {make_account_token(acct['id'])}"}
    assert client.post(f"/operator/incidents/{inc['id']}/sync/refresh", headers=auth).status_code in (401, 403)
    assert client.get("/operator/incident-sync/drift", headers=auth).status_code in (401, 403)


def test_stale_config_rejected():
    from app.core.config import Settings
    with pytest.raises(ValueError):
        Settings(incident_link_stale_seconds=0)


# ── G-8: drift resolution, link repair & scheduled reconciliation ────────────


def _target_id_for(incident_id):
    return incident_sync_service.incident_sync_status(incident_id)["links"][0]["target_id"]


def test_detach_excludes_link_from_drift_without_touching_local(capture_send, monkeypatch):
    incident_sync_service.create_target(name="t", url="https://h.example.com/i")
    incident_service.observe([_alert(job_id="det-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "det-1")
    _fetch_returning(monkeypatch, ok=True, exists=False, status="missing")  # external gone -> missing
    incident_sync_service.refresh(inc["id"])
    assert incident_sync_service.incident_sync_status(inc["id"])["summary"]["link_status"] == "missing_external"
    # Detach the bad link.
    status = incident_sync_service.detach(inc["id"], _target_id_for(inc["id"]))
    assert status["summary"]["link_status"] == "detached" and status["linked"] is False
    assert status["links"][0]["detached"] is True and status["links"][0]["detached_at"]
    # No longer surfaced as actionable drift; local incident untouched.
    assert all(link["incident_id"] != inc["id"] for link in incident_sync_service.drifted())
    assert incident_service.get(inc["id"])["state"] == "open"
    # A reconciliation event records the repair.
    assert any(e["action"] == "detach" and e["outcome"] == "ok" for e in status["reconciliation"])


def test_relink_requires_adapter_verification(capture_send, monkeypatch):
    incident_sync_service.create_target(name="t", url="https://h.example.com/i")
    incident_service.observe([_alert(job_id="rel-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "rel-1")
    target_id = _target_id_for(inc["id"])
    incident_sync_service.detach(inc["id"], target_id)
    # Verification fails → relink refused, link stays detached, no blind trust.
    _fetch_returning(monkeypatch, ok=True, exists=False, status="missing")
    refused = incident_sync_service.relink(inc["id"], target_id, "EXT-NEW")
    assert refused["ok"] is False
    assert incident_sync_service.incident_sync_status(inc["id"])["links"][0]["detached"] is True
    # Verification succeeds → relink reattaches with the verified ref.
    _fetch_returning(monkeypatch, ok=True, exists=True, status="open", url="https://ext.example.com/i/EXT-NEW")
    ok = incident_sync_service.relink(inc["id"], target_id, "EXT-NEW")
    assert ok["ok"] is True
    link = ok["status"]["links"][0]
    assert link["detached"] is False and link["external_ref"] == "EXT-NEW"
    assert link["external_url"].endswith("/EXT-NEW") and link["external_status"] == "open"


def test_relink_unsupported_adapter_is_refused_honestly(capture_send, monkeypatch):
    incident_sync_service.create_target(name="j", url="https://h.example.com/j", kind="jira")
    incident_service.observe([_alert(job_id="rel-jira")])
    inc = next(i for i in incident_service.list() if i["subject"] == "rel-jira")
    target_id = _target_id_for(inc["id"])
    called = {"n": 0}
    def _should_not_run(self, target_url, ref, secret, adapter=None):
        called["n"] += 1
        return (True, {"exists": True, "status": "open"}, None)
    monkeypatch.setattr(type(incident_sync_service), "_fetch", _should_not_run)
    result = incident_sync_service.relink(inc["id"], target_id, "EXT-X")
    assert result["ok"] is False and called["n"] == 0  # outbound-only can't verify → refused, no fetch


def test_redrive_from_incident_context(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "incident_sync_max_attempts", 1)
    incident_sync_service.create_target(name="t", url="https://h.example.com/i")
    def _fail(self, url, body_json, secret, adapter=None):
        return (False, 500, "HTTP500", None, None)
    monkeypatch.setattr(type(incident_sync_service), "_send", _fail)
    incident_service.observe([_alert(job_id="rd-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "rd-1")
    assert incident_sync_service.incident_sync_status(inc["id"])["summary"]["actions"]["can_redrive"] is True
    def _ok(self, url, body_json, secret, adapter=None):
        return (True, 200, None, "ext-rd", "https://ext.example.com/i/ext-rd")
    monkeypatch.setattr(type(incident_sync_service), "_send", _ok)
    result = incident_sync_service.redrive_incident_latest(inc["id"])
    assert result["ok"] and result["record"]["status"] == "synced"
    # Nothing failed left to redrive now.
    assert incident_sync_service.redrive_incident_latest(inc["id"])["ok"] is False


def test_reconcile_sweep_rechecks_stale_links_bounded(capture_send, monkeypatch):
    incident_sync_service.create_target(name="t", url="https://h.example.com/i")
    incident_service.observe([_alert(job_id="rec-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "rec-1")
    # Age the link so reconcile considers it; external now reports resolved → drift.
    with SessionLocal() as s:
        link = s.query(IncidentExternalLink).filter(IncidentExternalLink.incident_id == inc["id"]).first()
        link.last_synced_at = _now() - timedelta(days=2)
        s.commit()
    _fetch_returning(monkeypatch, ok=True, exists=True, status="resolved")
    counts = incident_sync_service.reconcile()
    assert counts["checked"] >= 1
    status = incident_sync_service.incident_sync_status(inc["id"], incident_state="open")
    assert status["summary"]["link_status"] == "drifted" and status["links"][0]["last_checked_at"]
    # Reconcile never mutates local incident state.
    assert incident_service.get(inc["id"])["state"] == "open"


def test_drift_resolution_over_http_and_gating(op, capture_send, monkeypatch):
    client.post("/operator/incident-targets", headers=OP, json={"name": "t", "url": "https://h.example.com/i"})
    incident_service.observe([_alert(job_id="http-resolve")])
    inc = next(i for i in incident_service.list() if i["subject"] == "http-resolve")
    target_id = _target_id_for(inc["id"])
    # Detach over HTTP.
    detached = client.post(f"/operator/incidents/{inc['id']}/sync/detach", headers=OP,
                           json={"target_id": target_id}).json()
    assert detached["links"][0]["detached"] is True
    # Relink over HTTP (verified).
    _fetch_returning(monkeypatch, ok=True, exists=True, status="open", url="https://ext.example.com/i/RE-1")
    relinked = client.post(f"/operator/incidents/{inc['id']}/sync/relink", headers=OP,
                           json={"target_id": target_id, "external_ref": "RE-1"})
    assert relinked.status_code == 200 and relinked.json()["status"]["links"][0]["detached"] is False
    # Reconcile sweep over HTTP.
    assert "reconciled" in client.post("/operator/incident-sync/reconcile", headers=OP).json()
    # Curated payload — no secrets / raw internals.
    assert "secret_value" not in str(relinked.json())
    # Gating: normal account token denied on every resolution endpoint.
    acct = _account()
    auth = {"Authorization": f"Bearer {make_account_token(acct['id'])}"}
    assert client.post(f"/operator/incidents/{inc['id']}/sync/detach", headers=auth, json={"target_id": target_id}).status_code in (401, 403)
    assert client.post(f"/operator/incidents/{inc['id']}/sync/relink", headers=auth, json={"target_id": target_id, "external_ref": "x"}).status_code in (401, 403)
    assert client.post(f"/operator/incidents/{inc['id']}/sync/redrive", headers=auth).status_code in (401, 403)
    assert client.post("/operator/incident-sync/reconcile", headers=auth).status_code in (401, 403)


def test_reconcile_config_rejected():
    from app.core.config import Settings
    with pytest.raises(ValueError):
        Settings(incident_reconcile_max_per_sweep=0)


def test_no_reconciliation_fields_leak_into_user_routes(capture_send):
    from app.execution_queue import execution_queue
    incident_sync_service.create_target(name="t", url="https://h.example.com/i")
    owner = _account()
    job = execution_queue.enqueue(f"account:{owner['id']}", "noop", {}, title="T")
    auth = {"Authorization": f"Bearer {make_account_token(owner['id'])}"}
    user_job = client.get(f"/jobs/{job['id']}", headers=auth).json()["job"]
    for operator_only in ("detached", "detached_at", "link_status", "reconciliation", "external_status"):
        assert operator_only not in user_job


# ── G-9: explicit local-vs-external resolution (apply / push / capabilities) ──


def test_adapter_capabilities_are_explicit_and_honest():
    from app.incident_sync import adapter_capabilities
    gen = adapter_capabilities("generic")
    assert gen["refresh"] and gen["push_outward"] and gen["relink_validation"]
    assert gen["status_sync"] is False and gen["support_level"] == "refresh"
    pd = adapter_capabilities("pagerduty")
    assert pd["push_outward"] and pd["status_sync"] is True and pd["support_level"] == "rich"
    # Outbound-only: can push, cannot refresh / validate a relink / status-sync.
    jira = adapter_capabilities("jira")
    assert jira == {"refresh": False, "push_outward": True, "relink_validation": False,
                    "status_sync": False, "support_level": "outbound_only"}


def test_external_resolved_is_actionable_without_silently_mutating_local(capture_send, monkeypatch):
    incident_sync_service.create_target(name="t", url="https://h.example.com/i")
    incident_service.observe([_alert(job_id="apply-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "apply-1")
    _fetch_returning(monkeypatch, ok=True, exists=True, status="resolved")
    status = incident_sync_service.refresh(inc["id"])  # observe only — must NOT change local
    assert status["summary"]["link_status"] == "drifted"
    assert status["summary"]["actions"]["can_apply"] is True
    assert status["summary"]["actions"]["apply_action"] == "accept_resolved"
    assert incident_service.get(inc["id"])["state"] == "open"  # refresh never mutates local


def test_apply_accept_resolved_recovers_local_only_when_invoked(capture_send, monkeypatch):
    incident_sync_service.create_target(name="t", url="https://h.example.com/i")
    incident_service.observe([_alert(job_id="apply-2")])
    inc = next(i for i in incident_service.list() if i["subject"] == "apply-2")
    _fetch_returning(monkeypatch, ok=True, exists=True, status="resolved")
    incident_sync_service.refresh(inc["id"])
    result = incident_sync_service.apply_from_external(inc["id"], "accept_resolved", actor="alice")
    assert result["ok"] and result["changed_local"] is True
    # Local incident is now explicitly recovered, and the trail records WHY.
    assert incident_service.get(inc["id"])["state"] == "recovered"
    trail = incident_service.history(inc["id"])
    assert any(e["action"] == "recovered" and "external" in (e["detail"] or "") for e in trail)
    # The reconciliation log captures the apply action + that it changed local state.
    recon = incident_sync_service.incident_sync_status(inc["id"])["reconciliation"]
    assert any(e["action"] == "apply:accept_resolved" and e["outcome"] == "ok" for e in recon)


def test_apply_refused_when_not_applicable(capture_send, monkeypatch):
    incident_sync_service.create_target(name="t", url="https://h.example.com/i")
    incident_service.observe([_alert(job_id="apply-3")])
    inc = next(i for i in incident_service.list() if i["subject"] == "apply-3")
    _fetch_returning(monkeypatch, ok=True, exists=True, status="open")  # aligned, no drift
    incident_sync_service.refresh(inc["id"])
    refused = incident_sync_service.apply_from_external(inc["id"], "accept_resolved", actor="alice")
    assert refused["ok"] is False
    assert incident_service.get(inc["id"])["state"] == "open"  # untouched


def test_apply_accept_missing_detaches_link_only(capture_send, monkeypatch):
    incident_sync_service.create_target(name="t", url="https://h.example.com/i")
    incident_service.observe([_alert(job_id="apply-4")])
    inc = next(i for i in incident_service.list() if i["subject"] == "apply-4")
    _fetch_returning(monkeypatch, ok=True, exists=False, status="missing")
    incident_sync_service.refresh(inc["id"])
    assert incident_sync_service.incident_sync_status(inc["id"])["summary"]["actions"]["apply_action"] == "accept_missing"
    result = incident_sync_service.apply_from_external(inc["id"], "accept_missing", actor="bob")
    assert result["ok"] and result["changed_local"] is False  # linkage only
    assert incident_sync_service.incident_sync_status(inc["id"])["links"][0]["detached"] is True
    assert incident_service.get(inc["id"])["state"] == "open"  # local untouched


def test_push_outward_uses_adapter_and_records(monkeypatch):
    sent = []
    def _capture(self, url, body_json, secret, adapter=None):
        sent.append(getattr(adapter, "kind", None))
        return (True, 200, None, "ext-push", None)
    monkeypatch.setattr(type(incident_sync_service), "_send", _capture)
    incident_sync_service.create_target(name="t", url="https://h.example.com/i")
    incident_service.observe([_alert(job_id="push-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "push-1")
    incident_service.mark_recovered(inc["id"], actor="alice")  # local recovered
    sent.clear()
    result = incident_sync_service.push_outward(inc["id"], actor="alice")
    assert result["ok"] and result["changed_local"] is False
    assert sent and sent[-1] == "generic"  # explicitly re-sent outward
    pushed = next(r for r in incident_sync_service.list_records(incident_id=inc["id"]) if r["action"] == "recovered")
    assert pushed["status"] == "synced"


def test_push_outward_unsupported_adapter_is_skipped_honestly(monkeypatch):
    called = {"n": 0}
    def _capture(self, url, body_json, secret, adapter=None):
        called["n"] += 1
        return (True, 200, None, None, None)
    monkeypatch.setattr(type(incident_sync_service), "_send", _capture)
    # An outbound-only adapter CAN push (it is outbound), so assert push works there too.
    incident_sync_service.create_target(name="j", url="https://h.example.com/j", kind="jira")
    incident_service.observe([_alert(job_id="push-jira")])
    inc = next(i for i in incident_service.list() if i["subject"] == "push-jira")
    called["n"] = 0
    result = incident_sync_service.push_outward(inc["id"], actor="alice")
    assert result["ok"] and called["n"] >= 1  # jira is outbound-capable → pushed


def test_apply_and_push_over_http_with_gating(op, capture_send, monkeypatch):
    client.post("/operator/incident-targets", headers=OP, json={"name": "t", "url": "https://h.example.com/i"})
    incident_service.observe([_alert(job_id="http-apply")])
    inc = next(i for i in incident_service.list() if i["subject"] == "http-apply")
    _fetch_returning(monkeypatch, ok=True, exists=True, status="resolved")
    client.post(f"/operator/incidents/{inc['id']}/sync/refresh", headers=OP)
    # can_apply / can_push are surfaced honestly in the status.
    summary = client.get(f"/operator/incidents/{inc['id']}/sync", headers=OP).json()["summary"]
    assert summary["actions"]["can_apply"] is True and summary["actions"]["can_push"] is True
    # Apply over HTTP → local recovered.
    applied = client.post(f"/operator/incidents/{inc['id']}/sync/apply", headers=OP, json={"action": "accept_resolved"})
    assert applied.status_code == 200 and applied.json()["changed_local"] is True
    assert incident_service.get(inc["id"])["state"] == "recovered"
    # Push over HTTP.
    pushed = client.post(f"/operator/incidents/{inc['id']}/sync/push", headers=OP, json={})
    assert pushed.status_code == 200 and pushed.json()["ok"] is True
    # Applying again is now refused (no longer applicable) → 409.
    assert client.post(f"/operator/incidents/{inc['id']}/sync/apply", headers=OP, json={"action": "accept_resolved"}).status_code == 409
    # Gating: normal account token denied.
    acct = _account()
    auth = {"Authorization": f"Bearer {make_account_token(acct['id'])}"}
    assert client.post(f"/operator/incidents/{inc['id']}/sync/apply", headers=auth, json={"action": "accept_resolved"}).status_code in (401, 403)
    assert client.post(f"/operator/incidents/{inc['id']}/sync/push", headers=auth, json={}).status_code in (401, 403)


# ── G-10: richer adapters, bounded inbound status sync & suggestions ─────────


def _pd_fetch(monkeypatch, **fields):
    """Stub a PagerDuty-shaped inbound snapshot (richer bounded fields)."""
    from app.incident_sync import _external_state
    snap = _external_state(exists=True, status=fields.get("status", "acknowledged"),
                           url=fields.get("url"), assignee=fields.get("assignee"),
                           severity=fields.get("severity"), updated_at=fields.get("updated_at"),
                           comment_count=fields.get("comment_count"))
    monkeypatch.setattr(type(incident_sync_service), "_fetch", lambda self, u, r, s, adapter=None: (True, snap, None))


def test_pagerduty_adapter_parses_bounded_rich_snapshot():
    from app.incident_sync import adapter_for
    pd = adapter_for("pagerduty")
    body = {
        "status": "acknowledged", "urgency": "high", "html_url": "https://pd.example.com/i/1",
        "last_status_change_at": "2026-06-20T10:00:00Z",
        "assignments": [{"assignee": {"summary": "Dana Ops", "email": "secret@pd.example.com"}}],
        "alert_counts": {"all": 7, "triggered": 2},
        "description": "RAW INCIDENT BODY THAT MUST NOT BE INGESTED",
    }
    snap = pd.parse_snapshot(200, {}, body)
    assert snap["status"] == "acknowledged" and snap["assignee"] == "Dana Ops"
    assert snap["severity"] == "critical" and snap["comment_count"] == 7
    assert snap["updated_at"] == "2026-06-20T10:00:00Z"
    # Bounded: only the allowed normalized keys — no raw body / email leaks through.
    assert set(snap) == {"exists", "status", "url", "assignee", "severity", "updated_at", "comment_count"}
    assert "secret@pd.example.com" not in str(snap) and "RAW INCIDENT BODY" not in str(snap)


def test_generic_adapter_does_not_surface_rich_fields():
    from app.incident_sync import adapter_for
    snap = adapter_for("generic").parse_snapshot(200, {}, {"status": "open", "assignee": "X", "urgency": "high"})
    assert snap["status"] == "open"
    assert snap["assignee"] is None and snap["severity"] is None  # generic stays thin


def test_status_sync_stores_only_normalized_fields_and_keeps_local_primary(monkeypatch):
    incident_sync_service.create_target(name="pd", url="https://h.example.com/pd", kind="pagerduty")

    def _push_ok(self, url, body_json, secret, adapter=None):
        return (True, 200, None, "pd-1", "https://pd.example.com/i/1")
    monkeypatch.setattr(type(incident_sync_service), "_send", _push_ok)
    incident_service.observe([_alert(job_id="rich-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "rich-1")
    incident_service.assign(inc["id"], "alice")  # local owner
    _pd_fetch(monkeypatch, status="acknowledged", assignee="Dana Ops", severity="critical",
              updated_at="2026-06-20T10:00:00Z", comment_count=7)
    status = incident_sync_service.refresh(inc["id"])
    link = status["links"][0]
    assert link["external_assignee"] == "Dana Ops" and link["external_severity"] == "critical"
    assert link["external_comment_count"] == 7 and link["capabilities"]["status_sync"] is True
    assert status["summary"]["support_level"] == "rich"
    # Inbound status sync NEVER mutates local state.
    assert incident_service.get(inc["id"])["state"] == "open"
    assert incident_service.get(inc["id"])["assignee"] == "alice"


def test_external_state_suggestions_are_bounded_and_honest():
    from app.incident_sync import external_state_suggestions
    # Aligned → calm.
    aligned = external_state_suggestions({"state": "open", "assignee": "alice"},
                                         {"external_status": "open", "external_exists": True, "detached": False})
    assert [s["code"] for s in aligned] == ["aligned"]
    # Acknowledged externally + owner mismatch + high severity → multiple high-signal hints.
    rich = external_state_suggestions(
        {"state": "open", "assignee": "alice"},
        {"external_status": "acknowledged", "external_exists": True, "external_assignee": "Dana Ops",
         "external_severity": "critical", "detached": False})
    codes = {s["code"] for s in rich}
    assert "external_acknowledged" in codes and "owner_mismatch" in codes and "high_severity" in codes
    assert all(set(s) == {"code", "tone", "text"} for s in rich) and len(rich) <= 4
    # Missing → detach hint, nothing else.
    missing = external_state_suggestions({"state": "open"},
                                         {"external_exists": False, "detached": False})
    assert [s["code"] for s in missing] == ["external_missing"]
    # Detached / never-observed → no suggestions.
    assert external_state_suggestions({"state": "open"}, {"detached": True, "external_status": "resolved"}) == []
    assert external_state_suggestions({"state": "open"}, {"external_status": None, "external_exists": True, "detached": False}) == []


def test_suggestions_surface_in_status_after_refresh(capture_send, monkeypatch):
    incident_sync_service.create_target(name="pd", url="https://h.example.com/pd", kind="pagerduty")
    incident_service.observe([_alert(job_id="sugg-1")])
    inc = next(i for i in incident_service.list() if i["subject"] == "sugg-1")
    _pd_fetch(monkeypatch, status="resolved", severity="critical")
    status = incident_sync_service.refresh(inc["id"])
    codes = {s["code"] for s in status["summary"]["suggestions"]}
    assert "external_resolved" in codes  # resolved-while-open is surfaced


def test_target_capabilities_endpoint(op):
    pd = client.post("/operator/incident-targets", headers=OP,
                     json={"name": "pd", "url": "https://h.example.com/pd", "kind": "pagerduty"}).json()["target"]
    caps = client.get(f"/operator/incident-targets/{pd['id']}/capabilities", headers=OP).json()
    assert caps["support_level"] == "rich" and caps["capabilities"]["status_sync"] is True
    # Gating + 404.
    acct = _account()
    auth = {"Authorization": f"Bearer {make_account_token(acct['id'])}"}
    assert client.get(f"/operator/incident-targets/{pd['id']}/capabilities", headers=auth).status_code in (401, 403)
    assert client.get("/operator/incident-targets/nope/capabilities", headers=OP).status_code == 404


def test_no_rich_inbound_fields_leak_into_user_routes(capture_send, monkeypatch):
    from app.execution_queue import execution_queue
    incident_sync_service.create_target(name="pd", url="https://h.example.com/pd", kind="pagerduty")
    owner = _account()
    job = execution_queue.enqueue(f"account:{owner['id']}", "noop", {}, title="T")
    auth = {"Authorization": f"Bearer {make_account_token(owner['id'])}"}
    user_job = client.get(f"/jobs/{job['id']}", headers=auth).json()["job"]
    for operator_only in ("external_assignee", "external_severity", "external_comment_count",
                          "support_level", "suggestions", "capabilities"):
        assert operator_only not in user_job
