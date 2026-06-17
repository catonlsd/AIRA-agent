# File: backend/app/chat_context.py
"""
Chat context handoff — bring prior work back into the conversation, explicitly.

A small, server-backed reference model: the user picks an accessible document,
artifact, or run from the active scope and "uses it in chat". This resolves the
reference against the already owner-scoped readers (so it inherits the access
model and can never attach another scope's work), produces ONE clean, UI-ready
context object, and parks it on the chat session so the composer can show a calm
pill and prefill an honest starter. No file contents in the browser, no blobs in
the URL, no owner keys — just a reference plus an honest intended action.

The action stays semantically honest per resource:
  * document → use_as_context   (grounds the next answer; never "continued")
  * artifact → revise           (regenerates a richer version; never "resumed")
  * run      → resume / continue_from / retry  (delegates to run history, which
               already distinguishes a genuinely pending run from a completed or
               failed one — we never pretend a finished run is resumable).

Context is single-use for the next turn (the supervisor consumes it at turn
start), but the user stays in control: the message they type still leads, the
attachment only helps. Multi-item context packs and richer revision flows layer
on this reference model without changing the call sites.
"""

from __future__ import annotations

from typing import Any, Optional

from app.memory.session_memory import session_memory
from app.run_history import run_history_service
from app.shared_resources import shared_resource_service

# Resource families a user can hand off (a pin resolves to one of these).
REF_DOCUMENT = "document"
REF_ARTIFACT = "artifact"
REF_RUN = "run"

# Honest intended actions (never blurred — see module docstring).
ACTION_USE_AS_CONTEXT = "use_as_context"
ACTION_REVISE = "revise"
ACTION_CONTINUE_FROM = "continue_from"
ACTION_RETRY = "retry"
ACTION_RESUME = "resume"

_SESSION_KEY = "attached_context"
_TYPE_TO_KIND = {"PPTX": "pptx", "DOCX": "docx", "XLSX": "xlsx"}
# Run continuation mode (run_history) -> chat-context action (kept distinct).
_RUN_MODE_TO_ACTION = {
    "resume": ACTION_RESUME,
    "continue": ACTION_CONTINUE_FROM,
    "retry": ACTION_RETRY,
}


class ChatContextService:
    def attach(
        self,
        owner: str,
        session_id: Optional[str],
        ref_type: str,
        ref_id: str,
        db: Any = None,
    ) -> Optional[dict[str, Any]]:
        """Resolve a reference in the active scope and park a clean context object
        on the session. Returns None when the resource isn't accessible here, so an
        inaccessible / cross-scope item never attaches and never leaks."""
        if not owner or not ref_id:
            return None
        if ref_type == REF_DOCUMENT:
            context = self._document_context(owner, ref_id, db)
        elif ref_type == REF_ARTIFACT:
            context = self._artifact_context(owner, session_id, ref_id)
        elif ref_type == REF_RUN:
            context = self._run_context(owner, ref_id, db)
        else:
            return None
        if context is None:
            return None
        session_memory.note(owner, session_id, _SESSION_KEY, context)
        return context

    def current(self, owner: Optional[str], session_id: Optional[str]) -> Optional[dict[str, Any]]:
        ctx = session_memory.value(owner, session_id, _SESSION_KEY)
        return ctx if isinstance(ctx, dict) else None

    def clear(self, owner: Optional[str], session_id: Optional[str]) -> None:
        session_memory.note(owner, session_id, _SESSION_KEY, None)

    def consume(self, owner: Optional[str], session_id: Optional[str]) -> Optional[dict[str, Any]]:
        """Read and clear — context applies to the next turn only."""
        ctx = self.current(owner, session_id)
        if ctx is not None:
            self.clear(owner, session_id)
        return ctx

    # ── resolvers (each owner-scoped; reuse the clean readers) ────────────────

    def _document_context(self, owner: str, ref_id: str, db: Any) -> Optional[dict[str, Any]]:
        if db is None:
            return None
        doc = next(
            (d for d in shared_resource_service.recent_documents(owner, db, limit=200) if d["name"] == ref_id),
            None,
        )
        if doc is None:
            return None
        return {
            "ref_type": REF_DOCUMENT,
            "ref_id": ref_id,
            "title": doc["name"],
            "action": ACTION_USE_AS_CONTEXT,
            "summary": f"{doc['type']} document · grounds your next answer",
            "prompt": "",  # the user's question leads; the document grounds it
        }

    def _artifact_context(self, owner: str, session_id: Optional[str], ref_id: str) -> Optional[dict[str, Any]]:
        art = next(
            (a for a in shared_resource_service.recent_artifacts(owner, limit=200) if a["filename"] == ref_id),
            None,
        )
        if art is None:
            return None
        kind = _TYPE_TO_KIND.get(art["type"], "pptx")
        title = art["title"]
        # Seed the existing revision rail so the next revise-style turn regenerates
        # a richer version of THIS artifact (honest reuse, not a fake resume).
        session_memory.note(owner, session_id, "last_artifact", {"kind": kind, "goal": title, "title": title})
        return {
            "ref_type": REF_ARTIFACT,
            "ref_id": ref_id,
            "title": title,
            "action": ACTION_REVISE,
            "summary": f"{art['type']} artifact · revise into a richer version",
            "prompt": f'Revise "{title}": add more detail and a relevant image to each slide.',
            "download_url": art["download_url"],
        }

    def _run_context(self, owner: str, ref_id: str, db: Any) -> Optional[dict[str, Any]]:
        prepared = run_history_service.continuation_for(owner, ref_id, db=db)
        if prepared is None:
            return None
        run = run_history_service.get(owner, ref_id, db=db) or {}
        action = _RUN_MODE_TO_ACTION.get(prepared["mode"], ACTION_CONTINUE_FROM)
        return {
            "ref_type": REF_RUN,
            "ref_id": ref_id,
            "title": prepared["title"],
            "action": action,
            "summary": run.get("summary") or "Pick up this run in chat",
            "prompt": prepared["prompt"],
        }


chat_context_service = ChatContextService()
