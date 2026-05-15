from agents.base_agent import BaseAgent
from schemas.aira_state import AiraXState


class ReflectionAgent(BaseAgent):
    name = "reflection_agent"
    description = "Analyzes failures and prepares retry strategy."

    async def run(self, state: AiraXState) -> AiraXState:
        if state.current_step is None:
            state.status = "failed"
            state.decision = "reflection_failed_no_step"
            return state

        current_step = next(
            (step for step in state.plan if step.id == state.current_step),
            None,
        )

        if current_step is None:
            state.status = "failed"
            state.decision = "reflection_failed_step_missing"
            return state

        state.retry_count += 1

        retry_note = {
            "step_id": current_step.id,
            "failed_step": current_step.title,
            "error": current_step.error or "Unknown error",
            "retry_count": state.retry_count,
            "suggested_fix": "Retry the step with improved execution strategy.",
        }

        state.memory.setdefault("reflections", [])
        state.memory["reflections"].append(retry_note)

        current_step.status = "pending"
        current_step.error = None

        state.status = "reflecting"
        state.decision = "retry_prepared"

        return state