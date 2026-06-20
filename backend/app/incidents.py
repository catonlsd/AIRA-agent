# File: backend/app/incidents.py
"""
Operator incident workflow — acknowledge, silence, and honest recovery.

A small, durable operator-only layer on top of the alert/policy signals. It gives a
recurring operational condition (a stuck-job alert, a retry-exhausted class, a
backlog-pressure signal) a single durable identity — the alert SIGNAL
(`classification:subject`) — so operators can say "I'm on it" (acknowledge) or
"mute this for a bounded window" (silence) instead of keeping out-of-band notes.

Deliberately NOT a ticketing platform, and deliberately kept DISTINCT from the
related-but-different delivery concepts:
  * delivery **suppression** = per-(destination, signal) dedup window (F-10)
  * destination **cooldown** = per-destination health gate (F-12)
  * **dead-letter** = terminal delivery failure (F-9)
  * operator **silence** (here) = per-SIGNAL operator mute, bounded, that gates
    only *alert routing* — never delivery/execution truth.

Honesty rules: a silence is always time-bounded (never a black hole); a silenced
incident still EXISTS in operator state; a condition that clears becomes
`recovered`; and a recovered or silence-expired condition that recurs reopens as a
fresh episode. The whole thing is operator-gated at the route layer.

Collaboration (G-4): an incident can be owned by a single operator (`assignee` — an
operator-declared handle, since service-key auth carries no verified identity), and
every meaningful transition is appended to a curated, ordered action trail
(`OperatorIncidentEvent`) so a relieving operator can read what already happened
instead of relying on out-of-band coordination. Notes stay short and bounded; the
trail carries no payloads/traces/secrets — just action, actor, brief detail, and
the resulting state.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional
from uuid import uuid4

from app.core.config import settings
from app.db.database import Base, SessionLocal, engine, ensure_runtime_columns
from app.db.models import OperatorIncident, OperatorIncidentEvent

STATE_OPEN = "open"
STATE_ACKNOWLEDGED = "acknowledged"
STATE_SILENCED = "silenced"
STATE_RECOVERED = "recovered"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def signal_of(alert: dict) -> str:
    """The durable incident identity — must match the delivery layer's signal."""
    return f"{alert.get('classification')}:{alert.get('job_id') or alert.get('exec_class')}"


