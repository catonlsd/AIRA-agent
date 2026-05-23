import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, List, Any

from schemas.aira_state import AiraXState


class WorkflowStore:
    runs: Dict[str, AiraXState] = {}
    loaded: bool = False

    storage_file = (
        Path(__file__).resolve().parents[1]
        / "storage"
        / "workflow_runs.json"
    )

    final_statuses = {"completed", "failed", "rejected"}

    @classmethod
    def _utc_now_iso(cls) -> str:
        return datetime.now(timezone.utc).isoformat()

    @classmethod
    def _parse_datetime(cls, value: Optional[str]) -> datetime:
        if not value:
            return datetime.min.replace(tzinfo=timezone.utc)

        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)

        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)

    @classmethod
    def _is_final_status(cls, status: str) -> bool:
        return status in cls.final_statuses

    @classmethod
    def _touch_state_timestamps(cls, state: AiraXState) -> None:
        now = cls._utc_now_iso()

        if not getattr(state, "created_at", None):
            state.created_at = now

        state.updated_at = now

        if cls._is_final_status(state.status):
            if not getattr(state, "completed_at", None):
                state.completed_at = now
        else:
            state.completed_at = None

    @classmethod
    def _ensure_loaded(cls) -> None:
        if cls.loaded:
            return

        cls.storage_file.parent.mkdir(parents=True, exist_ok=True)

        if not cls.storage_file.exists():
            cls.storage_file.write_text("{}", encoding="utf-8")
            cls.loaded = True
            return

        try:
            raw_data = json.loads(cls.storage_file.read_text(encoding="utf-8"))

            for run_id, state_data in raw_data.items():
                try:
                    state = AiraXState.model_validate(state_data)

                    if not getattr(state, "created_at", None):
                        state.created_at = cls._utc_now_iso()

                    if not getattr(state, "updated_at", None):
                        state.updated_at = state.created_at

                    if (
                        cls._is_final_status(state.status)
                        and not getattr(state, "completed_at", None)
                    ):
                        state.completed_at = state.updated_at

                    cls.runs[run_id] = state
                except Exception:
                    continue

        except Exception:
            cls.runs = {}

        cls.loaded = True

    @classmethod
    def _persist(cls) -> None:
        cls.storage_file.parent.mkdir(parents=True, exist_ok=True)

        data = {
            run_id: state.model_dump()
            for run_id, state in cls.runs.items()
        }

        cls.storage_file.write_text(
            json.dumps(data, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def save(cls, state: AiraXState) -> None:
        cls._ensure_loaded()

        if state.run_id:
            cls._touch_state_timestamps(state)
            cls.runs[state.run_id] = state
            cls._persist()

    @classmethod
    def get(cls, run_id: str) -> Optional[AiraXState]:
        cls._ensure_loaded()

        return cls.runs.get(run_id)

    @classmethod
    def delete(cls, run_id: str) -> None:
        cls._ensure_loaded()

        if run_id in cls.runs:
            del cls.runs[run_id]
            cls._persist()

    @classmethod
    def list_runs(cls) -> List[Dict[str, Any]]:
        cls._ensure_loaded()

        summaries = []

        sorted_runs = sorted(
            cls.runs.items(),
            key=lambda item: cls._parse_datetime(
                getattr(item[1], "created_at", None)
            ),
        )

        for run_id, state in sorted_runs:
            approval_context = state.memory.get("approval_context", {})
            approval_resolution = state.memory.get("approval_resolution", {})
            approval_recovery_events = state.memory.get(
                "approval_recovery_events",
                [],
            )
            cleanup_actions = state.memory.get("cleanup_actions", [])

            summaries.append(
                {
                    "run_id": run_id,
                    "user_goal": state.user_goal,
                    "status": state.status,
                    "decision": state.decision,
                    "final_answer": state.final_answer,
                    "current_step": state.current_step,
                    "retry_count": state.retry_count,

                    "created_at": state.created_at,
                    "updated_at": state.updated_at,
                    "completed_at": state.completed_at,

                    "requires_approval": state.status == "requires_approval",
                    "pending_action": state.memory.get("pending_action"),

                    "approval_context": approval_context,
                    "approval_context_type": approval_context.get("type"),

                    "approval_in_progress": state.memory.get(
                        "approval_in_progress",
                        False,
                    ),
                    "approval_resolution": approval_resolution,
                    "approval_resolution_status": approval_resolution.get("status"),
                    "approval_resolution_action": approval_resolution.get("action"),

                    "approval_stale_recovered": state.memory.get(
                        "approval_stale_recovered",
                        False,
                    ),
                    "approval_recovery_events": approval_recovery_events,
                    "approval_recovery_count": len(approval_recovery_events),
                    "has_approval_recovery": len(approval_recovery_events) > 0,

                    "cleanup_actions": cleanup_actions,
                    "cleanup_count": len(cleanup_actions),
                    "has_cleanup": len(cleanup_actions) > 0,

                    "step_count": len(state.plan),
                    "log_count": len(state.memory.get("workflow_logs", [])),
                }
            )

        return summaries

    @classmethod
    def get_metrics(cls) -> Dict[str, Any]:
        cls._ensure_loaded()

        runs = list(cls.runs.values())

        completed = sum(1 for run in runs if run.status == "completed")
        failed = sum(1 for run in runs if run.status == "failed")
        requires_approval = sum(
            1 for run in runs if run.status == "requires_approval"
        )
        rejected = sum(1 for run in runs if run.status == "rejected")

        total_retries = sum(run.retry_count for run in runs)
        total_tool_calls = sum(len(run.execution_outputs) for run in runs)
        total_logs = sum(len(run.memory.get("workflow_logs", [])) for run in runs)

        cleanup_runs = sum(
            1 for run in runs if len(run.memory.get("cleanup_actions", [])) > 0
        )

        total_cleanup_actions = sum(
            len(run.memory.get("cleanup_actions", [])) for run in runs
        )

        git_write_preflight_runs = sum(
            1
            for run in runs
            if run.memory.get("approval_context", {}).get("type")
            == "git_write_preflight"
        )

        git_push_preflight_runs = sum(
            1
            for run in runs
            if run.memory.get("approval_context", {}).get("type")
            == "git_push_preflight"
        )

        git_preflight_runs = git_write_preflight_runs + git_push_preflight_runs

        approval_in_progress_runs = sum(
            1
            for run in runs
            if run.memory.get("approval_in_progress") is True
        )

        approval_resolved_runs = sum(
            1
            for run in runs
            if isinstance(run.memory.get("approval_resolution"), dict)
            and bool(run.memory.get("approval_resolution"))
        )

        approval_approved_runs = sum(
            1
            for run in runs
            if run.memory.get("approval_resolution", {}).get("status")
            == "approved"
        )

        approval_rejected_runs = sum(
            1
            for run in runs
            if run.memory.get("approval_resolution", {}).get("status")
            == "rejected"
        )

        approval_resume_failed_runs = sum(
            1
            for run in runs
            if run.memory.get("approval_resolution", {}).get("status")
            == "approved_but_resume_failed"
        )

        stale_approval_recovery_runs = sum(
            1
            for run in runs
            if run.memory.get("approval_stale_recovered") is True
            or run.memory.get("approval_resolution", {}).get("status")
            == "stale_processing_recovered"
        )

        total_approval_recovery_events = sum(
            len(run.memory.get("approval_recovery_events", []))
            for run in runs
        )

        latest_runs = sorted(
            cls.list_runs(),
            key=lambda run: cls._parse_datetime(run.get("updated_at")),
        )[-5:]

        return {
            "total_runs": len(runs),
            "completed_runs": completed,
            "failed_runs": failed,
            "requires_approval_runs": requires_approval,
            "rejected_runs": rejected,

            "total_retries": total_retries,
            "total_tool_calls": total_tool_calls,
            "total_logs": total_logs,

            "git_preflight_runs": git_preflight_runs,
            "git_write_preflight_runs": git_write_preflight_runs,
            "git_push_preflight_runs": git_push_preflight_runs,

            "cleanup_runs": cleanup_runs,
            "total_cleanup_actions": total_cleanup_actions,

            "approval_in_progress_runs": approval_in_progress_runs,
            "approval_resolved_runs": approval_resolved_runs,
            "approval_approved_runs": approval_approved_runs,
            "approval_rejected_runs": approval_rejected_runs,
            "approval_resume_failed_runs": approval_resume_failed_runs,

            "stale_approval_recovery_runs": stale_approval_recovery_runs,
            "approval_stale_recovered_runs": stale_approval_recovery_runs,
            "total_approval_recovery_events": total_approval_recovery_events,

            "latest_runs": latest_runs,
        }