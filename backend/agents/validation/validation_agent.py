from agents.base_agent import BaseAgent
from schemas.aira_state import AiraXState
from memory.workflow_memory import WorkflowMemory


class ValidationAgent(BaseAgent):
    name = "validation_agent"
    description = "Validates whether execution completed successfully."

    async def run(self, state: AiraXState) -> AiraXState:
        if state.current_step is None:
            state.status = "failed"
            state.decision = "validation_failed_no_step"

            WorkflowMemory.add_log(
                state,
                agent=self.name,
                event="validation_failed",
                details={"reason": "No current step found."},
            )

            return state

        current_step = next(
            (step for step in state.plan if step.id == state.current_step),
            None,
        )

        if current_step is None:
            state.status = "failed"
            state.decision = "validation_failed_step_missing"

            WorkflowMemory.add_log(
                state,
                agent=self.name,
                event="validation_failed",
                details={"reason": "Current step does not exist in plan."},
            )

            return state

        WorkflowMemory.add_log(
            state,
            agent=self.name,
            event="validation_started",
            details={
                "step_id": current_step.id,
                "step_title": current_step.title,
            },
        )

        execution_success = any(
            output.get("agent") == "execution_agent"
            and output.get("tool_result", {}).get("success")
            for output in state.execution_outputs
        )

        if execution_success:
            current_step.status = "completed"

            if not current_step.result:
                current_step.result = "Execution completed successfully."

            state.status = "validated"
            state.decision = "validation_success"

            WorkflowMemory.add_log(
                state,
                agent=self.name,
                event="validation_success",
                details={
                    "step_id": current_step.id,
                    "step_result": current_step.result,
                    "validation_result": "Validation passed. Successful execution output exists.",
                },
            )

        else:
            current_step.status = "failed"
            current_step.error = "No successful execution output found to validate."

            state.status = "failed"
            state.decision = "validation_failed"

            WorkflowMemory.add_log(
                state,
                agent=self.name,
                event="validation_failed",
                details={
                    "step_id": current_step.id,
                    "error": current_step.error,
                },
            )

        return state