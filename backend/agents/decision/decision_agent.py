from agents.base_agent import BaseAgent
from schemas.aira_state import AiraXState


class DecisionAgent(BaseAgent):
    name = "decision_agent"
    description = "Decides the next action based on current workflow state."

    async def run(self, state: AiraXState) -> AiraXState:
        if not state.plan:
            state.decision = "create_plan"
            state.status = "planning"
            return state

        if state.status == "completed":
            state.decision = "finish"
            return state

        if state.retry_count >= state.max_retries:
            state.decision = "stop_max_retries"
            state.status = "failed"
            return state

        current_step = None

        for step in state.plan:
            if step.status in ["pending", "failed"]:
                current_step = step
                break

        if current_step is None:
            state.decision = "validate_final_result"
            state.status = "validating"
            return state

        state.current_step = current_step.id

        if current_step.status == "failed":
            state.decision = "reflect_and_retry"
            state.status = "reflecting"
            return state

        if current_step.assigned_agent == "research_agent":
            state.decision = "run_research"
        elif current_step.assigned_agent == "execution_agent":
            state.decision = "run_execution"
        elif current_step.assigned_agent == "validation_agent":
            state.decision = "run_validation"
        elif current_step.assigned_agent == "planner_agent":
            state.decision = "run_planner"
        else:
            state.decision = "run_tool"

        state.status = "deciding"
        return state