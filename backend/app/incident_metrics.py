"""Incident-sync observability — bounded, deterministic operational metrics (Phase 5).

This module is **pure**: it turns already-extracted samples (timestamps + outcome
classes) into windowed rollups, SLO percentages, and candidate-alert observations. It
holds **no state and touches no database** — `IncidentSyncService.incident_metrics()`
does the (bounded) reads and feeds the rows in here. That keeps the math unit-testable
in isolation and guarantees every number is explainable from existing audit/history.

Design rules (match the operator guardrails):
- **No duplicate storage / no background aggregation** — metrics are computed on read
  from the existing check-event, reconciliation-event, sync-record, link, and target
  rows.
- **Deterministic** — same rows + same `now` always yield the same output. No sampling,
  no smoothing, no AI.
- **Honest about "no data"** — a rate over zero decided samples is `None`, never a
  misleading `0%` or `100%`.
- **Observe, never enforce** — SLO numbers and candidate alerts are signals; nothing
  here mutates state, pages, or notifies.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

# Trend windows (seconds). Bounded and fixed — no warehouse, no custom ranges.
WINDOWS: dict[str, int] = {"24h": 86400, "7d": 604800, "30d": 2592000}

# Hard safety cap on how many recent events any single metrics read will scan. Keeps
# the computation bounded regardless of how much history has accumulated.
METRICS_EVENT_CAP = 5000

# Candidate-alert thresholds (deterministic constants). An alert is an *observation*
# that a count crossed a fixed line — never a notification or an action.
ALERT_AUTH_FAILURES = 3        # auth-failed validations for one target within 24h
ALERT_VALIDATION_FAILURES = 3  # failed validations for one target within 24h
ALERT_DRIFT_BACKLOG = 5        # current actionable drift/missing/stale links
ALERT_STALE_READINESS = 3      # current targets whose readiness has aged to `stale`
ALERT_RECON_FAILURES = 5       # failed reconciliation actions within 24h

# Outcome vocabularies (mirror what the writers record).
VALIDATION_EVENTS = frozenset({"validate", "revalidate"})
RECON_OK = frozenset({"ok"})
RECON_FAIL = frozenset({"failed", "missing"})
# "skipped" / "unsupported" are honest non-events — they neither pass nor fail an SLO.


def pct(numerator: int, denominator: int) -> Optional[float]:
    """A rounded percentage, or None when there's nothing decided yet. None (not 0.0)
    is the honest answer for an empty denominator so dashboards never imply a 0%/100%
    SLO from zero samples."""
    if denominator <= 0:
        return None
    return round(100.0 * numerator / denominator, 1)


def within(ts: Optional[datetime], now: datetime, seconds: int) -> bool:
    """True if `ts` is within the last `seconds` of `now` (and not in the future)."""
    if ts is None:
        return False
    delta = (now - ts).total_seconds()
    return 0 <= delta <= seconds


def validation_class(outcome: Optional[str], ready_state: str = "ready") -> str:
    """A validate/revalidate check event's outcome → pass | fail. The outcome is the
    resulting readiness state, so only `ready` is a pass."""
    return "pass" if outcome == ready_state else "fail"


def recon_class(outcome: Optional[str]) -> str:
    """A reconciliation event's outcome → pass | fail | neutral."""
    if outcome in RECON_OK:
        return "pass"
    if outcome in RECON_FAIL:
        return "fail"
    return "neutral"


def sync_class(status: Optional[str], *, synced: str = "synced", failed: str = "failed") -> str:
    """A sync record's status → pass | fail | neutral (pending)."""
    if status == synced:
        return "pass"
    if status == failed:
        return "fail"
    return "neutral"


def recon_category(action: Optional[str]) -> str:
    """Group a reconciliation action into a stable category. `apply:*` and `external:*`
    are namespaced; everything else (refresh / redrive / detach / relink / push) is its
    own category."""
    a = action or ""
    if a.startswith("apply:"):
        return "apply"
    if a.startswith("external:"):
        return "external_action"
    return a or "unknown"


