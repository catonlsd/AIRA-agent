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
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from uuid import uuid4

from app.core.config import settings
from app.db.database import Base, SessionLocal, engine
from app.db.models import AlertOccurrence, WebhookDelivery, WebhookDestination

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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _status_bucket(status: str) -> str:
    return STATUS_DELIVERED if status == STATUS_DELIVERED else (
        STATUS_FAILED if status == STATUS_FAILED else STATUS_PENDING)


# ── destination adapters ──────────────────────────────────────────────────────
#
# An adapter owns ONLY payload shaping + which (url, secret) to use. The actual
# HTTP transport stays a single injectable primitive (`DeliveryService._send`), so
# the delivery state machine, retry, redrive, and tests are adapter-agnostic and
# later adapters (PagerDuty, email, a queue) are a one-class addition.

class WebhookAdapter:
    """The generic outbound HTTP adapter: POST the curated payload as-is, signed."""

    kind = KIND_WEBHOOK
    payload_shape = "structured_json"  # adapter-specific payload policy (intentional)
    # Adapter delivery policy: the default retry budget (None = the global default)
    # and a backoff CLASS label. A destination's own `max_attempts` overrides this.
    default_max_attempts: Optional[int] = None
    backoff = "standard"

    def prepare(self, dest, payload: dict) -> tuple[str, str, Optional[str]]:
        return dest.url, json.dumps(payload, default=str), dest.secret


class SlackAdapter:
    """A minimal Slack-compatible adapter: reshape the curated payload into Slack's
    `{"text": ...}` shape. Proves the abstraction without webhook-specific signing
    (Slack authenticates via the secret URL)."""

    kind = KIND_SLACK
    payload_shape = "slack_text"
    # Slack hooks are fast + transient; a tighter retry budget avoids hammering a
    # rate-limited endpoint (per-adapter policy actually used by delivery).
    default_max_attempts: Optional[int] = 2
    backoff = "fast"

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
        self.max_attempts = row.max_attempts


_ADAPTERS = {a.kind: a for a in (WebhookAdapter(), SlackAdapter())}


def adapter_for(kind: Optional[str]):
    """Resolve the adapter for a destination kind; unknown kinds fall back to the
    generic webhook adapter so a misconfigured destination still delivers safely."""
    return _ADAPTERS.get(kind or KIND_WEBHOOK, _ADAPTERS[KIND_WEBHOOK])


def effective_max_attempts(kind: Optional[str], dest_max: Optional[int]) -> int:
    """The DELIVERY retry budget for a destination: its own override, else the
    adapter default, else the global default. Bounded >= 1. Pure + testable."""
    if dest_max is not None:
        return max(1, int(dest_max))
    adapter_default = getattr(adapter_for(kind), "default_max_attempts", None)
    if adapter_default is not None:
        return max(1, int(adapter_default))
    return max(1, int(getattr(settings, "webhook_max_attempts", 4)))


def in_cooldown(cooldown_until, now) -> bool:
    """Whether a destination is currently cooling down (time-bounded)."""
    return cooldown_until is not None and cooldown_until > now


# ── routing-decision helpers (pure; enforced by routing) ──────────────────────

def _csv_set(value: Optional[str]) -> Optional[set[str]]:
    if not value:
        return None
    items = {t.strip() for t in value.split(",") if t.strip()}
    return items or None


def _alert_signal(alert: dict) -> str:
    """A stable per-(classification, subject) signal — the dedup/suppression key
    body. Severity is intentionally excluded so an escalation is NOT suppressed."""
    return f"{alert.get('classification')}:{alert.get('job_id') or alert.get('exec_class')}"


