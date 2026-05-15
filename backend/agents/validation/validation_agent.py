from agents.base_agent import BaseAgent
from schemas.aira_state import AiraXState


class ValidationAgent(BaseAgent):
    name = "validation_agent"
    description = "Validates whether execution completed successfully."

    async def run(self, state: AiraXState) -> AiraXState:
        if state.current_step is None:
            state.status = "failed"
            state.decision = "validation_failed_no_step"
            return state

        current_step = next(
            (step for step in state.plan if step.id == state.current_step),
            None,
        )

        if current_step is None:
            state.status = "failed"
            state.decision = "validation_failed_step_missing"
            return state

        if current_step.result:
            current_step.status = "completed"

            state.status = "validated"
            state.decision = "validation_success"

        else:
            current_step.status = "failed"

            state.status = "failed"
            state.decision = "validation_failed"

        return state