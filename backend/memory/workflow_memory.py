from datetime import datetime
from typing import Dict, Any

from schemas.aira_state import AiraXState


class WorkflowMemory:
    name = "workflow_memory"

    @staticmethod
    def add_log(
        state: AiraXState,
        agent: str,
        event: str,
        details: Dict[str, Any] | None = None,
    ) -> AiraXState:
        if details is None:
            details = {}

        state.memory.setdefault("workflow_logs", [])

        state.memory["workflow_logs"].append(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "agent": agent,
                "event": event,
                "details": details,
            }
        )

        return state