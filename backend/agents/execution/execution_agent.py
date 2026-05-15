from datetime import datetime

from agents.base_agent import BaseAgent
from schemas.aira_state import AiraXState


class ExecutionAgent(BaseAgent):
    name = "execution_agent"
    description = "Executes workflow steps and records execution output."

    async def run(self, state: AiraXState) -> AiraXState:
        if state.current_step is None:
            state.decision = "no_step_to_execute"
            state.status = "failed"
            return state

        current_step = next(
            (step for step in state.plan if step.id == state.current_step),
            None,
        )

        if current_step is None:
            state.decision = "step_not_found"
            state.status = "failed"
            return state

        current_step.status = "running"

        output = {
            "step_id": current_step.id,
            "agent": self.name,
            "timestamp": datetime.utcnow().isoformat(),
            "output": f"Executed step: {current_step.title}",
        }

        state.execution_outputs.append(output)

        current_step.result = output["output"]
        current_step.status = "completed"

        state.status = "executing"
        state.decision = "execution_completed"

        return state