def alert_routing_decision(
    *, dest, alert: dict, in_flight: bool, last_severity: Optional[str],
    last_age_seconds: Optional[float], window_seconds: int,
    escalate_after: Optional[int] = None, occurrence_count: int = 1,
) -> tuple[str, str]:
    """Decide whether an alert should route to a destination, and why. Pure +
    testable. Returns one of: ("route", ...), ("skip", reason), ("suppress", reason).

      * skip:below_min_severity         — under the destination's floor
      * skip:classification_filtered    — not in the destination's alert_filter
      * skip:below_escalation_threshold — an escalation target, condition not yet
                                          persistent enough (occurrences < escalate_after)
      * skip:in_flight                  — an identical delivery is still pending
      * suppress:within_window          — same signal + same severity, inside window
      * route                           — a real new delivery should be created
    A severity CHANGE for the same signal always routes (escalation/recovery).
    Escalation is bounded by an occurrence count, never an uncontrolled fan-out.
    """
    sev = alert.get("severity", "warning")
    if _SEVERITY_RANK.get(sev, 0) < _SEVERITY_RANK.get(dest.min_severity, 1):
        return ("skip", "below_min_severity")
    allowed = _csv_set(dest.alert_filter)
    if allowed is not None and alert.get("classification") not in allowed:
        return ("skip", "classification_filtered")
    if escalate_after and occurrence_count < int(escalate_after):
        return ("skip", "below_escalation_threshold")
    if in_flight:
        return ("skip", "in_flight")
    if (window_seconds > 0 and last_severity == sev and last_age_seconds is not None
            and last_age_seconds < window_seconds):
        return ("suppress", "within_window")
    return ("route", "ok")


