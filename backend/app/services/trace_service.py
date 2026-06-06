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

# Maps a routed mode to the kind of source of truth the answer drew on.
_SOURCE_TYPE_BY_MODE = {
    "general_chat": "model",
    "self_memory": "model",
    "clarification": "model",
    "web_research": "web",
    "document_qa": "documents",
    "execution": "tools",
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
        trace_events: Optional[list[dict]] = None,
        tokens: Optional[int] = None,
        source_type: Optional[str] = None,
    ) -> dict[str, Any]:
        return {
            "created_at": _utc_now_iso(),
            "session_id": session_id,
            "run_id": run_id,
            "mode": mode,
            "route": mode,
            "source_type": source_type or source_type_for_mode(mode),
            "latency_ms": latency_ms,
            "tokens": tokens,
            "final_status": final_status,
            "trace_events": trace_events or [],
        }

    def persist(self, record: dict[str, Any]) -> bool:
        """Append one trace record. Best-effort: never raises."""
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(record, default=str)
            with _LOCK:
                with self.log_path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            return True
        except Exception:
            return False

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
