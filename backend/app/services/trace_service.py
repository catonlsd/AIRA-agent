# File: backend/app/services/trace_service.py
"""
Turn tracing + persistence.

Every chat turn is persisted as one structured record so debugging, evals, and
version comparison have reliable ground truth. Tracing must never affect the
turn itself: all writes are best-effort and swallow their own errors.

Storage is an append-only JSONL log (consistent with the workflow store). The
path is the env var ``AIRA_TRACE_LOG`` if set, else ``storage/traces.jsonl``.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_DEFAULT_TRACE_PATH = "./storage/traces.jsonl"
_LOCK = threading.Lock()
# Rotate the trace log once it exceeds this size so it never grows unbounded.
_MAX_TRACE_BYTES = 5 * 1024 * 1024

# Maps a routed mode to the kind of source of truth the answer drew on.
_SOURCE_TYPE_BY_MODE = {
    "general_chat": "model",
    "self_memory": "model",
    "clarification": "model",
    "web_research": "web",
    "document_qa": "documents",
    "execution": "tools",
    "execution_planning": "model",
    "research_then_execution": "tools",
    "multi_question": "mixed",
    "approval_resume": "tools",
}


def source_type_for_mode(mode: Optional[str]) -> str:
    return _SOURCE_TYPE_BY_MODE.get(mode or "", "unknown")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TraceService:
    def __init__(self, log_path: Optional[str] = None) -> None:
        self.log_path = Path(
            log_path or os.getenv("AIRA_TRACE_LOG") or _DEFAULT_TRACE_PATH
        )

    def build_record(
        self,
        *,
        session_id: Optional[str],
        run_id: Optional[str],
        mode: Optional[str],
        latency_ms: float,
        final_status: Optional[str],
        owner: Optional[str] = None,
        trace_events: Optional[list[dict]] = None,
        tokens: Optional[int] = None,
        source_type: Optional[str] = None,
        conversation_type: Optional[str] = None,
        selected_route: Optional[str] = None,
        candidate_routes: Optional[dict[str, float]] = None,
        confidence: Optional[float] = None,
        clarification_needed: Optional[bool] = None,
        capabilities_used: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        record = {
            "created_at": _utc_now_iso(),
            "session_id": session_id,
            "run_id": run_id,
            "owner": owner,  # durable scope key — enables scope-filtered run history
            "mode": mode,
            "route": mode,
            "source_type": source_type or source_type_for_mode(mode),
            "latency_ms": latency_ms,
            "tokens": tokens,
            "final_status": final_status,
            "trace_events": trace_events or [],
        }
        # Supervisor-reasoning fields (Phase 2A). Additive and optional so older
        # records and readers keep working unchanged.
        if conversation_type is not None:
            record["conversation_type"] = conversation_type
        if selected_route is not None:
            record["selected_route"] = selected_route
        if candidate_routes is not None:
            record["candidate_routes"] = candidate_routes
        if confidence is not None:
            record["confidence"] = confidence
        if clarification_needed is not None:
            record["clarification_needed"] = clarification_needed
        if capabilities_used is not None:
            record["capabilities_used"] = capabilities_used
        return record

    def persist(self, record: dict[str, Any]) -> bool:
        """Append one trace record. Best-effort: never raises."""
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(record, default=str)
            with _LOCK:
                self._rotate_if_needed()
                with self.log_path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            return True
        except Exception:
            return False

    def _rotate_if_needed(self) -> None:
        try:
            if self.log_path.exists() and self.log_path.stat().st_size > _MAX_TRACE_BYTES:
                rotated = self.log_path.with_name(self.log_path.name + ".1")
                if rotated.exists():
                    rotated.unlink()
                self.log_path.rename(rotated)
        except Exception:
            pass

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recent trace records (newest last). Best-effort."""
        try:
            if not self.log_path.exists():
                return []
            with self.log_path.open("r", encoding="utf-8") as handle:
                lines = handle.readlines()
            records: list[dict[str, Any]] = []
            for line in lines[-limit:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return records
        except Exception:
            return []