class DeliveryService:
    def __init__(self, session_factory: Callable[[], Any] = SessionLocal) -> None:
        self._session_factory = session_factory
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        try:
            WebhookDestination.__table__.create(bind=engine, checkfirst=True)
            WebhookDelivery.__table__.create(bind=engine, checkfirst=True)
            AlertOccurrence.__table__.create(bind=engine, checkfirst=True)
        except Exception:
            Base.metadata.create_all(bind=engine)

    # ── destinations (operator-only config) ───────────────────────────────────

    def create_destination(
        self, *, name: str, url: str, kind: str = KIND_WEBHOOK, subscription: str = SUB_ALERTS,
        min_severity: str = "warning", event_filter: Optional[str] = None,
        alert_filter: Optional[str] = None, origin_filter: Optional[str] = None,
        suppress_seconds: Optional[int] = None, escalate_after: Optional[int] = None,
        max_attempts: Optional[int] = None, secret: Optional[str] = None, enabled: bool = True,
    ) -> Optional[dict[str, Any]]:
        name, url = (name or "").strip(), (url or "").strip()
        if not name or not url.lower().startswith(("http://", "https://")):
            return None
        if subscription not in _SUBSCRIPTIONS or min_severity not in _SEVERITIES or kind not in _KINDS:
            return None
        if suppress_seconds is not None and int(suppress_seconds) < 0:
            return None
        if escalate_after is not None and int(escalate_after) < 1:
            return None
        if max_attempts is not None and int(max_attempts) < 1:
            return None
        with self._session_factory() as session:
            row = WebhookDestination(
                id=uuid4().hex, name=name[:120], url=url[:500], kind=kind,
                enabled=bool(enabled), subscription=subscription, min_severity=min_severity,
                event_filter=(event_filter or None), alert_filter=(alert_filter or None),
                origin_filter=(origin_filter or None),
                suppress_seconds=(int(suppress_seconds) if suppress_seconds is not None else None),
                escalate_after=(int(escalate_after) if escalate_after is not None else None),
                max_attempts=(int(max_attempts) if max_attempts is not None else None),
                secret=(secret or None),
            )
            session.add(row)
            session.commit()
            return self._clean_destination(row)

    def update_destination(self, dest_id: str, **changes: Any) -> Optional[dict[str, Any]]:
        allowed = {"name", "url", "enabled", "subscription", "min_severity", "event_filter",
                   "alert_filter", "origin_filter", "suppress_seconds", "escalate_after",
                   "max_attempts", "secret", "kind"}
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
                if key == "suppress_seconds" and int(value) < 0:
                    return None
                if key == "escalate_after" and int(value) < 1:
                    return None
                if key == "max_attempts" and int(value) < 1:
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
        events, enforcing per-destination event-type AND origin filters. Best-effort;
        returns #queued."""
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
                now = _utc_now()
                etype = event.get("event_type")
                eorigin = event.get("origin")  # normal -> None; retry/replay otherwise
                for dest in dests:
                    if in_cooldown(dest.cooldown_until, now):  # health-aware skip
                        dest.stat_skipped = (dest.stat_skipped or 0) + 1
                        continue
                    type_set = _csv_set(dest.event_filter)
                    if type_set is not None and etype not in type_set:
                        continue
                    origin_set = _csv_set(dest.origin_filter)
                    if origin_set is not None and (eorigin or "normal") not in origin_set:
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
        enforcing min_severity + classification filters and a bounded suppression
        window (a persistent stuck job won't re-deliver the same critical alert
        every sweep; a severity change still routes). Returns #routed (new
        deliveries); suppressed/skipped do NOT create records."""
        return self.route_alerts_detailed(alerts).get("routed", 0)

    def route_alerts_detailed(self, alerts: list[dict[str, Any]]) -> dict[str, int]:
        """Like `route_alerts` but returns `{routed, suppressed, skipped, escalated}`
        so the operator sweep can report how much noise the policy absorbed and how
        much it escalated. Records per-signal occurrences (for repeated-condition
        escalation) and bumps durable per-destination routing counters."""
        if not getattr(settings, "webhooks_enabled", True) or not alerts:
            return {"routed": 0, "suppressed": 0, "skipped": 0, "escalated": 0, "silenced": 0}
        default_window = int(getattr(settings, "webhook_suppress_seconds", 300))
        resolve_seconds = int(getattr(settings, "webhook_escalation_resolve_seconds", 1800))
        now = _utc_now()
        counts = {"routed": 0, "suppressed": 0, "skipped": 0, "escalated": 0, "silenced": 0}
        # Operator silence is a DISTINCT concept from suppression/cooldown: a
        # signal an operator has muted (bounded) is not routed anywhere. Best-effort
        # — never let the incident layer break delivery.
        try:
            from app.incidents import incident_service
            silenced = incident_service.silenced_signals()
        except Exception:
            silenced = set()
        try:
            with self._session_factory() as session:
                # One occurrence bump per (alert signal) per sweep — episodic so a
                # resolved-then-recurring condition starts a fresh count.
                occ: dict[str, int] = {}
                for alert in alerts:
                    sig = _alert_signal(alert)
                    occ[sig] = self._record_occurrence(session, sig, alert.get("severity"), now, resolve_seconds)
                dests = (
                    session.query(WebhookDestination)
                    .filter(WebhookDestination.enabled.is_(True),
                            WebhookDestination.subscription.in_((SUB_ALERTS, SUB_BOTH)))
                    .all()
                )
                for dest in dests:
                    # Health-aware: a cooling-down destination is skipped (honestly —
                    # no delivery is created), so an unhealthy endpoint and any
                    # escalation target pointing at it stop thrashing.
                    if in_cooldown(dest.cooldown_until, now):
                        dest.stat_skipped = (dest.stat_skipped or 0) + len(alerts)
                        counts["skipped"] += len(alerts)
                        continue
                    window = dest.suppress_seconds if dest.suppress_seconds is not None else default_window
                    for alert in alerts:
                        sig = _alert_signal(alert)
                        if sig in silenced:  # operator-muted — distinct from suppression
                            counts["silenced"] += 1
                            continue
                        dedup = f"alert:{dest.id}:{sig}"
                        in_flight, last_sev, last_age = self._dedup_state(session, dedup, now)
                        decision, _reason = alert_routing_decision(
                            dest=dest, alert=alert, in_flight=in_flight,
                            last_severity=last_sev, last_age_seconds=last_age, window_seconds=window,
                            escalate_after=dest.escalate_after, occurrence_count=occ.get(sig, 1))
                        if decision == "route":
                            self._enqueue_delivery(session, dest, source_type="alert",
                                                   source_id=sig, event_type=alert.get("classification"),
                                                   severity=alert.get("severity", "warning"),
                                                   payload=alert, dedup_key=dedup)
                            dest.stat_routed = (dest.stat_routed or 0) + 1
                            counts["routed"] += 1
                            if dest.escalate_after:
                                counts["escalated"] += 1
                        elif decision == "suppress":
                            dest.stat_suppressed = (dest.stat_suppressed or 0) + 1
                            counts["suppressed"] += 1
                        else:
                            dest.stat_skipped = (dest.stat_skipped or 0) + 1
                            counts["skipped"] += 1
                session.commit()
        except Exception:
            return counts
        return counts

    def _record_occurrence(self, session, signal: str, severity: Optional[str], now, resolve_seconds: int) -> int:
        """Bump (or reset, on a resolved episode) the durable occurrence count for a
        signal, returning the current count. Drives repeated-condition escalation."""
        row = session.get(AlertOccurrence, signal)
        if row is None:
            session.add(AlertOccurrence(signal=signal, count=1, last_severity=severity,
                                        first_seen=now, last_seen=now))
            return 1
        stale = (resolve_seconds > 0 and row.last_seen is not None
                 and (now - row.last_seen).total_seconds() > resolve_seconds)
        row.count = 1 if stale else (row.count or 0) + 1
        if stale:
            row.first_seen = now
        row.last_seen = now
        row.last_severity = severity
        return row.count

    def _dedup_state(self, session, dedup: str, now) -> tuple[bool, Optional[str], Optional[float]]:
        """(in_flight, last_severity, last_age_seconds) for a dedup signal — the
        inputs the suppression window needs, from the most recent delivery."""
        last = (
            session.query(WebhookDelivery)
            .filter(WebhookDelivery.dedup_key == dedup)
            .order_by(WebhookDelivery.created_at.desc())
            .first()
        )
        if last is None:
            return (False, None, None)
        in_flight = last.status == STATUS_PENDING
        age = (now - last.created_at).total_seconds() if last.created_at else None
        return (in_flight, last.severity, age)

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
                dest = session.get(WebhookDestination, dest_id)
                # Retry budget is adapter/destination-specific, not purely global.
                budget = effective_max_attempts(dest_view.kind if dest_view else None,
                                                 dest_view.max_attempts if dest_view else None)
                row.attempts = attempts + 1
                row.response_code = code
                row.updated_at = _utc_now()
                if ok:
                    row.status, row.last_error = STATUS_DELIVERED, None
                    delivered += 1
                    self._on_delivery_success(dest)
                elif row.attempts >= budget:
                    row.status, row.last_error = STATUS_FAILED, (err or "DeliveryError")[:120]
                    failed += 1
                    self._on_delivery_failure(dest)
                else:
                    row.status, row.last_error = STATUS_PENDING, (err or "DeliveryError")[:120]
                    retried += 1
                session.commit()
        return {"delivered": delivered, "failed": failed, "retried": retried}

    def _on_delivery_success(self, dest) -> None:
        """A success clears the failure streak and any cooldown — honest recovery."""
        if dest is None:
            return
        dest.consecutive_failures = 0
        dest.cooldown_until = None

    def _on_delivery_failure(self, dest) -> None:
        """A terminal failure bumps the streak; crossing the threshold cools the
        destination down for a bounded window so it stops thrashing."""
        if dest is None:
            return
        dest.consecutive_failures = (dest.consecutive_failures or 0) + 1
        threshold = max(1, int(getattr(settings, "webhook_cooldown_threshold", 5)))
        cooldown_seconds = int(getattr(settings, "webhook_cooldown_seconds", 600))
        if cooldown_seconds > 0 and dest.consecutive_failures >= threshold:
            from datetime import timedelta
            dest.cooldown_until = _utc_now() + timedelta(seconds=cooldown_seconds)

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

    def delivery_lineage(self, delivery_id: str) -> Optional[dict[str, Any]]:
        """The full redrive chain for one delivery: the ORIGINAL attempt plus every
        redrive attempt, in order, each curated (status / attempts / error class /
        time) — so an operator sees what happened over time, not just the current
        dead-letter state. Works whether the given id is the original or a redrive.
        Never raw payloads/secrets."""
        with self._session_factory() as session:
            row = session.get(WebhookDelivery, delivery_id)
            if row is None:
                return None
            root_id = row.redrive_of or row.id  # resolve to the original
            root = session.get(WebhookDelivery, root_id) or row
            children = (
                session.query(WebhookDelivery)
                .filter(WebhookDelivery.redrive_of == root.id)
                .order_by(WebhookDelivery.created_at.asc())
                .all()
            )
            attempts = [self._clean_delivery(root)] + [self._clean_delivery(c) for c in children]
            dest = session.get(WebhookDestination, root.destination_id)
            return {
                "root_id": root.id,
                "destination_id": root.destination_id,
                "destination_name": dest.name if dest else None,
                "destination_kind": dest.kind if dest else None,
                "source_type": root.source_type,
                "source_id": root.source_id,
                "event_type": root.event_type,
                "state": self._dead_letter_state(children) if root.status == STATUS_FAILED else (
                    "resolved" if root.status == STATUS_DELIVERED else "in_progress"),
                "attempts": attempts,  # curated chain, never payloads
            }

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
                          redrives: Optional[bool] = None, limit: int = 50) -> list[dict[str, Any]]:
        """Recent delivery attempts (history). Filterable by status, destination,
        and original-vs-redrive. Enriched with the destination name for a readable
        operator history — still curated (no payloads/secrets)."""
        with self._session_factory() as session:
            query = session.query(WebhookDelivery)
            if status:
                query = query.filter(WebhookDelivery.status == status)
            if destination_id:
                query = query.filter(WebhookDelivery.destination_id == destination_id)
            if redrives is True:
                query = query.filter(WebhookDelivery.redrive_of.isnot(None))
            elif redrives is False:
                query = query.filter(WebhookDelivery.redrive_of.is_(None))
            rows = query.order_by(WebhookDelivery.created_at.desc()).limit(min(limit, 200)).all()
            names = {d.id: d.name for d in session.query(WebhookDestination).all()}
            out = []
            for r in rows:
                clean = self._clean_delivery(r)
                clean["destination_name"] = names.get(r.destination_id)
                out.append(clean)
            return out

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
            "payload_shape": adapter_for(row.kind).payload_shape,  # adapter policy
            "enabled": row.enabled,
            "subscription": row.subscription,
            "min_severity": row.min_severity,
            "event_filter": row.event_filter,
            "alert_filter": row.alert_filter,
            "origin_filter": row.origin_filter,
            "suppress_seconds": row.suppress_seconds,
            "escalate_after": row.escalate_after,
            "is_escalation": bool(row.escalate_after),
            "max_attempts": row.max_attempts,  # None = adapter/global default
            "effective_max_attempts": effective_max_attempts(row.kind, row.max_attempts),
            "backoff": getattr(adapter_for(row.kind), "backoff", "standard"),
            "cooling_down": in_cooldown(row.cooldown_until, _utc_now()),
            "cooldown_until": row.cooldown_until.isoformat() if row.cooldown_until else None,
            "consecutive_failures": row.consecutive_failures or 0,
            "has_secret": bool(row.secret),   # presence only — never the value
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    # ── routing inspection (operator-only; explains decisions) ────────────────

    def routing_preview(self, dest_id: str, alerts: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        """A dry-run of the current alert set against ONE destination's policy:
        for each alert, would it route / suppress / skip, and why. Answers "why did
        this destination (not) receive this class of alert" without DB spelunking.
        Creates no deliveries."""
        now = _utc_now()
        default_window = int(getattr(settings, "webhook_suppress_seconds", 300))
        with self._session_factory() as session:
            dest = session.get(WebhookDestination, dest_id)
            if dest is None:
                return None
            window = dest.suppress_seconds if dest.suppress_seconds is not None else default_window
            decisions: list[dict[str, Any]] = []
            if dest.subscription in (SUB_ALERTS, SUB_BOTH):
                for alert in alerts:
                    sig = _alert_signal(alert)
                    dedup = f"alert:{dest.id}:{sig}"
                    in_flight, last_sev, last_age = self._dedup_state(session, dedup, now)
                    occ = session.get(AlertOccurrence, sig)
                    occ_count = occ.count if occ is not None else 1  # read-only; no bump
                    decision, reason = alert_routing_decision(
                        dest=dest, alert=alert, in_flight=in_flight,
                        last_severity=last_sev, last_age_seconds=last_age, window_seconds=window,
                        escalate_after=dest.escalate_after, occurrence_count=occ_count)
                    decisions.append({
                        "classification": alert.get("classification"),
                        "severity": alert.get("severity"),
                        "job_id": alert.get("job_id"),
                        "occurrences": occ_count,
                        "decision": decision,
                        "reason": reason,
                    })
            return {
                "destination": self._clean_destination(dest),
                "effective_window_seconds": window,
                "decisions": decisions,
            }

    # ── delivery analytics + destination health (operator-only) ───────────────

    def analytics(self, *, since_minutes: int = 60) -> dict[str, Any]:
        """A compact, queryable delivery summary: totals, per-kind, per-destination,
        and routing/suppression/escalation counters. Bounded; derived from durable
        state, not raw scraping. (Suppressed alerts create no delivery, so those
        counts come from the durable per-destination stat counters.)"""
        from datetime import timedelta
        cutoff = _utc_now() - timedelta(minutes=max(1, since_minutes))
        with self._session_factory() as session:
            dests = {d.id: d for d in session.query(WebhookDestination).all()}
            rows = (
                session.query(WebhookDelivery)
                .filter(WebhookDelivery.created_at >= cutoff)
                .all()
            )
            totals = {"attempted": 0, "delivered": 0, "failed": 0, "pending": 0, "redriven": 0}
            by_kind: dict[str, dict[str, int]] = {}
            per_dest: dict[str, dict[str, Any]] = {}
            for r in rows:
                totals["attempted"] += 1
                if r.status == STATUS_DELIVERED:
                    totals["delivered"] += 1
                elif r.status == STATUS_FAILED:
                    totals["failed"] += 1
                else:
                    totals["pending"] += 1
                if r.redrive_of:
                    totals["redriven"] += 1
                dest = dests.get(r.destination_id)
                kind = dest.kind if dest else "unknown"
                k = by_kind.setdefault(kind, {"delivered": 0, "failed": 0, "pending": 0})
                k[_status_bucket(r.status)] += 1
                pd = per_dest.setdefault(r.destination_id, {
                    "destination_id": r.destination_id,
                    "name": dest.name if dest else None,
                    "kind": kind,
                    "delivered": 0, "failed": 0, "pending": 0,
                })
                pd[_status_bucket(r.status)] += 1
            # Durable routing counters (incl. suppression — invisible in deliveries).
            routing = {"routed": 0, "suppressed": 0, "skipped": 0, "escalation_destinations": 0}
            for d in dests.values():
                routing["routed"] += d.stat_routed or 0
                routing["suppressed"] += d.stat_suppressed or 0
                routing["skipped"] += d.stat_skipped or 0
                if d.escalate_after:
                    routing["escalation_destinations"] += 1
            return {
                "window_minutes": since_minutes,
                "totals": totals,
                "routing": routing,
                "by_kind": by_kind,
                "by_destination": list(per_dest.values()),
            }

    def destination_health(self) -> list[dict[str, Any]]:
        """Per-destination health: status counts, redrive/dead-letter outcome, the
        durable routed/suppressed/skipped counters, last error class, and a calm
        health label. Bounded and operator-safe (no secrets, no payloads)."""
        with self._session_factory() as session:
            dests = session.query(WebhookDestination).order_by(WebhookDestination.created_at.desc()).all()
            return [self._health_of(session, dest) for dest in dests]

    def destination_health_one(self, dest_id: str) -> Optional[dict[str, Any]]:
        with self._session_factory() as session:
            dest = session.get(WebhookDestination, dest_id)
            return self._health_of(session, dest) if dest is not None else None

    def _health_of(self, session, dest) -> dict[str, Any]:
        rows = session.query(WebhookDelivery).filter(WebhookDelivery.destination_id == dest.id).all()
        delivered = sum(1 for r in rows if r.status == STATUS_DELIVERED)
        failed = sum(1 for r in rows if r.status == STATUS_FAILED and not r.redrive_of)
        pending = sum(1 for r in rows if r.status == STATUS_PENDING)
        resolved = sum(1 for r in rows if r.redrive_of and r.status == STATUS_DELIVERED)
        last_error = next((r.last_error for r in sorted(rows, key=lambda x: x.created_at or _utc_now(),
                                                        reverse=True) if r.last_error), None)
        cooling = in_cooldown(dest.cooldown_until, _utc_now())
        # Bounded, explainable classification (not a scoring engine).
        if not dest.enabled:
            health, reason = "disabled", "Destination is disabled"
        elif cooling:
            health, reason = "cooling_down", f"Cooling down after {dest.consecutive_failures or 0} consecutive failures"
        elif failed > 0 and delivered == 0:
            health, reason = "failing", "Terminal failures with no successful delivery"
        elif failed > 0:
            health, reason = "degraded", "Some deliveries have failed terminally"
        else:
            health, reason = "healthy", "Delivering normally"
        # Escalation should avoid a destination that's down/cooling/disabled.
        escalation_eligible = bool(dest.escalate_after) and health in ("healthy", "degraded")
        return {
            "destination_id": dest.id,
            "name": dest.name,
            "kind": dest.kind,
            "enabled": dest.enabled,
            "is_escalation": bool(dest.escalate_after),
            "delivered": delivered, "failed_terminal": failed, "pending": pending,
            "redrive_resolved": resolved,
            "routed": dest.stat_routed or 0,
            "suppressed": dest.stat_suppressed or 0,
            "skipped": dest.stat_skipped or 0,
            "consecutive_failures": dest.consecutive_failures or 0,
            "cooling_down": cooling,
            "cooldown_until": dest.cooldown_until.isoformat() if dest.cooldown_until else None,
            "escalation_eligible": escalation_eligible,
            "last_error": last_error,   # error CLASS only
            "health": health,
            "reason": reason,
        }

    def destination_policy(self, dest_id: str) -> Optional[dict[str, Any]]:
        """Effective delivery-control policy for one destination: adapter, retry
        budget (with provenance), backoff class, and cooldown configuration/state."""
        with self._session_factory() as session:
            dest = session.get(WebhookDestination, dest_id)
            if dest is None:
                return None
            adapter = adapter_for(dest.kind)
            if dest.max_attempts is not None:
                provenance = "destination"
            elif getattr(adapter, "default_max_attempts", None) is not None:
                provenance = "adapter"
            else:
                provenance = "global"
            return {
                "destination_id": dest.id,
                "kind": dest.kind,
                "payload_shape": adapter.payload_shape,
                "backoff": getattr(adapter, "backoff", "standard"),
                "max_attempts": effective_max_attempts(dest.kind, dest.max_attempts),
                "max_attempts_source": provenance,
                "cooldown_threshold": int(getattr(settings, "webhook_cooldown_threshold", 5)),
                "cooldown_seconds": int(getattr(settings, "webhook_cooldown_seconds", 600)),
                "consecutive_failures": dest.consecutive_failures or 0,
                "cooling_down": in_cooldown(dest.cooldown_until, _utc_now()),
                "cooldown_until": dest.cooldown_until.isoformat() if dest.cooldown_until else None,
            }

    def clear_cooldown(self, dest_id: str) -> bool:
        """Operator recovery: clear a destination's cooldown + failure streak so it
        resumes receiving deliveries. Honest, bounded, recoverable."""
        with self._session_factory() as session:
            dest = session.get(WebhookDestination, dest_id)
            if dest is None:
                return False
            dest.cooldown_until = None
            dest.consecutive_failures = 0
            session.commit()
            return True

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
                session.query(AlertOccurrence).delete()
                session.commit()
        except Exception:
            pass


delivery_service = DeliveryService()
