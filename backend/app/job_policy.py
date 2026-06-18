# File: backend/app/job_policy.py
"""
Execution policy — priority, concurrency classes, and fairness for the queue.

A small, real scheduling model so the durable queue stops treating all work the
same: light interactive work jumps ahead of heavy generation, an expensive class
can't hog every worker, and no single owner can monopolise a class. It stays a
clean abstraction (one swap-point for worker pools / external queues later), not a
distributed scheduler — but it is actually *used* by the claim path.

Each job `kind` maps to an `ExecutionClass` with:
  * priority   — higher claims sooner (interactive > artifact > validation >
                 maintenance), with created_at FIFO as the deterministic tie-break.
  * concurrency— max jobs of the class running at once (0 = unbounded), so a heavy
                 class is bounded independently of lighter work.

Two complementary bounds keep it fair, without replacing quotas (which still gate
enqueue/approval): a per-class concurrency cap and a per-owner in-flight cap, so a
class at capacity or an owner already running their share is skipped — others
proceed, nothing starves forever. Every cap is operator-tunable via settings with
safe defaults and validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

# Operator/maintenance work that re-runs an existing job, isolated from user work.
ORIGIN_REPLAY = "replay"


@dataclass(frozen=True)
class ExecutionClass:
    name: str
    priority: int          # higher = scheduled sooner
    default_concurrency: int  # max concurrently running; 0 = unbounded


# Small, justified set. Interactive (light, user-visible) is never starved by the
# heavy artifact class; validation is heavier still; maintenance/replay is lowest
# and isolated so operator re-runs never compete with live user work.
INTERACTIVE = ExecutionClass("interactive", 100, 0)
ARTIFACT = ExecutionClass("artifact", 50, 2)
VALIDATION = ExecutionClass("validation", 40, 1)
MAINTENANCE = ExecutionClass("maintenance", 10, 1)

_CLASSES = {c.name: c for c in (INTERACTIVE, ARTIFACT, VALIDATION, MAINTENANCE)}

# Job kind -> class. Unknown kinds default to interactive (light) — heavy work is
# opted into a heavier class explicitly, never the other way around.
_KIND_TO_CLASS = {
    "artifact": ARTIFACT,
    "startup_validation": VALIDATION,
    "runtime_validation": VALIDATION,
}


def class_for(kind: str, origin: Optional[str] = None) -> ExecutionClass:
    """The execution class for a job. Operator replay is always maintenance-class
    (low, isolated) regardless of the underlying kind, so re-runs never jump the
    queue ahead of users."""
    if origin == ORIGIN_REPLAY:
        return MAINTENANCE
    return _KIND_TO_CLASS.get(kind, INTERACTIVE)


def get_class(name: Optional[str]) -> ExecutionClass:
    return _CLASSES.get(name or "", INTERACTIVE)


def concurrency_cap(exec_class: ExecutionClass, settings: Any) -> int:
    """Per-class concurrency cap (0 = unbounded). Operator-tunable per class via
    `queue_concurrency_<class>`; falls back to the class default."""
    override = getattr(settings, f"queue_concurrency_{exec_class.name}", None)
    cap = exec_class.default_concurrency if override is None else override
    return max(0, int(cap))


def per_owner_cap(settings: Any) -> int:
    """Max jobs one owner may have running at once (fairness; always >= 1)."""
    return max(1, int(getattr(settings, "queue_per_owner_inflight_cap", 3)))


def scheduling_enabled(settings: Any) -> bool:
    return bool(getattr(settings, "queue_scheduling_enabled", True))


def validate_policy(settings: Any) -> None:
    """Fail clearly on invalid policy config; safe to call at startup."""
    for exec_class in _CLASSES.values():
        raw = getattr(settings, f"queue_concurrency_{exec_class.name}", None)
        if raw is not None and int(raw) < 0:
            raise ValueError(f"queue_concurrency_{exec_class.name} must be >= 0")
    if int(getattr(settings, "queue_per_owner_inflight_cap", 3)) < 1:
        raise ValueError("queue_per_owner_inflight_cap must be >= 1")


def blocked_classes(running_class_counts: dict[str, int], settings: Any) -> set[str]:
    """Classes whose concurrency cap is currently reached (excluded from claim)."""
    blocked: set[str] = set()
    for name, exec_class in _CLASSES.items():
        cap = concurrency_cap(exec_class, settings)
        if cap > 0 and running_class_counts.get(name, 0) >= cap:
            blocked.add(name)
    return blocked


def blocked_owners(running_owner_counts: dict[str, int], settings: Any) -> set[str]:
    """Owners already running their fair share (excluded so others proceed)."""
    cap = per_owner_cap(settings)
    return {owner for owner, count in running_owner_counts.items() if count >= cap}
