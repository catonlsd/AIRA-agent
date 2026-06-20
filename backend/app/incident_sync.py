# File: backend/app/incident_sync.py
"""
External incident sync — operator-only OUTBOUND export of incident transitions.

A small, durable foundation for mirroring operator incident workflow
(open / acknowledge / silence / assign / note / recover / …) to an external
incident or ticket tool. Deliberately one-way (outbound from AIRA-X) and honest
about it — there is no inbound/bidirectional sync pretence.

Kept DISTINCT from webhook *event/alert routing* (`app/webhooks.py`): that fans
job-lifecycle events and alerts to subscribers; this mirrors *incident workflow
transitions* to incident tooling. Different concern, different tables, different
operator config — so neither muddies the other.

Each export is a durable `IncidentSyncRecord` snapshotting the curated incident
fields (never raw payloads/traces/secrets/owners), correlated to the source
incident. Sending is the single injectable primitive `_send` (HMAC-signed, like
the delivery layer) so the state machine and tests are network-free. Status runs
pending → synced | failed; retry is bounded by `incident_sync_max_attempts`, and a
terminal-failed record is operator-redrivable (bounded by
`incident_sync_max_redrives`). The whole surface is operator-gated at the routes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from uuid import uuid4

from app.core.config import settings
from app.db.database import Base, SessionLocal, engine
from app.db.models import (
    ExternalIncidentTarget,
    IncidentExternalLink,
    IncidentReconciliationEvent,
    IncidentSyncRecord,
)

STATUS_PENDING = "pending"
STATUS_SYNCED = "synced"
STATUS_FAILED = "failed"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _csv_set(value: Optional[str]) -> Optional[set[str]]:
    if not value:
        return None
    items = {part.strip() for part in value.split(",") if part.strip()}
    return items or None


# ── adapter registry (target-kind-specific shaping + response parsing) ────────
#
# Every adapter keeps the SAME curated contract: it shapes the stable internal
# snapshot into the body a given target expects, and parses a target response into
# (external_ref, external_url) — nothing else changes in the state machine, so retry,
# redrive, linkage, and tests stay adapter-agnostic. The transport (`_send`) is a
# single injectable primitive. New vendors are a one-class addition; AIRA-X stays
# strictly OUTBOUND — no adapter reads external state back.


class GenericIncidentAdapter:
    """Default: send the curated envelope as-is; read a ref/url from common response
    headers or a small JSON body (never invents a link the target didn't return)."""

    kind = "generic"
    supports_refresh = True       # bounded inbound GET of {exists,status,url}
    supports_push_outward = True  # operator can explicitly re-send local state outward

    def shape(self, payload: dict) -> dict:
        return payload

    def parse(self, status_code: Optional[int], headers: dict, body: Optional[dict]) -> tuple[Optional[str], Optional[str]]:
        ref = (headers.get("X-Incident-Ref") or headers.get("x-incident-ref"))
        url = (headers.get("Location") or headers.get("location"))
        if body:
            ref = ref or body.get("ref") or body.get("id") or body.get("dedup_key")
            url = url or body.get("url") or body.get("html_url") or body.get("link")
        return ((str(ref)[:120] if ref else None), (str(url)[:500] if url else None))

    def parse_status(self, status_code: Optional[int], headers: dict, body: Optional[dict]) -> tuple[Optional[bool], Optional[str], Optional[str]]:
        """Bounded inbound parse → (external_exists, normalized_status, external_url).
        404 means the external incident is gone. Never raises."""
        if status_code == 404:
            return (False, EXT_MISSING, None)
        if not body:
            return (True, EXT_UNKNOWN, None)
        exists = body.get("exists")
        exists = True if exists is None else bool(exists)
        url = body.get("url") or body.get("html_url") or body.get("link")
        return (exists, _normalize_status(body.get("status") or body.get("state")),
                (str(url)[:500] if url else None))


class PagerDutyIncidentAdapter:
    """Adapter-specific pathway shaping the snapshot into a PagerDuty Events-v2-style
    envelope (event_action mapped from the incident transition, `dedup_key` = the
    incident signal) and parsing the returned `dedup_key`/url. This is real shaping +
    response parsing — it does NOT claim a verified PagerDuty connection; point a
    target of kind=pagerduty at any endpoint speaking this shape."""

    kind = "pagerduty"
    supports_refresh = True
    supports_push_outward = True  # event_action maps recovered→resolve, reopen→trigger
    _EVENT_ACTION = {
        "opened": "trigger", "reopened": "trigger", "recovered": "resolve",
        "acknowledged": "acknowledge",
    }

    def shape(self, payload: dict) -> dict:
        incident = payload.get("incident", {})
        action = payload.get("action", "")
        return {
            "event_action": self._EVENT_ACTION.get(action, "trigger"),
            "dedup_key": incident.get("signal") or incident.get("id"),
            "payload": {
                "summary": f"{incident.get('classification') or 'incident'} · {incident.get('subject') or ''}".strip(" ·"),
                "severity": incident.get("severity") or "warning",
                "source": "AIRA-X",
                "custom_details": {
                    "incident_id": incident.get("id"),
                    "state": incident.get("state"),
                    "assignee": incident.get("assignee"),
                    "note": incident.get("note"),
                    "action": action,
                    "actor": payload.get("actor"),
                },
            },
        }

    def parse(self, status_code: Optional[int], headers: dict, body: Optional[dict]) -> tuple[Optional[str], Optional[str]]:
        ref = url = None
        if body:
            ref = body.get("dedup_key") or body.get("id")
            url = body.get("url") or body.get("html_url") or (headers.get("Location") if headers else None)
        else:
            ref = (headers.get("X-Incident-Ref") if headers else None)
        return ((str(ref)[:120] if ref else None), (str(url)[:500] if url else None))

    def parse_status(self, status_code: Optional[int], headers: dict, body: Optional[dict]) -> tuple[Optional[bool], Optional[str], Optional[str]]:
        """PagerDuty incidents expose status triggered/acknowledged/resolved."""
        if status_code == 404:
            return (False, EXT_MISSING, None)
        if not body:
            return (True, EXT_UNKNOWN, None)
        url = body.get("url") or body.get("html_url")
        return (True, _normalize_status(body.get("status")), (str(url)[:500] if url else None))


class OutboundOnlyAdapter(GenericIncidentAdapter):
    """Reserved target kinds with no real inbound adapter yet: outbound shaping +
    push-outward work (via the generic envelope), but refresh / relink-validation are
    honestly unsupported — AIRA-X will not claim to KNOW external state for these
    until a real adapter lands. (Outbound-only = it can send, it can't read back.)"""

    supports_refresh = False
    # supports_push_outward stays True (inherited): outbound is exactly what it does.


_ADAPTERS = {
    "generic": GenericIncidentAdapter(),
    "pagerduty": PagerDutyIncidentAdapter(),
    "jira": OutboundOnlyAdapter(),
    "opsgenie": OutboundOnlyAdapter(),
}
_GENERIC = _ADAPTERS["generic"]
_KINDS = set(_ADAPTERS)


def adapter_for(kind: Optional[str]):
    return _ADAPTERS.get(kind or "generic", _GENERIC)


def adapter_capabilities(kind: Optional[str]) -> dict[str, bool]:
    """The honest, explicit capability set for a target kind. `relink_validation`
    needs a bounded inbound check, so it tracks `supports_refresh`."""
    adapter = adapter_for(kind)
    refresh = bool(getattr(adapter, "supports_refresh", False))
    return {
        "refresh": refresh,
        "push_outward": bool(getattr(adapter, "supports_push_outward", False)),
        "relink_validation": refresh,
    }


# ── external status normalization + link-status classification (pure) ─────────

EXT_OPEN = "open"
EXT_ACKNOWLEDGED = "acknowledged"
EXT_RESOLVED = "resolved"
EXT_MISSING = "missing"
EXT_UNKNOWN = "unknown"

LINK_LINKED = "linked"
LINK_NEVER = "never_linked"
LINK_STALE = "stale"
LINK_MISSING = "missing_external"
LINK_DRIFTED = "drifted"
LINK_REFRESHED = "refreshed"
LINK_DETACHED = "detached"

_LOCAL_OPEN = {"open", "acknowledged", "silenced"}
_EXT_CLOSED = {EXT_RESOLVED, "closed", "done"}
_EXT_OPEN = {EXT_OPEN, "triggered", EXT_ACKNOWLEDGED}


def _normalize_status(raw: Optional[str]) -> str:
    if not raw:
        return EXT_UNKNOWN
    value = str(raw).strip().lower()
    if value in _EXT_CLOSED:
        return EXT_RESOLVED
    if value in ("triggered", "open", "firing"):
        return EXT_OPEN
    if value in ("acknowledged", "ack", "acked"):
        return EXT_ACKNOWLEDGED
    return value[:24]


def classify_link_status(*, local_state: Optional[str], last_synced_at: Optional[datetime],
                         last_checked_at: Optional[datetime], external_exists: Optional[bool],
                         external_status: Optional[str], now: datetime,
                         stale_seconds: int, detached: bool = False) -> tuple[str, str]:
    """Pure, bounded reconciliation verdict for one link → (status, reason). Local
    state stays primary; this only *describes* alignment, it never mutates anything."""
    if detached:
        return (LINK_DETACHED, "intentionally detached")
    if last_synced_at is None:
        return (LINK_NEVER, "never linked")
    open_local = (local_state in _LOCAL_OPEN)
    closed_local = (local_state == "recovered")
    # Inbound facts (only meaningful once a refresh has happened).
    if external_exists is False:
        return (LINK_MISSING, "external incident not found")
    if external_status in _EXT_CLOSED and open_local:
        return (LINK_DRIFTED, "external resolved but incident still open")
    if external_status in _EXT_OPEN and closed_local:
        return (LINK_DRIFTED, "incident recovered but external still open")
    # Age-based staleness (no successful sync within the bounded window).
    age = (now - last_synced_at).total_seconds()
    if age > max(1, stale_seconds):
        return (LINK_STALE, "no successful sync recently")
    if last_checked_at is not None:
        return (LINK_REFRESHED, "checked and aligned")
    return (LINK_LINKED, "linked")


# Severity ordering for the incident-level rollup (worst link wins). Detached is an
# intentional operator choice → lowest, never flagged as actionable drift.
_LINK_SEVERITY = {LINK_DETACHED: 0, LINK_NEVER: 0, LINK_LINKED: 1, LINK_REFRESHED: 1,
                  LINK_STALE: 2, LINK_DRIFTED: 3, LINK_MISSING: 4}
_ACTIONABLE = {LINK_DRIFTED, LINK_MISSING, LINK_STALE}


class IncidentSyncService:
    def __init__(self, session_factory: Callable[[], Any] = SessionLocal) -> None:
        self._session_factory = session_factory
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        try:
            ExternalIncidentTarget.__table__.create(bind=engine, checkfirst=True)
            IncidentSyncRecord.__table__.create(bind=engine, checkfirst=True)
            IncidentExternalLink.__table__.create(bind=engine, checkfirst=True)
            IncidentReconciliationEvent.__table__.create(bind=engine, checkfirst=True)
        except Exception:
            Base.metadata.create_all(bind=engine)
        from app.db.database import ensure_runtime_columns
        ensure_runtime_columns()  # additive: external_url / link reconciliation columns

    # ── targets (operator-only config) ────────────────────────────────────────

    def create_target(self, *, name: str, url: str, kind: str = "generic",
                      sync_actions: Optional[str] = None, secret: Optional[str] = None,
                      enabled: bool = True) -> Optional[dict[str, Any]]:
        name, url = (name or "").strip(), (url or "").strip()
        if not name or not url.lower().startswith(("http://", "https://")):
            return None
        if kind not in _KINDS:
            return None
        with self._session_factory() as session:
            row = ExternalIncidentTarget(
                id=uuid4().hex, name=name[:120], url=url[:500], kind=kind,
                enabled=bool(enabled), sync_actions=(sync_actions or None),
                secret=(secret or None))
            session.add(row)
            session.commit()
            return self._clean_target(row)

    def update_target(self, target_id: str, **changes: Any) -> Optional[dict[str, Any]]:
        allowed = {"name", "url", "kind", "enabled", "sync_actions", "secret"}
        with self._session_factory() as session:
            row = session.get(ExternalIncidentTarget, target_id)
            if row is None:
                return None
            for key, value in changes.items():
                if key not in allowed or value is None:
                    continue
                if key == "kind" and value not in _KINDS:
                    return None
                if key == "url" and not str(value).lower().startswith(("http://", "https://")):
                    return None
                setattr(row, key, value)
            session.commit()
            return self._clean_target(row)

    def delete_target(self, target_id: str) -> bool:
        with self._session_factory() as session:
            row = session.get(ExternalIncidentTarget, target_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    def list_targets(self) -> list[dict[str, Any]]:
        try:
            with self._session_factory() as session:
                rows = session.query(ExternalIncidentTarget).order_by(ExternalIncidentTarget.created_at.desc()).all()
                return [self._clean_target(r) for r in rows]
        except Exception:
            return []

    def get_target(self, target_id: str) -> Optional[dict[str, Any]]:
        with self._session_factory() as session:
            row = session.get(ExternalIncidentTarget, target_id)
            return self._clean_target(row) if row is not None else None

    # ── export (the incident workflow hook calls this on each transition) ──────

    def export(self, incident: dict[str, Any], action: str, *, actor: Optional[str] = None) -> int:
        """Mirror one incident transition to every enabled target that opted into
        this action. Creates a durable record per target and attempts it once.
        Best-effort and bounded — returns how many records were created. Never
        raises (incident workflow must never break on a sync hiccup)."""
        if not incident or not incident.get("id"):
            return 0
        try:
            with self._session_factory() as session:
                targets = session.query(ExternalIncidentTarget).filter(
                    ExternalIncidentTarget.enabled.is_(True)).all()
                created = []
                for target in targets:
                    allow = _csv_set(target.sync_actions)
                    if allow is not None and action not in allow:
                        continue
                    record = IncidentSyncRecord(
                        id=uuid4().hex, target_id=target.id,
                        incident_id=incident.get("id"), signal=incident.get("signal"),
                        action=action, actor=actor, state=incident.get("state"),
                        severity=incident.get("severity"), classification=incident.get("classification"),
                        subject=incident.get("subject"), assignee=incident.get("assignee"),
                        note=(incident.get("note") or None), status=STATUS_PENDING, attempts=0)
                    session.add(record)
                    created.append(record.id)
                session.commit()
            # Attempt each new record once, outside the create txn.
            for record_id in created:
                self._attempt(record_id)
            return len(created)
        except Exception:
            return 0

    def flush_pending(self, *, max_records: int = 50) -> dict[str, int]:
        """Retry pending records still under the attempt cap (sweep / recovery)."""
        counts = {STATUS_SYNCED: 0, STATUS_FAILED: 0, STATUS_PENDING: 0}
        try:
            with self._session_factory() as session:
                rows = (session.query(IncidentSyncRecord.id)
                        .filter(IncidentSyncRecord.status == STATUS_PENDING)
                        .order_by(IncidentSyncRecord.created_at.asc())
                        .limit(max_records).all())
                ids = [r[0] for r in rows]
            for record_id in ids:
                result = self._attempt(record_id)
                counts[result] = counts.get(result, 0) + 1
        except Exception:
            return counts
        return counts

    def _attempt(self, record_id: str) -> str:
        """One send attempt for a record. Returns the resulting status bucket."""
        with self._session_factory() as session:
            record = session.get(IncidentSyncRecord, record_id)
            if record is None or record.status == STATUS_SYNCED:
                return STATUS_SYNCED if record else STATUS_FAILED
            target = session.get(ExternalIncidentTarget, record.target_id)
            if target is None:
                record.status = STATUS_FAILED
                record.last_error = "target_deleted"
                session.commit()
                return STATUS_FAILED
            adapter = adapter_for(target.kind)
            payload = self._payload(record, target)
            body_json = json.dumps(adapter.shape(payload))
            record.attempts = (record.attempts or 0) + 1
            ok, code, err, ref, url = self._send(target.url, body_json, target.secret, adapter)
            if ok:
                record.status = STATUS_SYNCED
                record.last_error = None
                record.external_ref = ref
                record.external_url = url
                target.consecutive_failures = 0
                # Upsert the durable incident→external link from this success.
                self._upsert_link(session, record, ref, url)
            else:
                record.last_error = (err or (f"HTTP{code}" if code else "error"))[:200]
                target.consecutive_failures = (target.consecutive_failures or 0) + 1
                cap = max(1, int(getattr(settings, "incident_sync_max_attempts", 4)))
                record.status = STATUS_FAILED if record.attempts >= cap else STATUS_PENDING
            session.commit()
            return record.status

    @staticmethod
    def _upsert_link(session, record: IncidentSyncRecord, ref: Optional[str], url: Optional[str]) -> None:
        """Record/refresh the incident→external linkage on a successful sync. One row
        per (incident, target); a later success (incl. a redrive) updates it in place.
        Keeps the last good ref/url even if the latest ref is empty (don't lose a link)."""
        link = (session.query(IncidentExternalLink)
                .filter(IncidentExternalLink.incident_id == record.incident_id,
                        IncidentExternalLink.target_id == record.target_id).first())
        now = _now()
        if link is None:
            link = IncidentExternalLink(
                id=uuid4().hex, incident_id=record.incident_id, target_id=record.target_id,
                created_at=now)
            session.add(link)
        if ref:
            link.external_ref = ref
        if url:
            link.external_url = url
        link.last_action = record.action
        link.last_record_id = record.id
        link.last_synced_at = now

    # ── redrive (operator recovery of a terminal-failed sync) ─────────────────

    def redrive(self, record_id: str) -> dict[str, Any]:
        with self._session_factory() as session:
            record = session.get(IncidentSyncRecord, record_id)
            if record is None:
                return {"ok": False, "message": "Sync record not found."}
            if record.status != STATUS_FAILED:
                return {"ok": False, "message": "Only a terminally-failed sync can be redriven."}
            children = (session.query(IncidentSyncRecord)
                        .filter(IncidentSyncRecord.redrive_of == record_id).all())
            open_child = next((c for c in children if c.status in (STATUS_PENDING, STATUS_SYNCED)), None)
            if open_child is not None:
                return {"ok": True, "record": self._clean_record(open_child),
                        "message": "A redrive is already in flight or succeeded."}
            if len(children) >= max(1, int(getattr(settings, "incident_sync_max_redrives", 3))):
                return {"ok": False, "message": "Redrive limit reached for this sync."}
            child = IncidentSyncRecord(
                id=uuid4().hex, target_id=record.target_id, incident_id=record.incident_id,
                signal=record.signal, action=record.action, actor=record.actor,
                state=record.state, severity=record.severity, classification=record.classification,
                subject=record.subject, assignee=record.assignee, note=record.note,
                status=STATUS_PENDING, attempts=0, redrive_of=record_id)
            session.add(child)
            session.commit()
            child_id = child.id
        self._attempt(child_id)
        return {"ok": True, "record": self.get_record(child_id), "message": "Redrive attempted."}

    # ── reads (operator-only; curated) ────────────────────────────────────────

    def list_records(self, *, status: Optional[str] = None, incident_id: Optional[str] = None,
                     limit: int = 50) -> list[dict[str, Any]]:
        try:
            with self._session_factory() as session:
                query = session.query(IncidentSyncRecord)
                if status:
                    query = query.filter(IncidentSyncRecord.status == status)
                if incident_id:
                    query = query.filter(IncidentSyncRecord.incident_id == incident_id)
                rows = query.order_by(IncidentSyncRecord.created_at.desc()).limit(min(limit, 200)).all()
                names = self._target_names(session)
                return [self._clean_record(r, names) for r in rows]
        except Exception:
            return []

    def get_record(self, record_id: str) -> Optional[dict[str, Any]]:
        with self._session_factory() as session:
            row = session.get(IncidentSyncRecord, record_id)
            if row is None:
                return None
            return self._clean_record(row, self._target_names(session))

    # ── transport (single injectable primitive; overridden in tests) ──────────

    def _send(self, url: str, body_json: str, secret: Optional[str],
              adapter=None) -> tuple[bool, Optional[int], Optional[str], Optional[str], Optional[str]]:
        """POST the (already adapter-shaped) signed snapshot. Returns
        (ok, status_code, error_class, external_ref, external_url). The adapter parses
        ref/url from the response. Injectable/overridable in tests. Never raises."""
        adapter = adapter or _GENERIC
        try:
            import requests

            headers = {"Content-Type": "application/json", "User-Agent": "AIRA-X-IncidentSync/1"}
            body = body_json.encode("utf-8")
            if secret:
                sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
                headers["X-AIRA-Signature"] = f"sha256={sig}"
            resp = requests.post(url, data=body, headers=headers,
                                 timeout=getattr(settings, "webhook_timeout_seconds", 5.0))
            ok = 200 <= resp.status_code < 300
            resp_headers, resp_body = {}, None
            try:
                resp_headers = dict(resp.headers)
            except Exception:
                resp_headers = {}
            try:
                resp_body = resp.json()
            except Exception:
                resp_body = None
            ref, link = adapter.parse(resp.status_code, resp_headers, resp_body)
            return (ok, resp.status_code, None if ok else f"HTTP{resp.status_code}", ref, link)
        except Exception as error:
            return (False, None, type(error).__name__, None, None)

    @staticmethod
    def _payload(record: IncidentSyncRecord, target: ExternalIncidentTarget) -> dict[str, Any]:
        """The curated, stable outbound payload — incident identity + snapshot."""
        return {
            "type": "incident.transition",
            "target_kind": target.kind,
            "action": record.action,
            "actor": record.actor,
            "incident": {
                "id": record.incident_id,
                "signal": record.signal,
                "state": record.state,
                "severity": record.severity,
                "classification": record.classification,
                "subject": record.subject,
                "assignee": record.assignee,
                "note": record.note,
            },
            "at": (record.created_at.isoformat() if record.created_at else None),
        }

    @staticmethod
    def _target_names(session) -> dict[str, dict[str, Any]]:
        return {t.id: {"name": t.name, "kind": t.kind}
                for t in session.query(ExternalIncidentTarget).all()}

    @staticmethod
    def _clean_target(row: ExternalIncidentTarget) -> dict[str, Any]:
        return {
            "id": row.id,
            "name": row.name,
            "kind": row.kind,
            "url": row.url,
            "enabled": bool(row.enabled),
            "sync_actions": row.sync_actions,
            "has_secret": bool(row.secret),   # presence only — never the value
            "consecutive_failures": row.consecutive_failures or 0,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @staticmethod
    def _clean_record(row: IncidentSyncRecord, target_names: Optional[dict] = None) -> dict[str, Any]:
        target = (target_names or {}).get(row.target_id, {})
        return {
            "id": row.id,
            "target_id": row.target_id,
            "target_name": target.get("name"),
            "target_kind": target.get("kind"),
            "incident_id": row.incident_id,
            "signal": row.signal,
            "action": row.action,
            "actor": row.actor,
            "state": row.state,
            "severity": row.severity,
            "classification": row.classification,
            "subject": row.subject,
            "assignee": row.assignee,
            "note": row.note,
            "status": row.status,
            "attempts": row.attempts or 0,
            "last_error": row.last_error,
            "external_ref": row.external_ref,
            "external_url": row.external_url,
            "redrive_of": row.redrive_of,
            "is_redrive": row.redrive_of is not None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    def _clean_link(self, row: IncidentExternalLink, target_names: Optional[dict] = None,
                    *, local_state: Optional[str] = None, now: Optional[datetime] = None) -> dict[str, Any]:
        target = (target_names or {}).get(row.target_id, {})
        now = now or _now()
        stale_seconds = max(1, int(getattr(settings, "incident_link_stale_seconds", 86400)))
        caps = adapter_capabilities(target.get("kind"))
        supports_refresh = caps["refresh"]
        detached = row.detached_at is not None
        status, reason = classify_link_status(
            local_state=local_state, last_synced_at=row.last_synced_at,
            last_checked_at=row.last_checked_at, external_exists=row.external_exists,
            external_status=row.external_status, now=now, stale_seconds=stale_seconds,
            detached=detached)
        return {
            "target_id": row.target_id,
            "target_name": target.get("name"),
            "target_kind": target.get("kind"),
            "external_ref": row.external_ref,
            "external_url": row.external_url,
            "last_action": row.last_action,
            "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
            "last_checked_at": row.last_checked_at.isoformat() if row.last_checked_at else None,
            "external_status": row.external_status,
            "external_exists": row.external_exists,
            "detached": detached,
            "detached_at": row.detached_at.isoformat() if row.detached_at else None,
            "capabilities": caps,
            "refresh_supported": supports_refresh,
            "link_status": status,
            "reason": reason,
        }

    # ── per-incident sync status & linkage (operator-only; curated) ───────────

    def incident_sync_status(self, incident_id: str, *, incident_state: Optional[str] = None) -> dict[str, Any]:
        """Curated sync-health + external linkage for one incident: durable links,
        recent attempts, and an honest summary (linked? behind? drifted? stale?
        missing? recovered by redrive?). Outbound stays primary — inbound facts are
        only what the last bounded refresh observed, never silent overwrites."""
        empty = {"linked": False, "links": [], "records": [], "reconciliation": [],
                 "summary": {"linked": False, "synced": False, "behind": False,
                             "last_synced_at": None, "last_failed_at": None, "last_error": None,
                             "recovered_after_redrive": False, "link_status": LINK_NEVER,
                             "reason": "never linked", "refresh_supported": False,
                             "last_checked_at": None,
                             "actions": {"can_refresh": False, "can_redrive": False,
                                         "can_detach": False, "can_relink": False,
                                         "can_apply": False, "apply_action": None,
                                         "can_push": False}}}
        try:
            local_state = incident_state if incident_state is not None else self._local_state(incident_id)
            now = _now()
            with self._session_factory() as session:
                names = self._target_names(session)
                link_rows = (session.query(IncidentExternalLink)
                             .filter(IncidentExternalLink.incident_id == incident_id)
                             .order_by(IncidentExternalLink.last_synced_at.desc()).all())
                rec_rows = (session.query(IncidentSyncRecord)
                            .filter(IncidentSyncRecord.incident_id == incident_id)
                            .order_by(IncidentSyncRecord.created_at.desc()).limit(50).all())
                evt_rows = (session.query(IncidentReconciliationEvent)
                            .filter(IncidentReconciliationEvent.incident_id == incident_id)
                            .order_by(IncidentReconciliationEvent.id.desc()).limit(10).all())
            links = [self._clean_link(r, names, local_state=local_state, now=now) for r in link_rows]
            records = [self._clean_record(r, names) for r in rec_rows]
            reconciliation = [self._clean_event(e) for e in evt_rows]
            synced = [r for r in records if r["status"] == STATUS_SYNCED]
            failed = [r for r in records if r["status"] == STATUS_FAILED]
            latest = records[0] if records else None
            active_links = [link for link in links if not link["detached"]]
            # Incident-level rollup: the worst (most actionable) active link wins.
            overall, reason = LINK_NEVER, "never linked"
            if active_links:
                worst = max(active_links, key=lambda link: _LINK_SEVERITY.get(link["link_status"], 0))
                overall, reason = worst["link_status"], worst["reason"]
            elif links:
                overall, reason = LINK_DETACHED, "intentionally detached"
            # What apply-from-external (if any) the observed disagreement supports.
            # Bounded + honest: only when external state was actually observed.
            apply_action = None
            if overall == LINK_MISSING:
                apply_action = "accept_missing"      # → detach the dead link
            elif overall == LINK_DRIFTED:
                worst_link = next((link for link in active_links if link["link_status"] == LINK_DRIFTED), None)
                if worst_link and worst_link["external_status"] in _EXT_CLOSED and local_state in _LOCAL_OPEN:
                    apply_action = "accept_resolved"  # → recover the local incident
            # Bounded, honest action availability (what the operator can actually do).
            actions = {
                "can_refresh": any(link["refresh_supported"] and not link["detached"] for link in links),
                "can_redrive": bool(failed and (latest is None or latest["status"] != STATUS_SYNCED)),
                "can_detach": any(not link["detached"] for link in links),
                "can_relink": any(link["refresh_supported"] for link in links),
                "can_apply": apply_action is not None,
                "apply_action": apply_action,
                "can_push": any(link["capabilities"]["push_outward"] and not link["detached"] for link in links),
            }
            summary = {
                "linked": bool(active_links),
                "synced": bool(synced),
                "behind": bool(latest and latest["status"] != STATUS_SYNCED),
                "last_synced_at": synced[0]["created_at"] if synced else None,
                "last_failed_at": failed[0]["created_at"] if failed else None,
                "last_error": failed[0]["last_error"] if failed else None,
                "recovered_after_redrive": bool(latest and latest["status"] == STATUS_SYNCED and latest["is_redrive"]),
                "link_status": overall,
                "reason": reason,
                "refresh_supported": any(link["refresh_supported"] for link in active_links),
                "last_checked_at": max([link["last_checked_at"] for link in links if link["last_checked_at"]], default=None),
                "actions": actions,
            }
            return {"linked": bool(active_links), "links": links, "records": records,
                    "reconciliation": reconciliation, "summary": summary}
        except Exception:
            return empty

    @staticmethod
    def _clean_event(row: IncidentReconciliationEvent) -> dict[str, Any]:
        return {
            "action": row.action,
            "outcome": row.outcome,
            "actor": row.actor,
            "detail": row.detail,
            "at": row.created_at.isoformat() if row.created_at else None,
        }

    @staticmethod
    def _local_state(incident_id: str) -> Optional[str]:
        """Read the current local incident state (guarded lazy import — sync must not
        hard-depend on the incident service)."""
        try:
            from app.incidents import incident_service
            inc = incident_service.get(incident_id)
            return inc.get("state") if inc else None
        except Exception:
            return None

    # ── bounded inbound reconciliation (refresh / drift) ──────────────────────

    def refresh(self, incident_id: str, *, incident_state: Optional[str] = None,
                actor: Optional[str] = None) -> Optional[dict[str, Any]]:
        """Bounded inbound recheck of each linked external incident (only for
        adapters that support it). Updates the link's last-observed external
        status/existence/url — it NEVER mutates the local incident. Returns the
        refreshed sync status, or None if the incident has no links to check."""
        local_state = incident_state if incident_state is not None else self._local_state(incident_id)
        try:
            with self._session_factory() as session:
                links = (session.query(IncidentExternalLink)
                         .filter(IncidentExternalLink.incident_id == incident_id,
                                 IncidentExternalLink.detached_at.is_(None)).all())
                if not links:
                    return None
                now = _now()
                for link in links:
                    target = session.get(ExternalIncidentTarget, link.target_id)
                    if target is None:
                        continue
                    adapter = adapter_for(target.kind)
                    if not getattr(adapter, "supports_refresh", False):
                        self._log_reconcile(session, incident_id, link.target_id, "refresh", "unsupported",
                                            actor=actor, detail="adapter is outbound-only")
                        continue  # outbound-only adapter — honestly skipped
                    ok, exists, status, url, err = self._fetch(target.url, link.external_ref, target.secret, adapter)
                    link.last_checked_at = now
                    if ok or exists is False:
                        link.external_exists = exists
                        if status:
                            link.external_status = status
                        if url:
                            link.external_url = url
                        outcome = "missing" if exists is False else "ok"
                        self._log_reconcile(session, incident_id, link.target_id, "refresh", outcome,
                                            actor=actor, detail=(status or ("not found" if exists is False else None)))
                    else:
                        self._log_reconcile(session, incident_id, link.target_id, "refresh", "failed",
                                            actor=actor, detail=err)
                session.commit()
        except Exception:
            return self.incident_sync_status(incident_id, incident_state=local_state)
        return self.incident_sync_status(incident_id, incident_state=local_state)

    def _fetch(self, target_url: str, ref: Optional[str], secret: Optional[str],
               adapter=None) -> tuple[bool, Optional[bool], Optional[str], Optional[str], Optional[str]]:
        """Bounded inbound GET of an external incident's current state. Returns
        (ok, external_exists, normalized_status, external_url, error_class). The
        adapter parses the response. Injectable/overridable in tests. Never raises."""
        adapter = adapter or _GENERIC
        try:
            import requests

            headers = {"Accept": "application/json", "User-Agent": "AIRA-X-IncidentSync/1"}
            params = {"ref": ref} if ref else {}
            resp = requests.get(target_url, params=params, headers=headers,
                                timeout=getattr(settings, "webhook_timeout_seconds", 5.0))
            ok = 200 <= resp.status_code < 300
            resp_headers, resp_body = {}, None
            try:
                resp_headers = dict(resp.headers)
            except Exception:
                resp_headers = {}
            try:
                resp_body = resp.json()
            except Exception:
                resp_body = None
            exists, status, url = adapter.parse_status(resp.status_code, resp_headers, resp_body)
            return (ok, exists, status, url, None if ok else f"HTTP{resp.status_code}")
        except Exception as error:
            return (False, None, None, None, type(error).__name__)

    def drifted(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Operator triage: active (non-detached) links whose reconciliation verdict
        is actionable (drifted / missing_external / stale). Curated, operator-only."""
        out: list[dict[str, Any]] = []
        try:
            now = _now()
            with self._session_factory() as session:
                names = self._target_names(session)
                rows = (session.query(IncidentExternalLink)
                        .filter(IncidentExternalLink.detached_at.is_(None))
                        .order_by(IncidentExternalLink.last_synced_at.desc())
                        .limit(min(limit, 200)).all())
                resolved = [(r, self._local_state(r.incident_id)) for r in rows]
            for row, local_state in resolved:
                clean = self._clean_link(row, names, local_state=local_state, now=now)
                if clean["link_status"] in _ACTIONABLE:
                    clean["incident_id"] = row.incident_id
                    out.append(clean)
        except Exception:
            return []
        return out

    # ── drift resolution / link repair (operator-only; never touches local state) ─

    def detach(self, incident_id: str, target_id: str, *, actor: Optional[str] = None,
               incident_state: Optional[str] = None) -> Optional[dict[str, Any]]:
        """Intentionally detach an incident's external link (e.g. the external issue
        is gone or wrong). The link row is preserved for lineage but excluded from
        drift/reconciliation. Does NOT touch local incident state."""
        try:
            with self._session_factory() as session:
                link = (session.query(IncidentExternalLink)
                        .filter(IncidentExternalLink.incident_id == incident_id,
                                IncidentExternalLink.target_id == target_id).first())
                if link is None:
                    return None
                if link.detached_at is None:
                    link.detached_at = _now()
                self._log_reconcile(session, incident_id, target_id, "detach", "ok",
                                    actor=actor, detail="link detached")
                session.commit()
        except Exception:
            return None
        return self.incident_sync_status(incident_id, incident_state=incident_state)

    def relink(self, incident_id: str, target_id: str, external_ref: str, *,
               external_url: Optional[str] = None, actor: Optional[str] = None,
               incident_state: Optional[str] = None) -> dict[str, Any]:
        """Repair/establish an external link to a known ref, VALIDATED through the
        adapter (a bounded inbound check that it exists). Refused honestly when the
        adapter is outbound-only or the external incident can't be verified. Never
        trusts an arbitrary link blindly; never mutates local incident state."""
        external_ref = (external_ref or "").strip()[:120]
        if not external_ref:
            return {"ok": False, "message": "An external reference is required to relink."}
        try:
            with self._session_factory() as session:
                target = session.get(ExternalIncidentTarget, target_id)
                if target is None:
                    return {"ok": False, "message": "Target not found."}
                adapter = adapter_for(target.kind)
                if not getattr(adapter, "supports_refresh", False):
                    self._log_reconcile(session, incident_id, target_id, "relink", "unsupported",
                                        actor=actor, detail="adapter cannot verify links")
                    session.commit()
                    return {"ok": False, "message": "This target's adapter is outbound-only and cannot verify a relink."}
                ok, exists, status, url, err = self._fetch(target.url, external_ref, target.secret, adapter)
                if not ok or exists is False:
                    self._log_reconcile(session, incident_id, target_id, "relink",
                                        "missing" if exists is False else "failed",
                                        actor=actor, detail=(err or "external incident not found"))
                    session.commit()
                    return {"ok": False, "message": "Could not verify that external reference; relink refused."}
                now = _now()
                link = (session.query(IncidentExternalLink)
                        .filter(IncidentExternalLink.incident_id == incident_id,
                                IncidentExternalLink.target_id == target_id).first())
                if link is None:
                    link = IncidentExternalLink(id=uuid4().hex, incident_id=incident_id,
                                                target_id=target_id, created_at=now)
                    session.add(link)
                link.external_ref = external_ref
                link.external_url = external_url or url or link.external_url
                link.external_status = status
                link.external_exists = True
                link.last_checked_at = now
                link.last_synced_at = link.last_synced_at or now  # operator-established linkage time
                link.last_action = "relink"
                link.detached_at = None  # a verified relink reattaches
                self._log_reconcile(session, incident_id, target_id, "relink", "ok",
                                    actor=actor, detail=f"→ {external_ref}")
                session.commit()
        except Exception:
            return {"ok": False, "message": "Relink failed."}
        return {"ok": True, "status": self.incident_sync_status(incident_id, incident_state=incident_state),
                "message": "Relinked and verified."}

    def redrive_incident_latest(self, incident_id: str) -> dict[str, Any]:
        """Redrive the most recent terminally-failed sync for an incident, straight
        from its context (a convenience over per-record redrive)."""
        try:
            with self._session_factory() as session:
                latest = (session.query(IncidentSyncRecord)
                          .filter(IncidentSyncRecord.incident_id == incident_id)
                          .order_by(IncidentSyncRecord.created_at.desc()).first())
                # Already landed (e.g. a prior redrive succeeded) → nothing to do.
                if latest is not None and latest.status == STATUS_SYNCED:
                    return {"ok": False, "message": "External sync is already up to date."}
                latest_failed = (session.query(IncidentSyncRecord)
                                 .filter(IncidentSyncRecord.incident_id == incident_id,
                                         IncidentSyncRecord.status == STATUS_FAILED)
                                 .order_by(IncidentSyncRecord.created_at.desc()).first())
                record_id = latest_failed.id if latest_failed else None
            if record_id is None:
                return {"ok": False, "message": "No failed sync to redrive for this incident."}
            result = self.redrive(record_id)
            with self._session_factory() as session:
                self._log_reconcile(session, incident_id, None, "redrive",
                                    "ok" if result.get("ok") else "failed",
                                    detail=result.get("message"))
                session.commit()
            return result
        except Exception:
            return {"ok": False, "message": "Redrive failed."}

    # ── explicit local-vs-external resolution (operator-driven only) ──────────

    def apply_from_external(self, incident_id: str, apply_action: str, *,
                            actor: Optional[str] = None) -> dict[str, Any]:
        """EXPLICIT, operator-chosen application of observed external state to the
        LOCAL side. This is the only path that may change local incident state from
        an external observation — refresh/reconcile never do. Bounded to the cases the
        observed disagreement actually supports; refused otherwise.

        - `accept_resolved`: external reports resolved/closed while local is open →
          recover the local incident (an explicit operator recovery, on the trail).
        - `accept_missing`: external is gone → detach the dead link.
        """
        if apply_action not in ("accept_resolved", "accept_missing"):
            return {"ok": False, "message": "Unknown apply action."}
        status = self.incident_sync_status(incident_id)
        if not status["links"]:
            return {"ok": False, "message": "Incident has no external link."}
        offered = status["summary"]["actions"].get("apply_action")
        if offered != apply_action:
            return {"ok": False, "message": "That external state is not currently applicable."}
        active = [link for link in status["links"] if not link["detached"]]
        if apply_action == "accept_missing":
            link = next((l for l in active if l["link_status"] == LINK_MISSING), active[0] if active else None)
            if link is None:
                return {"ok": False, "message": "No external link to detach."}
            self.detach(incident_id, link["target_id"], actor=actor)
            self._record_apply(incident_id, link["target_id"], "accept_missing", "ok",
                               actor=actor, detail="detached missing external link (linkage only)")
            return {"ok": True, "changed_local": False,
                    "status": self.incident_sync_status(incident_id),
                    "message": "Detached the missing external link."}
        # accept_resolved → explicit LOCAL recovery.
        link = next((l for l in active if l["link_status"] == LINK_DRIFTED), None)
        target_id = link["target_id"] if link else None
        applied = None
        try:
            from app.incidents import incident_service
            applied = incident_service.mark_recovered(
                incident_id, actor=actor, reason="applied external resolution")
        except Exception:
            applied = None
        outcome = "ok" if applied else "failed"
        self._record_apply(incident_id, target_id, "accept_resolved", outcome, actor=actor,
                           detail="local incident recovered from external resolved")
        if not applied:
            return {"ok": False, "message": "Could not apply external resolution."}
        return {"ok": True, "changed_local": True,
                "status": self.incident_sync_status(incident_id),
                "message": "Applied external resolution — local incident recovered."}

    def push_outward(self, incident_id: str, *, target_id: Optional[str] = None,
                     actor: Optional[str] = None, incident: Optional[dict] = None) -> dict[str, Any]:
        """EXPLICITLY re-send the CURRENT local incident state outward to push-capable
        targets (e.g. push a local `recovered` so the external incident resolves). The
        action mirrors the local state honestly; targets whose adapter can't push are
        skipped. Never changes local state."""
        snapshot = incident
        if snapshot is None:
            try:
                from app.incidents import incident_service
                snapshot = incident_service.get(incident_id)
            except Exception:
                snapshot = None
        if not snapshot:
            return {"ok": False, "message": "Incident not found."}
        action = "recovered" if snapshot.get("state") == "recovered" else "opened"
        created: list[str] = []
        pushed_targets = 0
        try:
            with self._session_factory() as session:
                query = session.query(ExternalIncidentTarget).filter(ExternalIncidentTarget.enabled.is_(True))
                if target_id:
                    query = query.filter(ExternalIncidentTarget.id == target_id)
                targets = query.all()
                if not targets:
                    return {"ok": False, "message": "No matching enabled target."}
                for target in targets:
                    if not getattr(adapter_for(target.kind), "supports_push_outward", False):
                        self._log_reconcile(session, incident_id, target.id, "push", "unsupported",
                                            actor=actor, detail="adapter cannot push outward")
                        continue
                    record = IncidentSyncRecord(
                        id=uuid4().hex, target_id=target.id, incident_id=incident_id,
                        signal=snapshot.get("signal"), action=action, actor=actor,
                        state=snapshot.get("state"), severity=snapshot.get("severity"),
                        classification=snapshot.get("classification"), subject=snapshot.get("subject"),
                        assignee=snapshot.get("assignee"), note=(snapshot.get("note") or None),
                        status=STATUS_PENDING, attempts=0)
                    session.add(record)
                    created.append(record.id)
                    pushed_targets += 1
                session.commit()
            for record_id in created:
                self._attempt(record_id)
            with self._session_factory() as session:
                self._log_reconcile(session, incident_id, target_id, "push",
                                    "ok" if pushed_targets else "unsupported", actor=actor,
                                    detail=f"pushed local '{action}' to {pushed_targets} target(s)")
                session.commit()
        except Exception:
            return {"ok": False, "message": "Push failed."}
        if not pushed_targets:
            return {"ok": False, "message": "No push-capable target for this incident."}
        return {"ok": True, "changed_local": False,
                "status": self.incident_sync_status(incident_id), "message": "Pushed local state outward."}

    def _record_apply(self, incident_id: str, target_id: Optional[str], action: str, outcome: str,
                      *, actor: Optional[str], detail: Optional[str]) -> None:
        try:
            with self._session_factory() as session:
                self._log_reconcile(session, incident_id, target_id, f"apply:{action}", outcome,
                                    actor=actor, detail=detail)
                session.commit()
        except Exception:
            pass

    def reconcile(self, *, max_incidents: Optional[int] = None, actor: Optional[str] = None) -> dict[str, int]:
        """Bounded scheduled reconciliation: recheck the active, refresh-capable links
        that most need it (stale / never-checked / already drifted), capped per sweep
        so external systems are never spammed. Never mutates local incident state."""
        cap = max_incidents if max_incidents is not None else int(getattr(settings, "incident_reconcile_max_per_sweep", 25))
        cap = max(1, int(cap))
        stale_seconds = max(1, int(getattr(settings, "incident_link_stale_seconds", 86400)))
        counts = {"checked": 0, "ok": 0, "missing": 0, "failed": 0, "skipped": 0}
        try:
            now = _now()
            with self._session_factory() as session:
                names = self._target_names(session)
                # NULL last_checked_at (never reconciled) sorts first under SQLite ASC,
                # so the longest-unchecked links are prioritized.
                rows = (session.query(IncidentExternalLink)
                        .filter(IncidentExternalLink.detached_at.is_(None))
                        .order_by(IncidentExternalLink.last_checked_at.asc())
                        .limit(200).all())
                candidates = []
                for link in rows:
                    kind = names.get(link.target_id, {}).get("kind")
                    if not getattr(adapter_for(kind), "supports_refresh", False):
                        continue
                    needs = (link.last_checked_at is None
                             or (link.last_synced_at is not None and (now - link.last_synced_at).total_seconds() > stale_seconds)
                             or (link.last_checked_at is not None and (now - link.last_checked_at).total_seconds() > stale_seconds))
                    if needs:
                        candidates.append(link.incident_id)
                    if len(candidates) >= cap:
                        break
            for incident_id in candidates:
                status = self.refresh(incident_id, actor=actor)
                if status is None:
                    counts["skipped"] += 1
                    continue
                counts["checked"] += 1
                verdict = status["summary"]["link_status"]
                if verdict == LINK_MISSING:
                    counts["missing"] += 1
                elif verdict in (LINK_REFRESHED, LINK_LINKED, LINK_DRIFTED):
                    counts["ok"] += 1
        except Exception:
            return counts
        return counts

    def reconciliation_events(self, incident_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        try:
            with self._session_factory() as session:
                rows = (session.query(IncidentReconciliationEvent)
                        .filter(IncidentReconciliationEvent.incident_id == incident_id)
                        .order_by(IncidentReconciliationEvent.id.desc()).limit(min(limit, 100)).all())
                return [self._clean_event(r) for r in rows]
        except Exception:
            return []

    @staticmethod
    def _log_reconcile(session, incident_id: str, target_id: Optional[str], action: str,
                       outcome: str, *, actor: Optional[str] = None, detail: Optional[str] = None) -> None:
        actor = (actor or "").strip()[:80] or None
        session.add(IncidentReconciliationEvent(
            incident_id=incident_id, target_id=target_id, action=action, outcome=outcome,
            actor=actor, detail=(detail[:200] if detail else None), created_at=_now()))

    def target_health(self, target_id: str) -> Optional[dict[str, Any]]:
        """Curated health for one target: recent attempt mix + last success/failure."""
        with self._session_factory() as session:
            target = session.get(ExternalIncidentTarget, target_id)
            if target is None:
                return None
            rows = (session.query(IncidentSyncRecord)
                    .filter(IncidentSyncRecord.target_id == target_id)
                    .order_by(IncidentSyncRecord.created_at.desc()).limit(100).all())
            synced = [r for r in rows if r.status == STATUS_SYNCED]
            failed = [r for r in rows if r.status == STATUS_FAILED]
            pending = [r for r in rows if r.status == STATUS_PENDING]
            healthy = (target.consecutive_failures or 0) == 0
            clean = self._clean_target(target)
            clean.update({
                "health": "healthy" if healthy else "degraded",
                "recent": {"synced": len(synced), "failed": len(failed), "pending": len(pending)},
                "last_synced_at": (synced[0].created_at.isoformat() if synced and synced[0].created_at else None),
                "last_failed_at": (failed[0].created_at.isoformat() if failed and failed[0].created_at else None),
                "last_error": (failed[0].last_error if failed else None),
            })
            return clean

    def clear_all(self) -> None:
        try:
            with self._session_factory() as session:
                session.query(IncidentReconciliationEvent).delete()
                session.query(IncidentExternalLink).delete()
                session.query(IncidentSyncRecord).delete()
                session.query(ExternalIncidentTarget).delete()
                session.commit()
        except Exception:
            pass


incident_sync_service = IncidentSyncService()
