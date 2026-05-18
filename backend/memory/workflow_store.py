import json
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
                    cls.runs[run_id] = AiraXState.model_validate(state_data)
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

        for run_id, state in cls.runs.items():
            summaries.append(
                {
                    "run_id": run_id,
                    "user_goal": state.user_goal,
                    "status": state.status,
                    "decision": state.decision,
                    "final_answer": state.final_answer,
                    "current_step": state.current_step,
                    "retry_count": state.retry_count,
                    "requires_approval": state.status == "requires_approval",
                    "pending_action": state.memory.get("pending_action"),
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

        latest_runs = cls.list_runs()[-5:]

        return {
            "total_runs": len(runs),
            "completed_runs": completed,
            "failed_runs": failed,
            "requires_approval_runs": requires_approval,
            "rejected_runs": rejected,
            "total_retries": total_retries,
            "total_tool_calls": total_tool_calls,
            "total_logs": total_logs,
            "latest_runs": latest_runs,
        }