class IncidentWorkflowService:
    def __init__(self, session_factory: Callable[[], Any] = SessionLocal) -> None:
        self._session_factory = session_factory
        self._ensure_table()

    def _ensure_table(self) -> None:
        try:
            OperatorIncident.__table__.create(bind=engine, checkfirst=True)
            OperatorIncidentEvent.__table__.create(bind=engine, checkfirst=True)
        except Exception:
            Base.metadata.create_all(bind=engine)
        ensure_runtime_columns()  # additive: assignee/assigned_at on pre-G-4 DBs

    # ── observe / recover (driven by the current alert set) ───────────────────

    def observe(self, alerts: list[dict[str, Any]]) -> None:
        """Open new incidents for current alerts and bump existing ones. A
        recovered or silence-expired condition that recurs reopens as a fresh
        episode (ack/note cleared) — honest re-trigger, never a stale state."""
        if not alerts:
            return
        now = _now()
        transitions: list[tuple[str, str]] = []  # (incident_id, action) to mirror after commit
        try:
            with self._session_factory() as session:
                for alert in alerts:
                    sig = signal_of(alert)
                    row = session.query(OperatorIncident).filter(OperatorIncident.signal == sig).first()
                    sev = alert.get("severity")
                    if row is None:
                        new_id = uuid4().hex
                        session.add(OperatorIncident(
                            id=new_id, signal=sig,
                            classification=alert.get("classification"),
                            subject=str(alert.get("job_id") or alert.get("exec_class") or "")[:120],
                            source="alert", state=STATE_OPEN, severity=sev, occurrences=1,
                            first_seen=now, last_seen=now))
                        self._log(session, new_id, "opened", actor=None,
                                  detail=alert.get("classification"), state=STATE_OPEN)
                        transitions.append((new_id, "opened"))
                        continue
                    silence_expired = (row.state == STATE_SILENCED
                                       and (row.silenced_until is None or row.silenced_until <= now))
                    if row.state == STATE_RECOVERED or silence_expired:
                        # Fresh episode of a previously-cleared/muted condition.
                        row.state = STATE_OPEN
                        row.recovered_at = None
                        row.silenced_until = None
                        row.acknowledged_at = None
                        row.note = None
                        row.first_seen = now
                        # Assignment carries over (the owner still owns the recurrence).
                        self._log(session, row.id, "reopened", actor=None,
                                  detail="recurred", state=STATE_OPEN)
                        transitions.append((row.id, "reopened"))
                    row.occurrences = (row.occurrences or 0) + 1
                    row.severity = sev
                    row.last_seen = now
                session.commit()
        except Exception:
            return  # incident bookkeeping must never break the sweep
        for incident_id, action in transitions:
            self._emit_sync(incident_id, action, None)

    def recover_stale(self, active_signals: list[str]) -> int:
        """Any tracked, non-recovered incident whose signal is no longer in the
        current alert set has cleared — mark it recovered (honest recovery clears
        ack/silence). Returns how many recovered."""
        active = set(active_signals)
        now = _now()
        recovered_ids: list[str] = []
        try:
            with self._session_factory() as session:
                rows = (
                    session.query(OperatorIncident)
                    .filter(OperatorIncident.state != STATE_RECOVERED)
                    .all()
                )
                for row in rows:
                    if row.signal not in active:
                        row.state = STATE_RECOVERED
                        row.recovered_at = now
                        row.silenced_until = None
                        self._log(session, row.id, "recovered", actor=None,
                                  detail="condition cleared", state=STATE_RECOVERED)
                        recovered_ids.append(row.id)
                session.commit()
        except Exception:
            return 0
        for incident_id in recovered_ids:
            self._emit_sync(incident_id, "recovered", None)
        return len(recovered_ids)

    # ── routing integration (the ONE coupling: silence gates routing) ─────────

    def silenced_signals(self) -> set[str]:
        """Signals currently under an active (unexpired) operator silence — used by
        alert routing to skip them. Expired silences are NOT included (auto-expiry)."""
        now = _now()
        try:
            with self._session_factory() as session:
                rows = (
                    session.query(OperatorIncident.signal)
                    .filter(OperatorIncident.state == STATE_SILENCED,
                            OperatorIncident.silenced_until.isnot(None),
                            OperatorIncident.silenced_until > now)
                    .all()
                )
                return {r[0] for r in rows}
        except Exception:
            return set()

    # ── operator actions (each appends one curated trail entry) ────────────────

    def acknowledge(self, incident_id: str, *, note: Optional[str] = None,
                    actor: Optional[str] = None) -> Optional[dict[str, Any]]:
        def fn(row):
            row.acknowledged_at = _now()
            if row.state == STATE_OPEN:
                row.state = STATE_ACKNOWLEDGED
            if note is not None:
                row.note = note[:280]
            return ("acknowledged", note[:280] if note else None)
        return self._apply(incident_id, fn, actor)

    def silence(self, incident_id: str, *, seconds: Optional[int] = None,
                actor: Optional[str] = None) -> Optional[dict[str, Any]]:
        max_s = max(1, int(getattr(settings, "incident_max_silence_seconds", 86400)))
        default_s = int(getattr(settings, "incident_default_silence_seconds", 3600))
        secs = min(max_s, max(1, int(seconds if seconds is not None else default_s)))

        def fn(row):
            row.state = STATE_SILENCED
            row.silenced_until = _now() + timedelta(seconds=secs)
            return ("silenced", f"until {row.silenced_until.isoformat()}")
        return self._apply(incident_id, fn, actor)

    def unsilence(self, incident_id: str, *, actor: Optional[str] = None) -> Optional[dict[str, Any]]:
        def fn(row):
            row.silenced_until = None
            row.state = STATE_ACKNOWLEDGED if row.acknowledged_at else STATE_OPEN
            return ("unsilenced", None)
        return self._apply(incident_id, fn, actor)

    def set_note(self, incident_id: str, note: str, *, actor: Optional[str] = None) -> Optional[dict[str, Any]]:
        def fn(row):
            row.note = (note or "")[:280]
            return ("note_updated", row.note or None)
        return self._apply(incident_id, fn, actor)

    def assign(self, incident_id: str, assignee: str, *, actor: Optional[str] = None) -> Optional[dict[str, Any]]:
        """Set the current owner (bounded operator-declared handle). Re-assigning to a
        different handle is recorded as `reassigned`; the caller validates non-empty."""
        handle = (assignee or "").strip()[:80]
        if not handle:
            return None

        def fn(row):
            prev = row.assignee
            row.assignee = handle
            row.assigned_at = _now()
            action = "reassigned" if (prev and prev != handle) else "assigned"
            return (action, f"→ {handle}")
        return self._apply(incident_id, fn, actor)

    def unassign(self, incident_id: str, *, actor: Optional[str] = None) -> Optional[dict[str, Any]]:
        def fn(row):
            prev = row.assignee
            row.assignee = None
            row.assigned_at = None
            return ("unassigned", f"was {prev}" if prev else None)
        return self._apply(incident_id, fn, actor)

    def mark_recovered(self, incident_id: str, *, actor: Optional[str] = None,
                       reason: str = "operator-recovered") -> Optional[dict[str, Any]]:
        """Explicitly recover an incident by id (operator-driven). Unlike
        `recover_stale` (signal-absence sweep), this is a deliberate single-incident
        action — used by apply-from-external when an operator chooses to accept an
        external `resolved`. Already-recovered is a no-op. Recorded on the trail."""
        def fn(row):
            if row.state == STATE_RECOVERED:
                return None
            row.state = STATE_RECOVERED
            row.recovered_at = _now()
            row.silenced_until = None
            return ("recovered", reason[:280])
        return self._apply(incident_id, fn, actor)

    def _apply(self, incident_id: str, fn, actor: Optional[str]) -> Optional[dict[str, Any]]:
        emitted_action: Optional[str] = None
        with self._session_factory() as session:
            row = session.get(OperatorIncident, incident_id)
            if row is None:
                return None
            result = fn(row)
            if result is not None:
                action, detail = result
                self._log(session, row.id, action, actor=actor, detail=detail, state=row.state)
                emitted_action = action
            session.commit()
            clean = self._clean(row)
        if emitted_action is not None:
            self._emit_sync(incident_id, emitted_action, actor, incident=clean)
        return clean

    @staticmethod
    def _log(session, incident_id: str, action: str, *, actor: Optional[str],
             detail: Optional[str], state: Optional[str]) -> None:
        actor = (actor or "").strip()[:80] or None
        session.add(OperatorIncidentEvent(
            incident_id=incident_id, action=action, actor=actor,
            detail=(detail[:280] if detail else None), state=state, created_at=_now()))

    def _emit_sync(self, incident_id: str, action: str, actor: Optional[str],
                   *, incident: Optional[dict[str, Any]] = None) -> None:
        """Mirror a committed incident transition to external sync targets. Lazily
        imported and fully guarded — external sync must NEVER break the workflow,
        and is a no-op when no targets are configured."""
        try:
            from app.incident_sync import incident_sync_service

            snapshot = incident if incident is not None else self.get(incident_id)
            if snapshot is not None:
                incident_sync_service.export(snapshot, action, actor=actor)
        except Exception:
            pass

    # ── reads ─────────────────────────────────────────────────────────────────

    def list(self, *, include_recovered: bool = True, limit: int = 100) -> list[dict[str, Any]]:
        try:
            with self._session_factory() as session:
                query = session.query(OperatorIncident)
                if not include_recovered:
                    query = query.filter(OperatorIncident.state != STATE_RECOVERED)
                rows = query.order_by(OperatorIncident.last_seen.desc()).limit(min(limit, 200)).all()
                return [self._clean(r) for r in rows]
        except Exception:
            return []

    def get(self, incident_id: str) -> Optional[dict[str, Any]]:
        with self._session_factory() as session:
            row = session.get(OperatorIncident, incident_id)
            return self._clean(row) if row is not None else None

    def _clean(self, row: OperatorIncident) -> dict[str, Any]:
        now = _now()
        # Effective state: a silence whose window elapsed reads as open (auto-expiry
        # is honest even before the next observe() reopens it).
        state = row.state
        if state == STATE_SILENCED and (row.silenced_until is None or row.silenced_until <= now):
            state = STATE_ACKNOWLEDGED if row.acknowledged_at else STATE_OPEN
        return {
            "id": row.id,
            "signal": row.signal,
            "classification": row.classification,
            "subject": row.subject,
            "source": row.source,
            "state": state,
            "severity": row.severity,
            "occurrences": row.occurrences or 0,
            "note": row.note,
            "assignee": row.assignee,
            "assigned_at": row.assigned_at.isoformat() if row.assigned_at else None,
            "acknowledged": row.acknowledged_at is not None,
            "acknowledged_at": row.acknowledged_at.isoformat() if row.acknowledged_at else None,
            "silenced_until": row.silenced_until.isoformat() if (row.silenced_until and row.silenced_until > now) else None,
            "recovered_at": row.recovered_at.isoformat() if row.recovered_at else None,
            "first_seen": row.first_seen.isoformat() if row.first_seen else None,
            "last_seen": row.last_seen.isoformat() if row.last_seen else None,
        }

    def history(self, incident_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """The curated, chronological action trail for one incident (oldest first)."""
        try:
            with self._session_factory() as session:
                rows = (
                    session.query(OperatorIncidentEvent)
                    .filter(OperatorIncidentEvent.incident_id == incident_id)
                    .order_by(OperatorIncidentEvent.id.asc())
                    .limit(min(limit, 200))
                    .all()
                )
                return [{
                    "action": r.action,
                    "actor": r.actor,
                    "detail": r.detail,
                    "state": r.state,
                    "at": r.created_at.isoformat() if r.created_at else None,
                } for r in rows]
        except Exception:
            return []

    def clear_all(self) -> None:
        try:
            with self._session_factory() as session:
                session.query(OperatorIncidentEvent).delete()
                session.query(OperatorIncident).delete()
                session.commit()
        except Exception:
            pass


incident_service = IncidentWorkflowService()
