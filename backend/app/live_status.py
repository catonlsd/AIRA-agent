# File: backend/app/live_status.py
"""
Unified live status — one calm phase model for inline AND queued work.

Inline turns stream SSE phases that live only while the request is open; queued
jobs are durable but only carried a freeform progress string. This service is the
seam that makes them feel like one product: it maps a durable job's lifecycle into
the SAME curated, user-facing phase vocabulary the streaming presenter uses
(`planning`, `executing`, `validating`, `working in the background`, `completed`,
`canceled`, …) — never raw worker/queue/trace internals.

Because the `ExecutionJob` row IS the durable snapshot, "reconnect-safe" needs no
event backplane: a client that reloads simply re-reads the snapshot and resumes
the right phase, and a job that already finished resolves to its honest terminal
phase (never fake resumed progress). Scope/ownership is inherited from the queue's
own `get`/`recent`, so a snapshot only ever exposes work the caller may see.

`RunLiveStatus` (the dict shape) is the conceptual channel both inline and queued
work map into, so richer resumable streams / multi-device continuity layer on
later without changing call sites.
"""

from __future__ import annotations

from typing import Any, Optional

from app.execution_queue import execution_queue

# Status -> (phase key, calm label, tone). Labels MUST match the frontend
# streaming presenter so inline and queued work read identically.
_JOB_PHASE: dict[str, tuple[str, str, str]] = {
    "queued": ("queued", "Queued", "active"),
    "running": ("working_background", "Working in the background", "active"),
    "validating": ("validating", "Running validation", "active"),
    "repairing": ("repairing", "Repairing an issue", "warn"),
    "awaiting_approval": ("awaiting_approval", "Waiting for your approval", "warn"),
    "cancel_requested": ("canceling", "Canceling", "warn"),
    "canceled": ("canceled", "Canceled", "warn"),
    "completed": ("completed", "Completed", "good"),
    "failed": ("failed", "Could not complete", "bad"),
}
_DEFAULT_PHASE = ("working_background", "Working in the background", "active")
_TERMINAL = {"completed", "failed", "canceled"}


def job_phase(status: str, *, origin: Optional[str] = None) -> dict[str, str]:
    """The unified phase for a job status — a freshly-queued *retry* reads as
    'Retrying' so a re-run is honest, not indistinguishable from a first attempt."""
    if status == "queued" and origin == "retry":
        return {"key": "retrying", "label": "Retrying", "tone": "active"}
    key, label, tone = _JOB_PHASE.get(status, _DEFAULT_PHASE)
    return {"key": key, "label": label, "tone": tone}


def enrich_phase(job: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Add the unified `phase` to a clean job dict (in place) for the API layer."""
    if job is None:
        return None
    job["phase"] = job_phase(job.get("status", ""), origin=job.get("origin"))
    return job


def live_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    """A clean, unified RunLiveStatus for one job — what a reconnecting client
    reads to resume. UI-ready only: phase, state, and the same result the job
    already exposes. Never worker ids, offsets, queue internals, or owner keys."""
    status = job.get("status", "")
    return {
        "id": job.get("id"),
        "kind": "job",
        "state": "terminal" if status in _TERMINAL else "active",
        "status": status,
        "phase": job_phase(status, origin=job.get("origin")),
        "title": job.get("title"),
        "result": job.get("result"),
        "can_cancel": job.get("can_cancel", False),
        "can_retry": job.get("can_retry", False),
        "updated_at": job.get("updated_at"),
    }


class LiveStatusService:
    """Reconnect-safe snapshots over the durable queue (scope inherited from it)."""

    def snapshot(self, owner: str, job_id: str) -> Optional[dict[str, Any]]:
        job = execution_queue.get(owner, job_id)  # scope-checked; None if not visible
        return live_snapshot(job) if job is not None else None

    def active(self, owner: Optional[str], *, limit: int = 10) -> list[dict[str, Any]]:
        """Active (non-terminal) work in scope — what a reconnecting client lists
        to restore an in-flight live view."""
        return [live_snapshot(j) for j in execution_queue.recent(owner, limit=limit, active_only=True)]


live_status_service = LiveStatusService()
