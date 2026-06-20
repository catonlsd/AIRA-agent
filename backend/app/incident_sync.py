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
from app.db.models import ExternalIncidentTarget, IncidentSyncRecord

STATUS_PENDING = "pending"
STATUS_SYNCED = "synced"
STATUS_FAILED = "failed"

_KINDS = {"generic", "pagerduty", "jira", "opsgenie"}  # adapter-ready labels (transport is uniform today)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _csv_set(value: Optional[str]) -> Optional[set[str]]:
    if not value:
        return None
    items = {part.strip() for part in value.split(",") if part.strip()}
    return items or None


class IncidentSyncService:
    def __init__(self, session_factory: Callable[[], Any] = SessionLocal) -> None:
        self._session_factory = session_factory
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        try:
            ExternalIncidentTarget.__table__.create(bind=engine, checkfirst=True)
            IncidentSyncRecord.__table__.create(bind=engine, checkfirst=True)
        except Exception:
            Base.metadata.create_all(bind=engine)

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
            payload = self._payload(record, target)
            record.attempts = (record.attempts or 0) + 1
            ok, code, err, ref = self._send(target.url, json.dumps(payload), target.secret)
            if ok:
                record.status = STATUS_SYNCED
                record.last_error = None
                record.external_ref = ref
                target.consecutive_failures = 0
            else:
                record.last_error = (err or (f"HTTP{code}" if code else "error"))[:200]
                target.consecutive_failures = (target.consecutive_failures or 0) + 1
                cap = max(1, int(getattr(settings, "incident_sync_max_attempts", 4)))
                record.status = STATUS_FAILED if record.attempts >= cap else STATUS_PENDING
            session.commit()
            return record.status

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

    def _send(self, url: str, body_json: str, secret: Optional[str]) -> tuple[bool, Optional[int], Optional[str], Optional[str]]:
        """POST the signed incident snapshot. Returns (ok, status_code, error_class,
        external_ref). Never raises."""
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
            ref = None
            try:
                ref = (resp.headers.get("X-Incident-Ref") or resp.headers.get("Location"))
            except Exception:
                ref = None
            return (ok, resp.status_code, None if ok else f"HTTP{resp.status_code}", (ref or None))
        except Exception as error:
            return (False, None, type(error).__name__, None)

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
            "redrive_of": row.redrive_of,
            "is_redrive": row.redrive_of is not None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    def clear_all(self) -> None:
        try:
            with self._session_factory() as session:
                session.query(IncidentSyncRecord).delete()
                session.query(ExternalIncidentTarget).delete()
                session.commit()
        except Exception:
            pass


incident_sync_service = IncidentSyncService()
