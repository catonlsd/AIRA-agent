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

        successful_output = self._latest_successful_execution_output(state)

        if successful_output:
            validation_result = self._build_validation_result(successful_output)

            current_step.status = "completed"

            # Important:
            # Do not overwrite the actual tool output shown on the execution step.
            # ExecutionAgent already writes current_step.result from tool_result["output"].
            # Validation metadata belongs in memory/logs, not in the user-visible step output.
            if not current_step.result:
                current_step.result = self._extract_user_visible_result(
                    successful_output
                )

            state.memory["latest_validation_result"] = validation_result
            state.memory.setdefault("validation_results", [])
            state.memory["validation_results"].append(
                {
                    "step_id": current_step.id,
                    "step_title": current_step.title,
                    "result": validation_result,
                    "tool_name": successful_output.get("tool_used"),
                    "tool_action": successful_output.get("tool_action"),
                }
            )

            state.status = "validated"
            state.decision = "validation_success"

            WorkflowMemory.add_log(
                state,
                agent=self.name,
                event="validation_success",
                details={
                    "step_id": current_step.id,
                    "step_result": current_step.result,
                    "validation_result": validation_result,
                },
            )

        else:
            latest_error = self._latest_execution_error(state)

            current_step.status = "failed"
            current_step.error = (
                latest_error or "No successful execution output found to validate."
            )

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

    def _latest_successful_execution_output(self, state: AiraXState) -> dict | None:
        for output in reversed(state.execution_outputs):
            if (
                output.get("agent") == "execution_agent"
                and output.get("tool_result", {}).get("success") is True
            ):
                return output

        return None

    def _latest_execution_error(self, state: AiraXState) -> str | None:
        for output in reversed(state.execution_outputs):
            tool_result = output.get("tool_result", {})

            if tool_result.get("success") is True:
                continue

            error = (
                tool_result.get("stderr")
                or tool_result.get("error")
                or tool_result.get("output")
            )

            if error:
                return str(error).strip()

        return None

    def _extract_user_visible_result(self, output: dict) -> str:
        tool_result = output.get("tool_result", {})
        raw_output = (
            tool_result.get("output")
            or tool_result.get("stdout")
            or tool_result.get("stderr")
            or ""
        )

        if isinstance(raw_output, list):
            text = "\n".join(str(item) for item in raw_output)
        else:
            text = str(raw_output)

        text = text.strip()

        if text:
            return text

        tool_name = output.get("tool_used") or "tool"
        tool_action = output.get("tool_action") or "action"

        return f"{tool_name}:{tool_action} completed successfully."

    def _build_validation_result(self, output: dict) -> str:
        tool_name = output.get("tool_used") or "tool"
        tool_action = output.get("tool_action") or "action"
        tool_result = output.get("tool_result", {})
        result_output = tool_result.get("output") or tool_result.get("stdout") or ""

        if isinstance(result_output, list):
            has_meaningful_output = len(result_output) > 0
        else:
            has_meaningful_output = bool(str(result_output).strip())

        if has_meaningful_output:
            return (
                f"Validation passed. {tool_name}:{tool_action} completed "
                "successfully and produced usable output."
            )

        return (
            f"Validation passed. {tool_name}:{tool_action} completed "
            "successfully without printed output."
        )
