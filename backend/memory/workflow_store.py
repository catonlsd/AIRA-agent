from typing import Dict, Optional, List, Any

from schemas.aira_state import AiraXState


class WorkflowStore:
    runs: Dict[str, AiraXState] = {}

    @classmethod
    def save(cls, state: AiraXState) -> None:
        if state.run_id:
            cls.runs[state.run_id] = state

    @classmethod
    def get(cls, run_id: str) -> Optional[AiraXState]:
        return cls.runs.get(run_id)

    @classmethod
    def delete(cls, run_id: str) -> None:
        if run_id in cls.runs:
            del cls.runs[run_id]

    @classmethod
    def list_runs(cls) -> List[Dict[str, Any]]:
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