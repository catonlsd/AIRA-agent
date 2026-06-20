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
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional
from uuid import uuid4

from app.core.config import settings
from app.db.database import Base, SessionLocal, engine
from app.db.models import OperatorIncident

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
        except Exception:
            Base.metadata.create_all(bind=engine)

    # ── observe / recover (driven by the current alert set) ───────────────────

    def observe(self, alerts: list[dict[str, Any]]) -> None:
        """Open new incidents for current alerts and bump existing ones. A
        recovered or silence-expired condition that recurs reopens as a fresh
        episode (ack/note cleared) — honest re-trigger, never a stale state."""
        if not alerts:
            return
        now = _now()
        try:
            with self._session_factory() as session:
                for alert in alerts:
                    sig = signal_of(alert)
                    row = session.query(OperatorIncident).filter(OperatorIncident.signal == sig).first()
                    sev = alert.get("severity")
                    if row is None:
                        session.add(OperatorIncident(
                            id=uuid4().hex, signal=sig,
                            classification=alert.get("classification"),
                            subject=str(alert.get("job_id") or alert.get("exec_class") or "")[:120],
                            source="alert", state=STATE_OPEN, severity=sev, occurrences=1,
                            first_seen=now, last_seen=now))
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
                    row.occurrences = (row.occurrences or 0) + 1
                    row.severity = sev
                    row.last_seen = now
                session.commit()
        except Exception:
            pass  # incident bookkeeping must never break the sweep

    def recover_stale(self, active_signals: list[str]) -> int:
        """Any tracked, non-recovered incident whose signal is no longer in the
        current alert set has cleared — mark it recovered (honest recovery clears
        ack/silence). Returns how many recovered."""
        active = set(active_signals)
        now = _now()
        try:
            with self._session_factory() as session:
                rows = (
                    session.query(OperatorIncident)
                    .filter(OperatorIncident.state != STATE_RECOVERED)
                    .all()
                )
                recovered = 0
                for row in rows:
                    if row.signal not in active:
                        row.state = STATE_RECOVERED
                        row.recovered_at = now
                        row.silenced_until = None
                        recovered += 1
                session.commit()
                return recovered
        except Exception:
            return 0

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

    # ── operator actions ──────────────────────────────────────────────────────

    def acknowledge(self, incident_id: str, *, note: Optional[str] = None) -> Optional[dict[str, Any]]:
        return self._mutate(incident_id, lambda row: self._do_ack(row, note))

    def silence(self, incident_id: str, *, seconds: Optional[int] = None) -> Optional[dict[str, Any]]:
        max_s = max(1, int(getattr(settings, "incident_max_silence_seconds", 86400)))
        default_s = int(getattr(settings, "incident_default_silence_seconds", 3600))
        secs = min(max_s, max(1, int(seconds if seconds is not None else default_s)))
        return self._mutate(incident_id, lambda row: self._do_silence(row, secs))

    def unsilence(self, incident_id: str) -> Optional[dict[str, Any]]:
        return self._mutate(incident_id, self._do_unsilence)

    def set_note(self, incident_id: str, note: str) -> Optional[dict[str, Any]]:
        return self._mutate(incident_id, lambda row: setattr(row, "note", (note or "")[:280]))

    @staticmethod
    def _do_ack(row, note: Optional[str]) -> None:
        row.acknowledged_at = _now()
        if row.state in (STATE_OPEN,):
            row.state = STATE_ACKNOWLEDGED
        if note is not None:
            row.note = note[:280]

    @staticmethod
    def _do_silence(row, seconds: int) -> None:
        row.state = STATE_SILENCED
        row.silenced_until = _now() + timedelta(seconds=seconds)

    @staticmethod
    def _do_unsilence(row) -> None:
        row.silenced_until = None
        row.state = STATE_ACKNOWLEDGED if row.acknowledged_at else STATE_OPEN

    def _mutate(self, incident_id: str, fn) -> Optional[dict[str, Any]]:
        with self._session_factory() as session:
            row = session.get(OperatorIncident, incident_id)
            if row is None:
                return None
            fn(row)
            session.commit()
            return self._clean(row)

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
            "acknowledged": row.acknowledged_at is not None,
            "acknowledged_at": row.acknowledged_at.isoformat() if row.acknowledged_at else None,
            "silenced_until": row.silenced_until.isoformat() if (row.silenced_until and row.silenced_until > now) else None,
            "recovered_at": row.recovered_at.isoformat() if row.recovered_at else None,
            "first_seen": row.first_seen.isoformat() if row.first_seen else None,
            "last_seen": row.last_seen.isoformat() if row.last_seen else None,
        }

    def clear_all(self) -> None:
        try:
            with self._session_factory() as session:
                session.query(OperatorIncident).delete()
                session.commit()
        except Exception:
            pass


incident_service = IncidentWorkflowService()
