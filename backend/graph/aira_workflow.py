from schemas.aira_state import AiraXState
from agents.planner.planner_agent import PlannerAgent
from agents.decision.decision_agent import DecisionAgent
from agents.execution.execution_agent import ExecutionAgent
from agents.validation.validation_agent import ValidationAgent
from agents.reflection.reflection_agent import ReflectionAgent
from agents.memory.memory_agent import MemoryAgent
from memory.workflow_memory import WorkflowMemory


class AiraXWorkflow:
    def __init__(self):
        self.planner = PlannerAgent()
        self.decision = DecisionAgent()
        self.execution = ExecutionAgent()
        self.validation = ValidationAgent()
        self.reflection = ReflectionAgent()
        self.memory = MemoryAgent()

    async def run(self, user_goal: str, run_id: str | None = None) -> AiraXState:
        state = AiraXState(user_goal=user_goal, run_id=run_id)

        WorkflowMemory.add_log(
            state,
            agent="aira_x_workflow",
            event="workflow_started",
            details={"user_goal": user_goal, "run_id": run_id},
        )

        state = await self.planner.run(state)

        return await self._execute_loop(state)

    async def resume(self, state: AiraXState) -> AiraXState:
        WorkflowMemory.add_log(
            state,
            agent="aira_x_workflow",
            event="workflow_resumed_after_approval",
            details={
                "run_id": state.run_id,
                "approved_actions": state.memory.get("approved_actions", []),
            },
        )

        return await self._execute_loop(state)

    async def _execute_loop(self, state: AiraXState) -> AiraXState:
        while True:
            state = await self.decision.run(state)

            WorkflowMemory.add_log(
                state,
                agent="decision_agent",
                event="decision_made",
                details={
                    "decision": state.decision,
                    "current_step": state.current_step,
                    "retry_count": state.retry_count,
                    "status": state.status,
                },
            )

            if state.decision == "run_planner":
                current_step = self._get_current_step(state)
                if current_step:
                    current_step.status = "completed"
                    current_step.result = "Goal understood and initial plan created."

            elif state.decision == "run_execution":
                state = await self.execution.run(state)

            elif state.decision == "execution_failed":
                state = await self.reflection.run(state)

            elif state.decision == "reflect_and_retry":
                state = await self.reflection.run(state)

            elif state.decision == "retry_prepared":
                state.status = "retrying"
                continue

            elif state.decision == "run_validation":
                state = await self.validation.run(state)

            elif state.decision == "run_tool":
                current_step = self._get_current_step(state)
                if current_step:
                    current_step.status = "completed"
                    current_step.result = "Decision step completed."
                    state.decision = "tool_step_completed"

            elif state.decision == "continue_workflow":
                continue

            elif state.decision == "validate_final_result":
                state.status = "completed"
                state.final_answer = "Workflow completed successfully."

                WorkflowMemory.add_log(
                    state,
                    agent="aira_x_workflow",
                    event="workflow_completed",
                    details={"final_answer": state.final_answer},
                )

                state = await self.memory.run(state)
                break

            elif state.decision == "stop_safety_block":
                state.status = "failed"

                WorkflowMemory.add_log(
                    state,
                    agent="aira_x_workflow",
                    event="workflow_blocked_by_safety",
                    details={"final_answer": state.final_answer},
                )

                state = await self.memory.run(state)
                break

            elif state.decision == "stop_approval_required":
                state.status = "requires_approval"

                WorkflowMemory.add_log(
                    state,
                    agent="aira_x_workflow",
                    event="workflow_waiting_for_approval",
                    details={"final_answer": state.final_answer},
                )

                state = await self.memory.run(state)
                break

            elif state.decision == "finish":
                state.status = "completed"
                state.final_answer = "Workflow finished."

                state = await self.memory.run(state)
                break

            elif state.decision == "stop_max_retries":
                state.status = "failed"
                state.final_answer = "Workflow failed after maximum retries."

                WorkflowMemory.add_log(
                    state,
                    agent="aira_x_workflow",
                    event="workflow_failed_max_retries",
                    details={"retry_count": state.retry_count},
                )

                state = await self.memory.run(state)
                break

            else:
                state.status = "failed"
                state.final_answer = f"Unknown decision: {state.decision}"

                WorkflowMemory.add_log(
                    state,
                    agent="aira_x_workflow",
                    event="workflow_failed_unknown_decision",
                    details={"decision": state.decision},
                )

                state = await self.memory.run(state)
                break

        return state

    def _get_current_step(self, state: AiraXState):
        if state.current_step is None:
            return None

        return next(
            (step for step in state.plan if step.id == state.current_step),
            None,
        )