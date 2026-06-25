# File: backend/app/chat_context.py
"""
Chat context handoff — bring prior work back into the conversation, explicitly.

A small, server-backed reference model: the user picks accessible documents,
artifacts, or runs from the active scope and "uses them in chat". Each reference
is resolved against the already owner-scoped readers (so it inherits the access
model and can never attach another scope's work), kept as ONE clean, UI-ready
item, and parked — now as an ordered, deduplicated LIST — on the chat session so
the composer can show calm pills and prefill an honest starter. No file contents
in the browser, no blobs in the URL, no owner keys — just references plus honest
intended actions.

The action (and a short role) stays semantically honest per resource:
  * document → use_as_context   ("source doc"; grounds the answer, never "continued")
  * artifact → revise           ("artifact to revise"; richer version, never "resumed")
  * run      → resume / continue_from / retry  ("prior run"; delegates to run
               history, which already distinguishes a pending run from a
               completed or failed one — we never pretend a finished run resumes).

Context is single-use for the next turn (the supervisor consumes the whole list
at turn start), but the user stays in control: the message they type still leads,
the attachments only help. Durable bundles (`app/bundles.py`) save a useful
combination of these references for later — references only, never payloads.
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
_MAX_ITEMS = 8  # calm cap — a context bundle, not a file tray
_TYPE_TO_KIND = {"PPTX": "pptx", "DOCX": "docx", "XLSX": "xlsx"}
_ROLE = {REF_DOCUMENT: "source doc", REF_ARTIFACT: "artifact to revise", REF_RUN: "prior run"}
# Run continuation mode (run_history) -> chat-context action (kept distinct).
_RUN_MODE_TO_ACTION = {
    "resume": ACTION_RESUME,
    "continue": ACTION_CONTINUE_FROM,
    "retry": ACTION_RETRY,
}


class ChatContextService:
    # ── storage (an ordered, deduped list parked on the session) ──────────────

    def _load(self, owner: Optional[str], session_id: Optional[str]) -> list[dict[str, Any]]:
        raw = session_memory.value(owner, session_id, _SESSION_KEY)
        return [i for i in raw if isinstance(i, dict)] if isinstance(raw, list) else []

    def _save(self, owner: Optional[str], session_id: Optional[str], items: list[dict[str, Any]]) -> None:
        session_memory.note(owner, session_id, _SESSION_KEY, items or None)

    # ── attach / inspect / remove ─────────────────────────────────────────────

    def attach(
        self,
        owner: str,
        session_id: Optional[str],
        ref_type: str,
        ref_id: str,
        db: Any = None,
    ) -> Optional[dict[str, Any]]:
        """Resolve a reference in the active scope and append it (deduped) to the
        session's attached context. Returns the clean item, or None when the
        resource isn't accessible here — an inaccessible / cross-scope item never
        attaches and never leaks."""
        if not owner or not ref_id:
            return None
        item = self._resolve(owner, session_id, ref_type, ref_id, db)
        if item is None:
            return None
        items = self._load(owner, session_id)
        if not any(i["ref_type"] == item["ref_type"] and i["ref_id"] == item["ref_id"] for i in items):
            items.append(item)
            self._save(owner, session_id, items[:_MAX_ITEMS])
        return item

    def attach_many(
        self,
        owner: str,
        session_id: Optional[str],
        refs: list[dict[str, str]],
        db: Any = None,
    ) -> dict[str, Any]:
        """Attach several references at once. Returns the resolved-and-stored list
        plus a count of any that couldn't be attached (inaccessible/unknown)."""
        attached = 0
        for ref in refs or []:
            if self.attach(owner, session_id, ref.get("ref_type", ""), ref.get("ref_id", ""), db=db) is not None:
                attached += 1
        items = self.items(owner, session_id)
        return {"items": items, "attached": attached, "skipped": max(0, len(refs or []) - attached)}

    def items(self, owner: Optional[str], session_id: Optional[str]) -> list[dict[str, Any]]:
        return self._load(owner, session_id)

    def current(self, owner: Optional[str], session_id: Optional[str]) -> Optional[dict[str, Any]]:
        """The primary (first) attached item, or None — kept for single-item call
        sites; multi-item callers use `items()`."""
        items = self._load(owner, session_id)
        return items[0] if items else None

    def remove(self, owner: Optional[str], session_id: Optional[str], ref_type: str, ref_id: str) -> bool:
        items = self._load(owner, session_id)
        kept = [i for i in items if not (i["ref_type"] == ref_type and i["ref_id"] == ref_id)]
        if len(kept) == len(items):
            return False
        self._save(owner, session_id, kept)
        return True

    def clear(self, owner: Optional[str], session_id: Optional[str]) -> None:
        self._save(owner, session_id, [])

    def consume(self, owner: Optional[str], session_id: Optional[str]) -> list[dict[str, Any]]:
        """Read the whole list and clear it — context applies to the next turn only."""
        items = self._load(owner, session_id)
        if items:
            self.clear(owner, session_id)
        return items

    @staticmethod
    def primary_prompt(items: list[dict[str, Any]]) -> str:
        """The composer prefill: the first item that carries an actionable starter
        (a run continuation or an artifact revise). Documents ground silently."""
        for item in items:
            if item.get("prompt"):
                return item["prompt"]
        return ""

    # ── resolvers (each owner-scoped; reuse the clean readers) ────────────────

    def _resolve(
        self, owner: str, session_id: Optional[str], ref_type: str, ref_id: str, db: Any
    ) -> Optional[dict[str, Any]]:
        if ref_type == REF_DOCUMENT:
            return self._document_context(owner, ref_id, db)
        if ref_type == REF_ARTIFACT:
            return self._artifact_context(owner, session_id, ref_id)
        if ref_type == REF_RUN:
            return self._run_context(owner, ref_id, db)
        return None

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
            "role": _ROLE[REF_DOCUMENT],
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
            "role": _ROLE[REF_ARTIFACT],
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
            "role": _ROLE[REF_RUN],
            "summary": run.get("summary") or "Pick up this run in chat",
            "prompt": prepared["prompt"],
        }


chat_context_service = ChatContextService()
