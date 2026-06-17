# File: backend/app/shared_resources.py
"""
Shared-resource listing for the active scope (personal or workspace).

A small, read-only view over resources that already exist and are already
owner-scoped — artifacts on disk, document rows, and turn traces — so workspace
members can discover what's there without deep links, and a solo user sees their
own recent items. Returns only premium, minimal metadata: never owner keys, raw
rows, trace dumps, or vector internals. The opaque capability token in a download
URL is the same one the access-controlled `/artifacts/...` route already uses.

This is intentionally a thin reader: no new storage, no migration of the owner
model. It composes the existing scoped stores, so richer shared history / search
layers on later without changing it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.auth import owner_token_for
from app.core.config import settings
from app.db.models import Document
from app.services.trace_service import TraceService

# Friendly run labels — task/result oriented, never internal mode strings.
_RUN_LABELS = {
    "general_chat": "Conversation",
    "self_memory": "Conversation",
    "web_research": "Web research",
    "document_qa": "Document answer",
    "execution": "Workflow run",
    "execution_planning": "Plan prepared",
    "research_then_execution": "Research & build",
    "multi_question": "Multi-task",
}
_DOC_TYPES = {"pdf": "PDF", "docx": "DOCX", "txt": "Text", "md": "Markdown"}
_ARTIFACT_TYPES = {".pptx": "PPTX", ".docx": "DOCX", ".xlsx": "XLSX"}


def _human_size(num: int) -> Optional[str]:
    if not num:
        return None
    if num < 1024:
        return f"{num} B"
    if num < 1024 * 1024:
        return f"{num / 1024:.0f} KB"
    return f"{num / 1024 / 1024:.1f} MB"


def _titleize(filename: str) -> str:
    stem = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    return stem[:1].upper() + stem[1:] if stem else filename


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


class SharedResourceService:
    def __init__(self, tracer: Optional[TraceService] = None) -> None:
        self._tracer = tracer or TraceService()

    # ── artifacts (files on disk, owner-token directory) ─────────────────────

    def recent_artifacts(self, owner: str, limit: int = 8) -> list[dict[str, Any]]:
        token = owner_token_for(owner)
        owner_dir = (Path(settings.artifacts_dir).resolve() / token)
        if not owner_dir.is_dir():
            return []
        files = [p for p in owner_dir.iterdir() if p.is_file() and p.suffix.lower() in _ARTIFACT_TYPES]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        out: list[dict[str, Any]] = []
        for path in files[:limit]:
            stat = path.stat()
            out.append({
                "title": _titleize(path.name),
                "filename": path.name,
                "type": _ARTIFACT_TYPES.get(path.suffix.lower(), "FILE"),
                "size": _human_size(stat.st_size),
                "created_at": _iso(stat.st_mtime),
                # Same opaque, access-controlled capability URL as a normal download.
                "download_url": f"/artifacts/{token}/{path.name}",
            })
        return out

    # ── documents (scoped rows; retrieval stays in the vector store) ─────────

    def recent_documents(self, owner: str, db, limit: int = 8) -> list[dict[str, Any]]:
        try:
            rows = (
                db.query(Document)
                .filter(Document.owner == owner)
                .order_by(Document.created_at.desc())
                .limit(limit)
                .all()
            )
        except Exception:
            return []
        return [
            {
                "name": row.original_filename,
                "type": _DOC_TYPES.get((row.file_type or "").lower(), (row.file_type or "file").upper()),
                "chunks": row.chunk_count,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]

    # ── runs (lightweight history from traces, owner-scoped) ──────────────────

    def recent_runs(self, owner: str, limit: int = 8) -> list[dict[str, Any]]:
        # Scan a generous tail and keep only this scope's runs (newest first).
        records = self._tracer.recent(limit=300)
        scoped = [r for r in records if r.get("owner") == owner]
        out: list[dict[str, Any]] = []
        for record in reversed(scoped[-limit:]):
            mode = record.get("mode") or ""
            out.append({
                "label": _RUN_LABELS.get(mode, "Run"),
                "status": record.get("final_status") or "completed",
                "source": record.get("source_type"),
                "created_at": record.get("created_at"),
            })
        return out


shared_resource_service = SharedResourceService()
