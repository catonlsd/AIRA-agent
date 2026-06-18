# File: backend/app/job_handlers.py
"""
Job handlers — the real work the worker runs off the request path.

Each handler takes a clean `JobView` (owner + scope + a reference payload) and
returns a clean, UI-ready result, recording activity/run-history exactly like the
inline path so worker-produced outcomes stay attributed and scope-correct. The
heavy work itself is unchanged — `ArtifactService.generate` still does generation
+ validation, so evidence-based completion and artifact validation are preserved;
we've only moved *where* it runs.

Handlers raise on failure so the queue's bounded-retry / honest-failed path owns
error reporting. They are registered once at import (`register_default_handlers`),
which both the API process and the worker call.
"""

from __future__ import annotations

from typing import Any

from app.activity import ARTIFACT_CREATED, ARTIFACT_FAILED, RUN_COMPLETED, RUN_FAILED, activity_service
from app.artifacts.service import ArtifactService, _artifact_from_dict
from app.execution_queue import JobCanceled, execution_queue

JOB_ARTIFACT = "artifact"


def _artifact_handler(job) -> dict[str, Any]:
    """Generate + validate an approved artifact durably. Records the same activity
    the inline approval records, so run history / recent artifacts stay coherent."""
    pending = _artifact_from_dict(job.payload or {})
    # Cooperative cancel checkpoint: stop cleanly *before* the expensive generation
    # rather than force-killing mid-write. The queue records an honest `canceled`.
    if job.cancelled():
        raise JobCanceled()
    execution_queue.transition(job.id, "validating", progress="Generating & validating")
    outcome = ArtifactService().generate(pending)

    if outcome.get("status") != "completed":
        # Honest failure — recorded as activity, then raised so the queue marks the
        # job failed with a clean message (and applies bounded retry).
        activity_service.record(
            job.owner, ARTIFACT_FAILED, f"Couldn't generate a {pending.kind.upper()}",
            actor_id=job.actor_account_id, status="failed", resource_type="artifact",
        )
        activity_service.record(
            job.owner, RUN_FAILED, f"Background {pending.kind.upper()} run failed",
            actor_id=job.actor_account_id, status="failed",
        )
        raise RuntimeError(outcome.get("error", "artifact generation failed"))

    artifact = outcome["artifact"]
    title = artifact.get("title") or pending.kind.upper()
    activity_service.record(
        job.owner, ARTIFACT_CREATED, f"Created “{title}” ({pending.kind.upper()})",
        actor_id=job.actor_account_id, status="completed",
        resource_type="artifact", resource_id=artifact.get("filename"),
    )
    activity_service.record(
        job.owner, RUN_COMPLETED, f"Built “{title}” in the background",
        actor_id=job.actor_account_id, status="completed",
    )
    # Clean, UI-ready result only — never the spec, path, or internals.
    return {
        "title": title,
        "type": pending.kind.upper(),
        "filename": artifact.get("filename"),
        "download_url": artifact.get("download_url"),
        "summary": artifact.get("summary"),
    }


def register_default_handlers() -> None:
    execution_queue.register_handler(JOB_ARTIFACT, _artifact_handler)


register_default_handlers()
