# File: backend/app/webhooks.py
"""
External delivery — webhook destinations + durable, bounded-retry delivery.

The observability layer made operational signals queryable; the policy layer
classified alert-worthy conditions. This is the seam that *delivers* them to
external systems (dashboards, Slack/PagerDuty bridges, alert routers) instead of
forcing them to poll forever.

Design notes that matter:
  * **Operator-only.** Destinations and deliveries are configured/inspected via the
    gated `/operator/*` routes; nothing here touches the user surface, and the
    signing `secret` is NEVER returned by a read API.
  * **Durable + bounded retry, separate from execution.** A `WebhookDelivery` row
    runs `pending -> delivered | failed`; `attempts` is the DELIVERY retry counter
    bounded by `webhook_max_attempts` — deliberately distinct from job retry /
    replay. Deliveries are NOT execution jobs (routing them through the queue would
    re-emit observability events and loop), so a failing webhook can never break a
    job.
  * **Idempotent alert routing.** A `dedup_key` keeps a stuck/failed job from
    delivering on every sweep — one open delivery per (destination, signal).
  * **Curated payloads.** The body is the already-clean observability event / alert
    dict (scope type+id, failure class, lineage, severity, a stable source id) —
    never prompts, tool payloads, traces, or secrets. Signed with HMAC-SHA256 in
    `X-AIRA-Signature` so receivers can verify authenticity.

The HTTP send is injectable (`_send`) so it is fully testable without a network,
and `deliver_pending` is the worker step — bounded, honest, dead-letter-ready.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Callable, Optional
from uuid import uuid4

from app.core.config import settings
from app.db.database import Base, SessionLocal, engine
from app.db.models import WebhookDelivery, WebhookDestination

SUB_EVENTS = "events"
SUB_ALERTS = "alerts"
SUB_BOTH = "both"
_SUBSCRIPTIONS = {SUB_EVENTS, SUB_ALERTS, SUB_BOTH}
_SEVERITIES = {"warning", "critical"}
_SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}

STATUS_PENDING = "pending"
STATUS_DELIVERED = "delivered"
STATUS_FAILED = "failed"

# Dead-letter classification for a terminal-failed delivery (derived from lineage).
DL_REDRIVE_CANDIDATE = "redrive_candidate"  # failed, never redriven, under the cap
DL_REDRIVEN = "redriven"                    # a redrive attempt is in flight
DL_RESOLVED = "resolved"                    # a redrive attempt succeeded
DL_EXHAUSTED = "exhausted"                  # redrive cap reached, none succeeded

KIND_WEBHOOK = "webhook"
KIND_SLACK = "slack"
_KINDS = {KIND_WEBHOOK, KIND_SLACK}


# ── destination adapters ──────────────────────────────────────────────────────
#
# An adapter owns ONLY payload shaping + which (url, secret) to use. The actual
# HTTP transport stays a single injectable primitive (`DeliveryService._send`), so
# the delivery state machine, retry, redrive, and tests are adapter-agnostic and
# later adapters (PagerDuty, email, a queue) are a one-class addition.

class WebhookAdapter:
    """The generic outbound HTTP adapter: POST the curated payload as-is, signed."""

    kind = KIND_WEBHOOK

    def prepare(self, dest, payload: dict) -> tuple[str, str, Optional[str]]:
        return dest.url, json.dumps(payload, default=str), dest.secret


class SlackAdapter:
    """A minimal Slack-compatible adapter: reshape the curated payload into Slack's
    `{"text": ...}` shape. Proves the abstraction without webhook-specific signing
    (Slack authenticates via the secret URL)."""

    kind = KIND_SLACK

    def prepare(self, dest, payload: dict) -> tuple[str, str, Optional[str]]:
        label = payload.get("classification") or payload.get("event_type") or "signal"
        sev = payload.get("severity")
        ref = payload.get("job_id") or payload.get("source_id") or payload.get("id") or ""
        text = f"[AIRA-X] {label}" + (f" ({sev})" if sev else "") + (f" — {ref}" if ref else "")
        return dest.url, json.dumps({"text": text, "aira": payload}, default=str), None


class _DestView:
    """A detached snapshot of a destination's send-relevant fields, so an adapter
    can shape a payload after the DB session has closed."""

    def __init__(self, row) -> None:
        self.id = row.id
        self.url = row.url
        self.secret = row.secret
        self.kind = row.kind


_ADAPTERS = {a.kind: a for a in (WebhookAdapter(), SlackAdapter())}


def adapter_for(kind: Optional[str]):
    """Resolve the adapter for a destination kind; unknown kinds fall back to the
    generic webhook adapter so a misconfigured destination still delivers safely."""
    return _ADAPTERS.get(kind or KIND_WEBHOOK, _ADAPTERS[KIND_WEBHOOK])


class DeliveryService:
    def __init__(self, session_factory: Callable[[], Any] = SessionLocal) -> None:
        self._session_factory = session_factory
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        try:
            WebhookDestination.__table__.create(bind=engine, checkfirst=True)
            WebhookDelivery.__table__.create(bind=engine, checkfirst=True)
        except Exception:
            Base.metadata.create_all(bind=engine)

    # ── destinations (operator-only config) ───────────────────────────────────

    def create_destination(
        self, *, name: str, url: str, kind: str = KIND_WEBHOOK, subscription: str = SUB_ALERTS,
        min_severity: str = "warning", event_filter: Optional[str] = None,
        secret: Optional[str] = None, enabled: bool = True,
    ) -> Optional[dict[str, Any]]:
        name, url = (name or "").strip(), (url or "").strip()
        if not name or not url.lower().startswith(("http://", "https://")):
            return None
        if subscription not in _SUBSCRIPTIONS or min_severity not in _SEVERITIES or kind not in _KINDS:
            return None
        with self._session_factory() as session:
            row = WebhookDestination(
                id=uuid4().hex, name=name[:120], url=url[:500], kind=kind,
                enabled=bool(enabled), subscription=subscription, min_severity=min_severity,
                event_filter=(event_filter or None), secret=(secret or None),
            )
            session.add(row)
            session.commit()
            return self._clean_destination(row)

    def update_destination(self, dest_id: str, **changes: Any) -> Optional[dict[str, Any]]:
        allowed = {"name", "url", "enabled", "subscription", "min_severity", "event_filter", "secret", "kind"}
        with self._session_factory() as session:
            row = session.get(WebhookDestination, dest_id)
            if row is None:
                return None
            for key, value in changes.items():
                if key not in allowed or value is None:
                    continue
                if key == "subscription" and value not in _SUBSCRIPTIONS:
                    return None
                if key == "min_severity" and value not in _SEVERITIES:
                    return None
                if key == "kind" and value not in _KINDS:
                    return None
                setattr(row, key, value)
            from datetime import datetime, timezone
            row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session.commit()
            return self._clean_destination(row)

    def delete_destination(self, dest_id: str) -> bool:
        with self._session_factory() as session:
            deleted = session.query(WebhookDestination).filter(WebhookDestination.id == dest_id).delete()
            session.commit()
            return bool(deleted)

    def list_destinations(self) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            rows = session.query(WebhookDestination).order_by(WebhookDestination.created_at.desc()).all()
            return [self._clean_destination(r) for r in rows]

    # ── routing (create durable deliveries; best-effort) ──────────────────────

    def route_observability(self, event: dict[str, Any]) -> int:
        """Fan an observability event out to enabled destinations subscribed to
        events (with optional type filter). Best-effort; returns #queued."""
        if not getattr(settings, "webhooks_enabled", True):
            return 0
        try:
            with self._session_factory() as session:
                dests = (
                    session.query(WebhookDestination)
                    .filter(WebhookDestination.enabled.is_(True),
                            WebhookDestination.subscription.in_((SUB_EVENTS, SUB_BOTH)))
                    .all()
                )
                queued = 0
                etype = event.get("event_type")
                for dest in dests:
                    if dest.event_filter:
                        allowed = {t.strip() for t in dest.event_filter.split(",") if t.strip()}
                        if etype not in allowed:
                            continue
                    self._enqueue_delivery(session, dest, source_type="observability",
                                           source_id=str(event.get("id")), event_type=etype,
                                           severity=None, payload=event,
                                           dedup_key=f"obs:{dest.id}:{event.get('id')}")
                    queued += 1
                session.commit()
                return queued
        except Exception:
            return 0  # delivery routing must never break the source path

    def route_alerts(self, alerts: list[dict[str, Any]]) -> int:
        """Route alert-worthy policy results to destinations subscribed to alerts,
        filtered by min_severity. Idempotent per (destination, alert signature)."""
        if not getattr(settings, "webhooks_enabled", True) or not alerts:
            return 0
        try:
            with self._session_factory() as session:
                dests = (
                    session.query(WebhookDestination)
                    .filter(WebhookDestination.enabled.is_(True),
                            WebhookDestination.subscription.in_((SUB_ALERTS, SUB_BOTH)))
                    .all()
                )
                queued = 0
                for dest in dests:
                    floor = _SEVERITY_RANK.get(dest.min_severity, 1)
                    for alert in alerts:
                        sev = alert.get("severity", "warning")
                        if _SEVERITY_RANK.get(sev, 0) < floor:
                            continue
                        sig = f"{alert.get('classification')}:{alert.get('job_id') or alert.get('exec_class')}"
                        dedup = f"alert:{dest.id}:{sig}"
                        # Idempotent: skip if an open delivery for this signal exists.
                        exists = (
                            session.query(WebhookDelivery)
                            .filter(WebhookDelivery.dedup_key == dedup,
                                    WebhookDelivery.status == STATUS_PENDING)
                            .first()
                        )
                        if exists is not None:
                            continue
                        self._enqueue_delivery(session, dest, source_type="alert", source_id=sig,
                                               event_type=alert.get("classification"), severity=sev,
                                               payload=alert, dedup_key=dedup)
                        queued += 1
                session.commit()
                return queued
        except Exception:
            return 0

    def _enqueue_delivery(self, session, dest, *, source_type, source_id, event_type,
                          severity, payload, dedup_key) -> None:
        session.add(WebhookDelivery(
            id=uuid4().hex, destination_id=dest.id, source_type=source_type,
            source_id=(source_id or None), event_type=event_type, severity=severity,
            status=STATUS_PENDING, attempts=0, dedup_key=dedup_key,
            payload_json=json.dumps(payload, default=str),
        ))

    # ── delivery worker step (bounded retry; honest terminal failure) ─────────

    def deliver_pending(self, *, max_deliveries: int = 50) -> dict[str, int]:
        """POST pending deliveries. A non-2xx / exception increments attempts and
        re-queues until `webhook_max_attempts`, then marks the delivery terminally
        failed (dead-letter-ready). Returns {delivered, failed, retried}."""
        delivered = failed = retried = 0
        with self._session_factory() as session:
            rows = (
                session.query(WebhookDelivery)
                .filter(WebhookDelivery.status == STATUS_PENDING)
                .order_by(WebhookDelivery.created_at.asc())
                .limit(max_deliveries)
                .all()
            )
            pending = [(r.id, r.destination_id, r.payload_json, r.attempts) for r in rows]

        for delivery_id, dest_id, payload_json, attempts in pending:
            with self._session_factory() as session:
                dest = session.get(WebhookDestination, dest_id)
                # Detach the fields the adapter needs (session closes after this).
                dest_view = _DestView(dest) if dest else None
            ok, code, err = (False, None, "NoDestination")
            if dest_view is not None:
                try:
                    payload = json.loads(payload_json)
                except (TypeError, ValueError):
                    payload = {}
                # The adapter shapes the payload + picks (url, secret); transport
                # stays the single injectable `_send` so retry/redrive are uniform.
                url, body, secret = adapter_for(dest_view.kind).prepare(dest_view, payload)
                ok, code, err = self._send(url, body, secret)
            with self._session_factory() as session:
                row = session.get(WebhookDelivery, delivery_id)
                if row is None:
                    continue
                row.attempts = attempts + 1
                row.response_code = code
                from datetime import datetime, timezone
                row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                if ok:
                    row.status, row.last_error = STATUS_DELIVERED, None
                    delivered += 1
                elif row.attempts >= max(1, settings.webhook_max_attempts):
                    row.status, row.last_error = STATUS_FAILED, (err or "DeliveryError")[:120]
                    failed += 1
                else:
                    row.status, row.last_error = STATUS_PENDING, (err or "DeliveryError")[:120]
                    retried += 1
                session.commit()
        return {"delivered": delivered, "failed": failed, "retried": retried}

    # ── redrive (operator-only recovery of terminal-failed deliveries) ────────

    def redrive(self, delivery_id: str) -> dict[str, Any]:
        """Operator redrive of a terminal-FAILED delivery: schedules a REAL new
        delivery attempt (a fresh `pending` row linked via `redrive_of`), preserving
        source + destination correlation. Distinct from auto-retry, job retry, and
        job/execution replay. Bounded by `webhook_max_redrives` and idempotent — a
        redrive already in flight is returned, never duplicated."""
        with self._session_factory() as session:
            row = session.get(WebhookDelivery, delivery_id)
            if row is None:
                return {"ok": False, "not_found": True, "message": "Delivery not found."}
            if row.status != STATUS_FAILED:
                return {"ok": False, "status": row.status,
                        "message": "Only a terminally-failed delivery can be redriven."}
            children = (
                session.query(WebhookDelivery)
                .filter(WebhookDelivery.redrive_of == delivery_id)
                .order_by(WebhookDelivery.created_at.asc())
                .all()
            )
            open_child = next((c for c in children if c.status == STATUS_PENDING), None)
            if open_child is not None:
                return {"ok": True, "delivery": self._clean_delivery(open_child),
                        "message": "A redrive is already in flight."}
            if len(children) >= max(1, settings.webhook_max_redrives):
                return {"ok": False, "status": STATUS_FAILED,
                        "message": "Redrive limit reached for this delivery."}
            child = WebhookDelivery(
                id=uuid4().hex, destination_id=row.destination_id, source_type=row.source_type,
                source_id=row.source_id, event_type=row.event_type, severity=row.severity,
                status=STATUS_PENDING, attempts=0, redrive_of=delivery_id,
                dedup_key=None, payload_json=row.payload_json,
            )
            session.add(child)
            session.commit()
            return {"ok": True, "delivery": self._clean_delivery(child),
                    "message": "Redrive scheduled."}

    def dead_letters(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Terminal-failed ORIGINAL deliveries (not themselves redrives), each
        classified from lineage: redrive_candidate / redriven / resolved / exhausted.
        The dead-letter view — recoverable without DB surgery."""
        with self._session_factory() as session:
            rows = (
                session.query(WebhookDelivery)
                .filter(WebhookDelivery.status == STATUS_FAILED, WebhookDelivery.redrive_of.is_(None))
                .order_by(WebhookDelivery.created_at.desc())
                .limit(min(limit, 200))
                .all()
            )
            out: list[dict[str, Any]] = []
            for row in rows:
                children = (
                    session.query(WebhookDelivery)
                    .filter(WebhookDelivery.redrive_of == row.id)
                    .all()
                )
                clean = self._clean_delivery(row)
                clean["dead_letter_state"] = self._dead_letter_state(children)
                clean["redrive_count"] = len(children)
                clean["redrive_ids"] = [c.id for c in children]
                out.append(clean)
            return out

    @staticmethod
    def _dead_letter_state(children: list) -> str:
        if any(c.status == STATUS_DELIVERED for c in children):
            return DL_RESOLVED
        if any(c.status == STATUS_PENDING for c in children):
            return DL_REDRIVEN
        if len(children) >= max(1, settings.webhook_max_redrives):
            return DL_EXHAUSTED
        return DL_REDRIVE_CANDIDATE

    def _send(self, url: str, body_json: str, secret: Optional[str]) -> tuple[bool, Optional[int], Optional[str]]:
        """POST the signed payload. Injected/overridable in tests. Returns
        (ok, status_code, error_class). Never raises."""
        try:
            import requests

            headers = {"Content-Type": "application/json", "User-Agent": "AIRA-X-Webhook/1"}
            body = body_json.encode("utf-8")
            if secret:
                sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
                headers["X-AIRA-Signature"] = f"sha256={sig}"
            resp = requests.post(url, data=body, headers=headers,
                                 timeout=getattr(settings, "webhook_timeout_seconds", 5.0))
            ok = 200 <= resp.status_code < 300
            return (ok, resp.status_code, None if ok else f"HTTP{resp.status_code}")
        except Exception as error:
            return (False, None, type(error).__name__)

    # ── inspection (operator-only; curated) ───────────────────────────────────

    def recent_deliveries(self, *, status: Optional[str] = None, destination_id: Optional[str] = None,
                          limit: int = 50) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            query = session.query(WebhookDelivery)
            if status:
                query = query.filter(WebhookDelivery.status == status)
            if destination_id:
                query = query.filter(WebhookDelivery.destination_id == destination_id)
            rows = query.order_by(WebhookDelivery.created_at.desc()).limit(min(limit, 200)).all()
            return [self._clean_delivery(r) for r in rows]

    def get_delivery(self, delivery_id: str) -> Optional[dict[str, Any]]:
        with self._session_factory() as session:
            row = session.get(WebhookDelivery, delivery_id)
            return self._clean_delivery(row, include_payload=True) if row is not None else None

    # ── clean shapes (secrets NEVER returned) ─────────────────────────────────

    @staticmethod
    def _clean_destination(row: WebhookDestination) -> dict[str, Any]:
        return {
            "id": row.id,
            "name": row.name,
            "url": row.url,
            "kind": row.kind,
            "enabled": row.enabled,
            "subscription": row.subscription,
            "min_severity": row.min_severity,
            "event_filter": row.event_filter,
            "has_secret": bool(row.secret),   # presence only — never the value
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @staticmethod
    def _clean_delivery(row: WebhookDelivery, *, include_payload: bool = False) -> dict[str, Any]:
        out = {
            "id": row.id,
            "destination_id": row.destination_id,
            "source_type": row.source_type,
            "source_id": row.source_id,
            "event_type": row.event_type,
            "severity": row.severity,
            "status": row.status,
            "attempts": row.attempts,
            "response_code": row.response_code,
            "last_error": row.last_error,   # error CLASS, never a body/secret
            "redrive_of": row.redrive_of,   # lineage: the original this re-drives
            "is_redrive": bool(row.redrive_of),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        if include_payload:
            try:
                out["payload"] = json.loads(row.payload_json)
            except (TypeError, ValueError):
                out["payload"] = None
        return out

    def clear_all(self) -> None:
        try:
            with self._session_factory() as session:
                session.query(WebhookDelivery).delete()
                session.query(WebhookDestination).delete()
                session.commit()
        except Exception:
            pass


delivery_service = DeliveryService()