def window_rollup(samples: Iterable[tuple[Optional[datetime], str]], now: datetime) -> dict[str, dict]:
    """Bucket (timestamp, class) samples — class in {pass, fail, neutral} — into each
    trend window. Returns, per window, the pass/fail/neutral counts, the total, and the
    pass rate over *decided* samples (pass+fail; neutral excluded, None when zero)."""
    materialized = list(samples)
    out: dict[str, dict] = {}
    for label, seconds in WINDOWS.items():
        passed = failed = neutral = 0
        for ts, cls in materialized:
            if not within(ts, now, seconds):
                continue
            if cls == "pass":
                passed += 1
            elif cls == "fail":
                failed += 1
            else:
                neutral += 1
        decided = passed + failed
        out[label] = {
            "pass": passed, "fail": failed, "neutral": neutral,
            "total": passed + failed + neutral,
            "pass_pct": pct(passed, decided),
        }
    return out


def count_in_windows(timestamps: Iterable[Optional[datetime]], now: datetime) -> dict[str, int]:
    """Count bare timestamps falling in each trend window."""
    materialized = list(timestamps)
    return {label: sum(1 for ts in materialized if within(ts, now, seconds))
            for label, seconds in WINDOWS.items()}


def _severity(count: int, threshold: int) -> str:
    """Deterministic severity: a count at/above twice the threshold is `critical`,
    otherwise `warning`. (Candidate alerts are observations, so there is no `page`.)"""
    return "critical" if count >= 2 * threshold else "warning"


def candidate_alerts(
    *,
    auth_failures_by_target: dict[str, int],
    validation_failures_by_target: dict[str, int],
    drift_backlog: int,
    stale_count: int,
    recon_failures_24h: int,
) -> list[dict]:
    """Derive deterministic candidate alerts from already-aggregated counts. Each alert
    is a pure observation: a fixed threshold was crossed. No notification, no paging,
    no remediation — the operator decides what (if anything) to do. Sorted critical-first
    then by count desc for stable, scan-friendly ordering."""
    alerts: list[dict] = []

    for name, count in auth_failures_by_target.items():
        if count >= ALERT_AUTH_FAILURES:
            alerts.append({
                "code": "repeated_auth_failures", "severity": _severity(count, ALERT_AUTH_FAILURES),
                "subject": name, "count": count, "threshold": ALERT_AUTH_FAILURES,
                "detail": f"{count} auth-failed validations in 24h — rotate the secret, then revalidate.",
            })
    for name, count in validation_failures_by_target.items():
        if count >= ALERT_VALIDATION_FAILURES:
            alerts.append({
                "code": "repeated_validation_failures", "severity": _severity(count, ALERT_VALIDATION_FAILURES),
                "subject": name, "count": count, "threshold": ALERT_VALIDATION_FAILURES,
                "detail": f"{count} failed validations in 24h — check endpoint/config.",
            })
    if drift_backlog >= ALERT_DRIFT_BACKLOG:
        alerts.append({
            "code": "drift_backlog", "severity": _severity(drift_backlog, ALERT_DRIFT_BACKLOG),
            "subject": "incident-sync", "count": drift_backlog, "threshold": ALERT_DRIFT_BACKLOG,
            "detail": f"{drift_backlog} unresolved drift/missing/stale links — refresh or detach to clear.",
        })
    if stale_count >= ALERT_STALE_READINESS:
        alerts.append({
            "code": "stale_readiness", "severity": _severity(stale_count, ALERT_STALE_READINESS),
            "subject": "incident-sync", "count": stale_count, "threshold": ALERT_STALE_READINESS,
            "detail": f"{stale_count} targets aged to stale — revalidate to restore trust.",
        })
    if recon_failures_24h >= ALERT_RECON_FAILURES:
        alerts.append({
            "code": "reconciliation_failures", "severity": _severity(recon_failures_24h, ALERT_RECON_FAILURES),
            "subject": "incident-sync", "count": recon_failures_24h, "threshold": ALERT_RECON_FAILURES,
            "detail": f"{recon_failures_24h} failed reconciliation actions in 24h — investigate the targets involved.",
        })

    alerts.sort(key=lambda a: (0 if a["severity"] == "critical" else 1, -a["count"]))
    return alerts
