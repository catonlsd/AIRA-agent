from agents.base_agent import BaseAgent
from schemas.aira_state import AiraXState


class DecisionAgent(BaseAgent):
    name = "decision_agent"
    description = "Determines the next workflow action."

    async def run(self, state: AiraXState) -> AiraXState:
        if state.decision == "approval_required" or state.status == "requires_approval":
            state.decision = "stop_approval_required"
            return state

        current_step = next(
            (step for step in state.plan if step.id == state.current_step),
            None,
        )

        if current_step and current_step.error:
            if "Unsafe action blocked" in current_step.error:
                state.decision = "stop_safety_block"
                state.status = "failed"
                state.final_answer = current_step.error
                return state

        if current_step and current_step.status == "failed":
            if current_step.tool_name == "git_tool" and current_step.tool_action in {
                "stage_all",
                "commit",
            }:
                state.decision = "stop_non_retryable_failure"
                state.status = "failed"
                state.final_answer = (
                    current_step.error
                    or "Git write action failed and will not be retried automatically."
                )
                return state

        if state.retry_count >= state.max_retries:
            if current_step:
                current_step.status = "failed"

                if not current_step.error:
                    current_step.error = (
                        state.memory.get("last_execution_error")
                        or "Workflow failed after maximum retries."
                    )

            state.decision = "stop_max_retries"
            return state

        if state.decision == "retry_prepared":
            state.decision = "run_execution"
            return state

        if state.decision == "validation_success" or state.status == "validated":
            state.decision = "validate_final_result"
            return state

        if current_step is None:
            state.decision = "finish"
            return state

        if current_step.status == "pending":
            if current_step.assigned_agent == "planner_agent":
                state.decision = "run_planner"
            elif current_step.assigned_agent == "execution_agent":
                state.decision = "run_execution"
            elif current_step.assigned_agent == "validation_agent":
                state.decision = "run_validation"
            elif current_step.assigned_agent == "decision_agent":
                state.decision = "run_tool"

        elif current_step.status == "completed":
            if current_step.assigned_agent == "execution_agent":
                state.decision = "run_validation"
                return state

            next_step = next(
                (step for step in state.plan if step.id == state.current_step + 1),
                None,
            )

            if next_step:
                state.current_step += 1
                state.decision = "continue_workflow"
            else:
                state.decision = "validate_final_result"

        elif current_step.status == "failed":
            state.decision = "reflect_and_retry"

        return state