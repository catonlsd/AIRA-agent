from typing import Dict, Optional

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