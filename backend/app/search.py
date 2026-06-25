# File: backend/app/search.py
"""
Scoped search — find the right prior work fast, without a file manager.

A thin, read-only composition over stores that are already owner-scoped, so it
inherits the access model for free and adds no new storage: it scans the active
scope's artifacts, documents, runs, and activity, filters by a simple
case-insensitive query, and returns one clean, relevance-first result list. Never
raw trace dumps, owner keys, DB rows, vector internals, or payload blobs — only
UI-ready fields, with a pin reference and a continue/resume affordance where the
underlying resource supports one.

Active-scope only and permission-aware (the route resolves the scope and checks
`view`); a non-member silently searches their own personal scope, never another
team's work. Richer filters / ranking / cross-resource search layer on top of this
without changing the call sites.
"""

from __future__ import annotations

from typing import Any, Optional

from app.activity import activity_service
from app.pins import REF_ARTIFACT, REF_DOCUMENT, REF_RUN
from app.run_history import run_history_service
from app.shared_resources import shared_resource_service

# Which resource families to search; the route can narrow via `?type=`.
KIND_ARTIFACT = "artifact"
KIND_DOCUMENT = "document"
KIND_RUN = "run"
KIND_ACTIVITY = "activity"
_ALL_KINDS = (KIND_ARTIFACT, KIND_DOCUMENT, KIND_RUN, KIND_ACTIVITY)

_SCAN = 50  # generous tail to filter from; results are then capped


def _matches(query: str, *fields: Optional[str]) -> bool:
    q = query.strip().lower()
    if not q:
        return True  # empty query lists the scope's recent work
    return any(q in (f or "").lower() for f in fields)


class SearchService:
    def search(
        self,
        owner: str,
        query: str,
        db: Any = None,
        *,
        kinds: Optional[list[str]] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        wanted = set(kinds) if kinds else set(_ALL_KINDS)
        results: list[dict[str, Any]] = []

        if KIND_ARTIFACT in wanted:
            for art in shared_resource_service.recent_artifacts(owner, limit=_SCAN):
                if _matches(query, art["title"], art["filename"], art["type"]):
                    results.append({
                        "result_type": KIND_ARTIFACT,
                        "title": art["title"],
                        "summary": f"{art['type']} artifact" + (f" · {art['size']}" if art.get("size") else ""),
                        "status": "completed",
                        "created_at": art["created_at"],
                        "download_url": art["download_url"],
                        "ref_type": REF_ARTIFACT,
                        "ref_id": art["filename"],
                    })

        if KIND_DOCUMENT in wanted and db is not None:
            for doc in shared_resource_service.recent_documents(owner, db, limit=_SCAN):
                if _matches(query, doc["name"], doc["type"]):
                    results.append({
                        "result_type": KIND_DOCUMENT,
                        "title": doc["name"],
                        "summary": f"{doc['type']} document · {doc['chunks']} chunk{'' if doc['chunks'] == 1 else 's'}",
                        "status": None,
                        "created_at": doc["created_at"],
                        "download_url": None,
                        "ref_type": REF_DOCUMENT,
                        "ref_id": doc["name"],
                    })

        if KIND_RUN in wanted:
            for run in run_history_service.recent(owner, db=db, limit=_SCAN):
                if _matches(query, run["title"], run["summary"], run["status"]):
                    results.append({
                        "result_type": KIND_RUN,
                        "title": run["title"],
                        "summary": run["summary"],
                        "status": run["status"],
                        "created_at": run["created_at"],
                        "download_url": run["download_url"],
                        "ref_type": REF_RUN,
                        "ref_id": run["id"],
                        "run_kind": run["kind"],       # resume | continue | retry
                        "action": run["action"],       # Resume | Continue | Retry
                        "resumable": run["resumable"],
                    })

        if KIND_ACTIVITY in wanted:
            for ev in activity_service.recent(owner, limit=_SCAN):
                if _matches(query, ev["title"], ev["type"]):
                    results.append({
                        "result_type": KIND_ACTIVITY,
                        "title": ev["title"],
                        "summary": (ev.get("actor") + " · " if ev.get("actor") else "") + "activity",
                        "status": ev["status"],
                        "created_at": ev["created_at"],
                        "download_url": None,
                        # Activity is a feed, not a stable resource — not pinnable.
                    })

        # Newest first across families (None times sort last).
        results.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        return results[:limit]


search_service = SearchService()
