from agents.base_agent import BaseAgent
from schemas.aira_state import AiraXState, AiraXStep
from memory.workflow_memory import WorkflowMemory


class PlannerAgent(BaseAgent):
    name = "planner_agent"
    description = "Breaks user goals into executable steps."

    async def run(self, state: AiraXState) -> AiraXState:
        state.status = "planning"

        WorkflowMemory.add_log(
            state,
            agent=self.name,
            event="planning_started",
            details={"user_goal": state.user_goal},
        )

        goal = state.user_goal.lower()
        plan = []

        if "list files" in goal:
            plan.append(
                AiraXStep(
                    id=1,
                    title="List project files",
                    description="List files in the backend directory.",
                    assigned_agent="execution_agent",
                )
            )

        elif "create file" in goal:
            plan.append(
                AiraXStep(
                    id=1,
                    title="Create a test file",
                    description="Create a new file using the filesystem tool.",
                    assigned_agent="execution_agent",
                )
            )

        elif "run python" in goal or "python code" in goal:
            plan.append(
                AiraXStep(
                    id=1,
                    title="Run Python code",
                    description="Execute a simple Python code snippet using the Python tool.",
                    assigned_agent="execution_agent",
                )
            )

        elif "test retry" in goal or "retry demo" in goal:
            plan.append(
                AiraXStep(
                    id=1,
                    title="Run retry demo command",
                    description="Intentionally fail once, then self-correct and retry.",
                    assigned_agent="execution_agent",
                )
            )

        else:
            plan = [
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

        state.plan = plan
        state.current_step = 1
        state.decision = "plan_created"

        WorkflowMemory.add_log(
            state,
            agent=self.name,
            event="plan_created",
            details={
                "steps": [
                    {
                        "id": step.id,
                        "title": step.title,
                        "assigned_agent": step.assigned_agent,
                    }
                    for step in state.plan
                ]
            },
        )

        return state