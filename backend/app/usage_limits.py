# File: backend/app/usage_limits.py
"""
Per-principal usage quotas + execution-safety boundaries.

Ownership boundaries (Step 5) gave every resource an owner. This module makes
shared resources *fair* under multi-user load: a principal cannot spam expensive
flows, hoard pending approvals, or repeatedly trigger execution/validation.

Two durable, multi-process-safe primitives:
  * UsageLimiter  — windowed counters (rows in `usage_records`) for rate-style
                    quotas: execution starts, artifact generations, startup
                    validations per owner per window.
  * pending-flow cap — counts live guided-flow rows for the owner.

`QuotaService` ties them to operator-tunable settings and a single
`QuotaDecision` result, so the supervisor enforces limits in one clean place and
fails honestly (never half-way through a run). The interface is small so a tier
model (free/paid), per-workspace quotas, or a Redis backend slot in later
without touching call sites.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional
from uuid import uuid4

from sqlalchemy import delete

from app.core.config import settings
from app.db.database import Base, SessionLocal, engine
from app.db.models import UsageRecord
from app.guided_flow_store import guided_flow_store

# Structured safety-event log (ops-facing, never shown in the chat UI).
_safety_logger = logging.getLogger("aira_x.safety")

# Quota kinds (also the usage_records.kind values).
KIND_EXECUTION = "execution_start"
KIND_ARTIFACT = "artifact_generation"
KIND_STARTUP = "startup_validation"
KIND_PENDING = "pending_flow"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class QuotaDecision:
    """Outcome of a quota check."""

    allowed: bool
    kind: str
    message: str = ""

    def __bool__(self) -> bool:
        return self.allowed


class UsageLimiter:
    """Durable windowed counter for rate-style per-owner quotas."""

    def __init__(self, session_factory: Callable[[], Any] = SessionLocal) -> None:
        self._session_factory = session_factory
        self._ensure_table()

    def _ensure_table(self) -> None:
        try:
            UsageRecord.__table__.create(bind=engine, checkfirst=True)
        except Exception:
            Base.metadata.create_all(bind=engine)

    def count_in_window(self, owner: str, kind: str, window_seconds: int) -> int:
        cutoff = _now() - timedelta(seconds=window_seconds)
        with self._session_factory() as session:
            return (
                session.query(UsageRecord)
                .filter(
                    UsageRecord.owner == owner,
                    UsageRecord.kind == kind,
                    UsageRecord.created_at >= cutoff,
                )
                .count()
            )

    def check(self, owner: str, kind: str, limit: int, window_seconds: int) -> bool:
        """True if recording one more action would stay within the limit."""
        return self.count_in_window(owner, kind, window_seconds) < limit

    def record(self, owner: str, kind: str) -> None:
        with self._session_factory() as session:
            session.add(UsageRecord(id=uuid4().hex, owner=owner, kind=kind, created_at=_now()))
            session.commit()

    def purge_old(self, older_than_seconds: int) -> int:
        cutoff = _now() - timedelta(seconds=older_than_seconds)
        with self._session_factory() as session:
            result = session.execute(delete(UsageRecord).where(UsageRecord.created_at < cutoff))
            session.commit()
            return result.rowcount or 0

    def reset(self) -> None:
        """Wipe all usage records (tests)."""
        with self._session_factory() as session:
            session.execute(delete(UsageRecord))
            session.commit()


usage_limiter = UsageLimiter()


_LIMIT_MESSAGES = {
    KIND_EXECUTION: (
        "Execution is temporarily rate-limited for this session because the "
        "execution quota was reached. Please try again shortly."
    ),
    KIND_ARTIFACT: (
        "Artifact generation is temporarily rate-limited. Please try again shortly."
    ),
    KIND_STARTUP: (
        "Runtime validation is temporarily rate-limited for this session. Please "
        "try again shortly."
    ),
    KIND_PENDING: (
        "You already have too many pending approval flows. Resolve or cancel one "
        "before starting another."
    ),
}


class QuotaService:
    """Operator-tunable quota policy, enforced in one place by the supervisor."""

    def __init__(self, limiter: UsageLimiter = usage_limiter) -> None:
        self._limiter = limiter

    def _window(self) -> int:
        return settings.quota_window_seconds

    def _limit_for(self, kind: str) -> int:
        return {
            KIND_EXECUTION: settings.execution_starts_per_window,
            KIND_ARTIFACT: settings.artifact_generations_per_window,
            KIND_STARTUP: settings.startup_validations_per_window,
        }[kind]

    def check_windowed(self, owner: str, kind: str) -> QuotaDecision:
        """Check a windowed quota WITHOUT recording (record on real action)."""
        if not settings.quotas_enabled:
            return QuotaDecision(True, kind)
        if self._limiter.check(owner, kind, self._limit_for(kind), self._window()):
            return QuotaDecision(True, kind)
        self._log_rejection(owner, kind)
        return QuotaDecision(False, kind, _LIMIT_MESSAGES[kind])

    def record(self, owner: str, kind: str) -> None:
        if settings.quotas_enabled:
            self._limiter.record(owner, kind)

    def check_pending_flows(self, owner: str) -> QuotaDecision:
        """Block creating a new guided flow when the owner has too many pending."""
        if not settings.quotas_enabled:
            return QuotaDecision(True, KIND_PENDING)
        if guided_flow_store.count_pending(owner) < settings.max_pending_flows_per_owner:
            return QuotaDecision(True, KIND_PENDING)
        self._log_rejection(owner, KIND_PENDING)
        return QuotaDecision(False, KIND_PENDING, _LIMIT_MESSAGES[KIND_PENDING])

    @staticmethod
    def _log_rejection(owner: str, kind: str) -> None:
        try:
            import json

            _safety_logger.warning(
                json.dumps({"event": "quota_rejected", "kind": kind, "owner": owner})
            )
        except Exception:
            pass


quota_service = QuotaService()
