# File: backend/app/ops_policy.py
"""
Operational policy — SLOs, stuck-job detection, and alert-ready classification.

The observability layer (`app/observability.py`) emits curated signals and lists
terminal-failed jobs for triage. This module is the *policy* on top: it turns
durable job state + timestamps into a small, production-sensible set of health
classifications an external alerting/SLO backend can consume — instead of
heuristics scattered across the codebase or raw error counters with no meaning.

Classifications (`HealthClass`), each with a severity:
  * healthy          — active and within its SLO, or a clean terminal outcome.
  * stuck            — queued / running / cancel-requested past a durable
                       threshold (class-aware; generation gets a longer budget).
  * retry_exhausted  — terminal failed, internal retries spent, no follow-up.
  * triage_needed    — terminal failed and replay-worthy (an operator could act).
  * resolved         — failed, but a retry/replay already completed it.
  * backlog_pressure — one class has more queued work than its threshold.

Everything is derived from durable timestamps/state (never fragile in-memory
timers), is bounded and explainable (each result carries a human reason), and
honours lineage/resolution (a stuck job that later completes is no longer stuck; a
failed job whose retry succeeded is resolved, not alerted). Operator-only — these
classifications never reach the user-facing activity layer. Thresholds come from
operator-tunable settings via the swappable `SLOPolicy`, so alert routing / SLO
dashboards / dead-letter rules layer on without touching call sites.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models import ExecutionJob
from app.observability import failure_class_of, scope_of

# ── classifications + severities ──────────────────────────────────────────────
HEALTHY = "healthy"
STUCK = "stuck"
RETRY_EXHAUSTED = "retry_exhausted"
TRIAGE_NEEDED = "triage_needed"
RESOLVED = "resolved"
BACKLOG_PRESSURE = "backlog_pressure"

SEV_INFO = "info"
SEV_WARNING = "warning"
SEV_CRITICAL = "critical"

# States that occupy a worker slot (a "running" job for SLO purposes).
_RUNNING = {"running", "validating", "repairing", "awaiting_approval"}
_TERMINAL = {"completed", "failed", "canceled"}
_ACTIVE = {"queued", "cancel_requested"} | _RUNNING


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _age_seconds(ts: Optional[datetime], now: datetime) -> Optional[float]:
    if ts is None:
        return None
    return (now - ts).total_seconds()


@dataclass(frozen=True)
class SLOPolicy:
    """Operator-tunable thresholds (seconds / counts). Injectable so tests can pin
    exact values and the running-too-long budget can vary by class."""

    enabled: bool
    queued_seconds: int
    running_seconds: dict[str, int]   # per class name, with "default"
    cancel_seconds: int
    backlog_threshold: int

    @classmethod
    def from_settings(cls, s: Any = settings) -> "SLOPolicy":
        return cls(
            enabled=bool(getattr(s, "slo_enabled", True)),
            queued_seconds=int(getattr(s, "slo_queued_seconds", 300)),
            running_seconds={
                "default": int(getattr(s, "slo_running_seconds_default", 120)),
                "artifact": int(getattr(s, "slo_running_seconds_artifact", 600)),
                "validation": int(getattr(s, "slo_running_seconds_validation", 300)),
                "maintenance": int(getattr(s, "slo_running_seconds_maintenance", 600)),
            },
            cancel_seconds=int(getattr(s, "slo_cancel_seconds", 60)),
            backlog_threshold=int(getattr(s, "slo_backlog_threshold", 20)),
        )

    def running_limit(self, exec_class: Optional[str]) -> int:
        return self.running_seconds.get(exec_class or "", self.running_seconds["default"])


class OperationalPolicyService:
    def __init__(self, session_factory=SessionLocal) -> None:
        self._session_factory = session_factory

    # ── per-job classification (pure given a row + lineage) ───────────────────

    def classify_job(
        self, row: ExecutionJob, *, now: datetime, children: list[ExecutionJob], policy: SLOPolicy,
    ) -> dict[str, Any]:
        status = row.status
        if status in _TERMINAL:
            result = self._classify_terminal(row, children)
        else:
            result = self._classify_active(row, now, policy)
        scope_type, scope_id = scope_of(row.owner)
        return {
            "job_id": row.id,
            "kind": row.kind,
            "exec_class": row.exec_class,
            "status": status,
            "origin": row.origin,
            "classification": result["classification"],
            "severity": result["severity"],
            "reason": result["reason"],
            "failure_class": failure_class_of(_result(row)),
            "scope": {"type": scope_type, "id": scope_id},
            "age_seconds": result.get("age_seconds"),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    def _classify_terminal(self, row: ExecutionJob, children: list[ExecutionJob]) -> dict[str, Any]:
        if row.status in ("completed", "canceled"):
            # Intentional/clean terminal — not alertable.
            return {"classification": HEALTHY, "severity": SEV_INFO,
                    "reason": "Completed" if row.status == "completed" else "Canceled cleanly"}
        # failed:
        if any(c.status == "completed" for c in children):
            return {"classification": RESOLVED, "severity": SEV_INFO,
                    "reason": "Failed, but a retry/replay already succeeded"}
        if any(c.status in _ACTIVE for c in children):
            return {"classification": TRIAGE_NEEDED, "severity": SEV_INFO,
                    "reason": "Failed; a retry/replay is in progress"}
        if row.attempts >= max(1, settings.job_max_attempts):
            return {"classification": RETRY_EXHAUSTED, "severity": SEV_CRITICAL,
                    "reason": "Failed after exhausting internal retries"}
        return {"classification": TRIAGE_NEEDED, "severity": SEV_WARNING,
                "reason": "Failed; replay candidate (no follow-up yet)"}

    def _classify_active(self, row: ExecutionJob, now: datetime, policy: SLOPolicy) -> dict[str, Any]:
        if not policy.enabled:
            return {"classification": HEALTHY, "severity": SEV_INFO, "reason": "SLO checks disabled"}
        status = row.status
        if status == "queued":
            age = _age_seconds(row.created_at, now)
            if policy.queued_seconds and age is not None and age > policy.queued_seconds:
                return {"classification": STUCK, "severity": SEV_WARNING, "age_seconds": int(age),
                        "reason": f"Queued {int(age)}s without being claimed"}
            return {"classification": HEALTHY, "severity": SEV_INFO, "age_seconds": int(age or 0),
                    "reason": "Queued, within SLO"}
        if status == "cancel_requested":
            age = _age_seconds(row.updated_at, now)
            if policy.cancel_seconds and age is not None and age > policy.cancel_seconds:
                return {"classification": STUCK, "severity": SEV_CRITICAL, "age_seconds": int(age),
                        "reason": f"Cancel requested {int(age)}s ago but not yet canceled"}
            return {"classification": HEALTHY, "severity": SEV_INFO, "age_seconds": int(age or 0),
                    "reason": "Cancel in progress, within SLO"}
        # running-ish
        age = _age_seconds(row.started_at or row.created_at, now)
        limit = policy.running_limit(row.exec_class)
        if limit and age is not None and age > limit:
            return {"classification": STUCK, "severity": SEV_CRITICAL, "age_seconds": int(age),
                    "reason": f"Running {int(age)}s, past the {limit}s budget for its class"}
        return {"classification": HEALTHY, "severity": SEV_INFO, "age_seconds": int(age or 0),
                "reason": "Running, within SLO"}

    # ── aggregate health / alerts ─────────────────────────────────────────────

    def health(self, *, policy: Optional[SLOPolicy] = None, now: Optional[datetime] = None,
               limit: int = 200) -> dict[str, Any]:
        """A bounded policy snapshot: per-job classifications for recent active +
        terminal-failed work, per-class backlog pressure, and a summary count."""
        policy = policy or SLOPolicy.from_settings(settings)
        now = now or _now()
        classifications: list[dict[str, Any]] = []
        with self._session_factory() as session:
            rows = (
                session.query(ExecutionJob)
                .filter(ExecutionJob.status.in_(tuple(_ACTIVE | {"failed"})))
                .order_by(ExecutionJob.created_at.desc())
                .limit(limit)
                .all()
            )
            child_map: dict[str, list[ExecutionJob]] = {}
            failed_ids = [r.id for r in rows if r.status == "failed"]
            if failed_ids:
                for child in session.query(ExecutionJob).filter(ExecutionJob.parent_job_id.in_(failed_ids)).all():
                    child_map.setdefault(child.parent_job_id, []).append(child)
            for row in rows:
                classifications.append(self.classify_job(
                    row, now=now, children=child_map.get(row.id, []), policy=policy))
            backlog = self._backlog(session, policy)
        summary: dict[str, int] = {}
        for c in classifications:
            summary[c["classification"]] = summary.get(c["classification"], 0) + 1
        for b in backlog:
            summary[BACKLOG_PRESSURE] = summary.get(BACKLOG_PRESSURE, 0) + 1
        return {"classifications": classifications, "backlog": backlog, "summary": summary}

    def alerts(self, *, policy: Optional[SLOPolicy] = None, now: Optional[datetime] = None,
               limit: int = 200) -> list[dict[str, Any]]:
        """Alert-ready: only the warning/critical items — stuck, retry-exhausted,
        and backlog pressure — bounded and curated for external routing."""
        snapshot = self.health(policy=policy, now=now, limit=limit)
        alerts = [c for c in snapshot["classifications"] if c["severity"] in (SEV_WARNING, SEV_CRITICAL)]
        for b in snapshot["backlog"]:
            alerts.append({
                "job_id": None, "exec_class": b["exec_class"], "status": "queued",
                "classification": BACKLOG_PRESSURE, "severity": b["severity"],
                "reason": b["reason"], "scope": None,
            })
        # Critical first, then warning; stable within.
        alerts.sort(key=lambda a: 0 if a["severity"] == SEV_CRITICAL else 1)
        return alerts

    def _backlog(self, session, policy: SLOPolicy) -> list[dict[str, Any]]:
        from sqlalchemy import func

        rows = (
            session.query(ExecutionJob.exec_class, func.count(ExecutionJob.id))
            .filter(ExecutionJob.status == "queued")
            .group_by(ExecutionJob.exec_class)
            .all()
        )
        out: list[dict[str, Any]] = []
        for exec_class, count in rows:
            if count > policy.backlog_threshold:
                sev = SEV_CRITICAL if count > policy.backlog_threshold * 2 else SEV_WARNING
                out.append({
                    "exec_class": exec_class or "interactive",
                    "queued": int(count),
                    "threshold": policy.backlog_threshold,
                    "severity": sev,
                    "reason": f"{int(count)} jobs queued in '{exec_class or 'interactive'}' (> {policy.backlog_threshold})",
                })
        return out


def _result(row: ExecutionJob) -> Any:
    import json
    if not row.result_json:
        return None
    try:
        return json.loads(row.result_json)
    except (TypeError, ValueError):
        return None


ops_policy = OperationalPolicyService()
