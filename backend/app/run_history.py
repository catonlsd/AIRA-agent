# File: backend/app/run_history.py
"""
Scoped run history — "pick up where we left off", honestly.

A thin, read-only composition over stores that are already owner-scoped, so it
inherits the access model for free and adds no new storage:

  * genuinely **resumable** runs  ← pending guided flows (artifact / plan) that
    are awaiting the user's approval. Resuming one really claims and continues it.
  * **continuable** runs          ← completed artifacts on disk. "Continue" seeds
    a fresh, on-topic turn from the prior output's context — it never pretends the
    internal execution state still exists.
  * **failed** runs               ← recent failure activity, surfaced honestly so
    a user can retry, never as a raw error blob.

It returns only UI-ready metadata (title, status, kind, resumable flag, a concise
summary, an optional artifact link, time) — never workflow internals, tool
payloads, trace blobs, raw rows, or owner keys. Continuation is permission-checked
at the moment it runs: a run that isn't in the active scope is simply not found,
so its existence never leaks. Resume vs continue vs retry stay distinct.

Future richer history / search / activity-linked detail layer on top of this
without changing the call sites.
"""

from __future__ import annotations

from typing import Any, Optional

from app.activity import ARTIFACT_FAILED, RUN_FAILED, activity_service
from app.guided_flow_store import guided_flow_store
from app.shared_resources import shared_resource_service

# Only flows with clean approve/continue semantics surface as resumable runs.
# (Runtime micro-confirmations and mid-turn clarifications are not "runs you pick
# up later" — keeping them out keeps the surface calm and the resume honest.)
_RESUMABLE_KINDS = ("artifact", "plan")

# The exact phrase the supervisor's approval parser accepts — so "Resume" really
# claims the pending flow rather than starting a new turn.
_RESUME_PROMPT = "Approve"

_SUFFIX_NOUN = {".pptx": "presentation", ".docx": "document", ".xlsx": "spreadsheet"}


def _clip(text: str, limit: int = 90) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _pending_title(kind: str, data: dict[str, Any]) -> str:
    goal = _clip(str(data.get("goal") or data.get("original_request") or ""), 70)
    if kind == "artifact":
        noun = (str(data.get("kind") or "file")).upper()
        return f"{noun} awaiting your approval" + (f" — {goal}" if goal else "")
    return "Plan awaiting your approval" + (f" — {goal}" if goal else "")


class RunHistoryService:
    """Composes resumable + continuable + failed runs for one owner key."""

    def recent(self, owner: str, db: Any = None, limit: int = 6) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []

        # 1) Resumable: pending flows awaiting approval (most actionable, first).
        for flow in guided_flow_store.list_pending(owner):
            if flow["kind"] not in _RESUMABLE_KINDS:
                continue
            data = flow.get("data") or {}
            runs.append({
                "id": f"pending:{flow['kind']}",
                "kind": "resume",
                "title": _pending_title(flow["kind"], data),
                "status": "requires_approval",
                "summary": "Paused for your go-ahead — resume to finish it.",
                "resumable": True,
                "action": "Resume",
                "download_url": None,
                "created_at": flow.get("created_at"),
            })

        # 2) Continuable: completed artifacts (clean title + type + link).
        for art in shared_resource_service.recent_artifacts(owner, limit=limit):
            runs.append({
                "id": f"artifact:{art['filename']}",
                "kind": "continue",
                "title": art["title"],
                "status": "completed",
                "summary": f"Finished {art['type']} — continue to build on it.",
                "resumable": False,
                "action": "Continue",
                "download_url": art["download_url"],
                "created_at": art["created_at"],
            })

        # 3) Failed: surfaced honestly from activity so a retry is one click away.
        failures = activity_service.recent(owner, limit=limit, types=[RUN_FAILED, ARTIFACT_FAILED])
        for i, ev in enumerate(failures):
            runs.append({
                "id": f"failed:{i}",
                "kind": "retry",
                "title": ev["title"],
                "status": "failed",
                "summary": "Didn't complete — retry with the same goal.",
                "resumable": False,
                "action": "Retry",
                "download_url": None,
                "created_at": ev.get("created_at"),
            })

        return runs[:limit]

    def get(self, owner: str, run_id: str, db: Any = None) -> Optional[dict[str, Any]]:
        """A single run's clean summary, scoped to this owner. Returns None when
        the run isn't in the active scope — its existence never leaks."""
        for run in self.recent(owner, db=db, limit=50):
            if run["id"] == run_id:
                return run
        return None

    def continuation_for(self, owner: str, run_id: str, db: Any = None) -> Optional[dict[str, Any]]:
        """Prepare a permission-checked continuation for an accessible run.

        Returns the honest mode + the exact chat prompt to send — `resume` claims
        a pending flow, `continue` seeds a fresh on-topic build, `retry` re-runs a
        failed goal. None when the run isn't accessible in this scope (no leak)."""
        run = self.get(owner, run_id, db=db)
        if run is None:
            return None
        kind = run["kind"]
        if kind == "resume":
            prompt = _RESUME_PROMPT
        elif kind == "retry":
            prompt = f'Try that again: {run["title"]}. Pick up from where it failed and fix it.'
        else:  # continue — derive the artifact noun from the filename, not prose
            suffix = run_id[run_id.rfind("."):].lower() if "." in run_id else ""
            noun = _SUFFIX_NOUN.get(suffix, "file")
            prompt = (
                f'Continue building on the {noun} "{run["title"]}" — make a new {noun} '
                "that expands it with more depth, detail, and supporting visuals."
            )
        return {"mode": kind, "run_id": run_id, "prompt": prompt, "title": run["title"]}


run_history_service = RunHistoryService()
