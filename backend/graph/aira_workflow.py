from schemas.aira_state import AiraXState
from agents.planner.planner_agent import PlannerAgent
from agents.decision.decision_agent import DecisionAgent
from agents.execution.execution_agent import ExecutionAgent
from agents.validation.validation_agent import ValidationAgent
from agents.reflection.reflection_agent import ReflectionAgent
from memory.workflow_memory import WorkflowMemory


class AiraXWorkflow:
    def __init__(self):
        self.planner = PlannerAgent()
        self.decision = DecisionAgent()
        self.execution = ExecutionAgent()
        self.validation = ValidationAgent()
        self.reflection = ReflectionAgent()

    async def run(self, user_goal: str) -> AiraXState:
        state = AiraXState(user_goal=user_goal)

        WorkflowMemory.add_log(
            state,
            agent="aira_x_workflow",
            event="workflow_started",
            details={"user_goal": user_goal},
        )

        state = await self.planner.run(state)

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
                current_step = self._get_current_step(state)

                execution_success = any(
                    output.get("agent") == "execution_agent"
                    and output.get("tool_result", {}).get("success")
                    for output in state.execution_outputs
                )

                if current_step and execution_success:
                    current_step.status = "completed"
                    current_step.result = "Validation passed. Execution output exists."
                    state.status = "validated"
                    state.decision = "validation_success"
                elif current_step:
                    current_step.status = "failed"
                    current_step.error = "No successful execution output found to validate."
                    state.status = "failed"
                    state.decision = "validation_failed"

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
                break

            elif state.decision == "finish":
                state.status = "completed"
                state.final_answer = "Workflow finished."
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
                break

        return state

    def _get_current_step(self, state: AiraXState):
        if state.current_step is None:
            return None

        return next(
            (step for step in state.plan if step.id == state.current_step),
            None,
        )