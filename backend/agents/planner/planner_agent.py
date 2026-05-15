from agents.base_agent import BaseAgent
from schemas.aira_state import AiraXState, AiraXStep


class PlannerAgent(BaseAgent):
    name = "planner_agent"
    description = "Breaks user goals into executable steps."

    async def run(self, state: AiraXState) -> AiraXState:
        state.status = "planning"

        state.plan = [
            AiraXStep(
                id=1,
                title="Understand user goal",
                description=f"Analyze the task: {state.user_goal}",
                assigned_agent="planner_agent",
            ),
            AiraXStep(
                id=2,
                title="Decide execution path",
                description="Determine which agent should act next.",
                assigned_agent="decision_agent",
            ),
            AiraXStep(
                id=3,
                title="Execute task",
                description="Perform the required action using tools or execution.",
                assigned_agent="execution_agent",
            ),
            AiraXStep(
                id=4,
                title="Validate result",
                description="Check whether the task was completed successfully.",
                assigned_agent="validation_agent",
            ),
        ]

        state.current_step = 1
        state.decision = "plan_created"

        return state
        