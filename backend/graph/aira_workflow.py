from schemas.aira_state import AiraXState, utc_now_iso
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
            details={
                "user_goal": user_goal,
                "run_id": run_id,
            },
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
            state.updated_at = utc_now_iso()
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
                    current_step.result = (
                        current_step.description
                        or "Goal understood and initial plan created."
                    )

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
                    current_step.result = (
                        current_step.description
                        or "Decision step completed."
                    )
                    state.decision = "tool_step_completed"

            elif state.decision == "continue_workflow":
                continue

            elif state.decision == "validate_final_result":
                state.status = "completed"
                state.final_answer = self._build_final_answer(state)
                state.completed_at = utc_now_iso()
                state.updated_at = state.completed_at

                WorkflowMemory.add_log(
                    state,
                    agent="aira_x_workflow",
                    event="workflow_completed",
                    details={
                        "final_answer": state.final_answer,
                        "execution_outputs_count": len(state.execution_outputs),
                    },
                )

                state = await self.memory.run(state)
                break

            elif state.decision == "stop_safety_block":
                state.status = "failed"
                state.completed_at = utc_now_iso()
                state.updated_at = state.completed_at

                WorkflowMemory.add_log(
                    state,
                    agent="aira_x_workflow",
                    event="workflow_blocked_by_safety",
                    details={
                        "final_answer": state.final_answer,
                    },
                )

                state = await self.memory.run(state)
                break

            elif state.decision == "stop_approval_required":
                state.status = "requires_approval"
                state.updated_at = utc_now_iso()

                WorkflowMemory.add_log(
                    state,
                    agent="aira_x_workflow",
                    event="workflow_waiting_for_approval",
                    details={
                        "final_answer": state.final_answer,
                    },
                )

                state = await self.memory.run(state)
                break

            elif state.decision == "stop_non_retryable_failure":
                state.status = "failed"

                current_step = self._get_current_step(state)

                if current_step:
                    current_step.status = "failed"

                    if not current_step.error:
                        current_step.error = (
                            state.memory.get("last_execution_error")
                            or "Non-retryable workflow step failed."
                        )

                if not state.final_answer:
                    state.final_answer = (
                        state.memory.get("last_execution_error")
                        or "Workflow stopped because a non-retryable action failed."
                    )

                state.completed_at = utc_now_iso()
                state.updated_at = state.completed_at

                WorkflowMemory.add_log(
                    state,
                    agent="aira_x_workflow",
                    event="workflow_stopped_non_retryable_failure",
                    details={
                        "final_answer": state.final_answer,
                    },
                )

                state = await self.memory.run(state)
                break

            elif state.decision == "finish":
                state.status = "completed"
                state.final_answer = self._build_final_answer(state)
                state.completed_at = utc_now_iso()
                state.updated_at = state.completed_at

                WorkflowMemory.add_log(
                    state,
                    agent="aira_x_workflow",
                    event="workflow_completed",
                    details={
                        "final_answer": state.final_answer,
                        "execution_outputs_count": len(state.execution_outputs),
                    },
                )

                state = await self.memory.run(state)
                break

            elif state.decision == "stop_max_retries":
                state.status = "failed"

                current_step = self._get_current_step(state)

                if current_step:
                    current_step.status = "failed"

                    if not current_step.error:
                        current_step.error = (
                            state.memory.get("last_execution_error")
                            or "Workflow failed after maximum retries."
                        )

                state.final_answer = self._build_failure_answer(state)
                state.completed_at = utc_now_iso()
                state.updated_at = state.completed_at

                WorkflowMemory.add_log(
                    state,
                    agent="aira_x_workflow",
                    event="workflow_failed_max_retries",
                    details={
                        "retry_count": state.retry_count,
                        "final_answer": state.final_answer,
                    },
                )

                state = await self.memory.run(state)
                break

            else:
                state.status = "failed"
                state.final_answer = f"Unknown decision: {state.decision}"
                state.completed_at = utc_now_iso()
                state.updated_at = state.completed_at

                WorkflowMemory.add_log(
                    state,
                    agent="aira_x_workflow",
                    event="workflow_failed_unknown_decision",
                    details={
                        "decision": state.decision,
                    },
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

    def _build_final_answer(self, state: AiraXState) -> str:
        successful_outputs = [
            output
            for output in state.execution_outputs
            if output.get("tool_result", {}).get("success") is True
        ]

        if successful_outputs:
            output_sections = []
            summary_lines = []

            for index, output in enumerate(successful_outputs, start=1):
                useful_output = self._extract_useful_output(output.get("tool_result", {}))
                summary_lines.append(
                    f"- {self._summarize_successful_output(output, include_output=False)}"
                )

                if useful_output:
                    output_label = self._output_label(output, index)
                    output_sections.append((output_label, useful_output))

            lines = ["Task completed successfully."]

            if output_sections:
                lines.append("")
                if len(output_sections) == 1:
                    lines.append("Output:")
                    lines.append(output_sections[0][1])
                else:
                    lines.append("Outputs:")
                    for label, value in output_sections:
                        lines.append(f"\n{label}:")
                        lines.append(value)

            lines.append("")
            lines.append("Execution summary:")
            lines.extend(summary_lines)

            validation_result = state.memory.get("latest_validation_result")
            if validation_result:
                lines.append(f"- {validation_result}")

            return self._clean_final_answer("\n".join(lines))

        completed_step_results = [
            step.result.strip()
            for step in state.plan
            if step.status == "completed"
            and step.result
            and step.result.strip()
            and not self._is_generic_success_text(step.result)
        ]

        if completed_step_results:
            return self._clean_final_answer(
                "Workflow completed.\n\n"
                "Outcome:\n"
                + "\n".join(f"- {result}" for result in completed_step_results)
            )

        return self._clean_final_answer(
            "I understood the goal, but AIRA-X did not produce a tool execution "
            "output for this workflow. Try giving a more specific executable task, "
            "such as running a command, checking Git status, reading a file, "
            "writing a file, or running a Python snippet."
        )

    def _build_failure_answer(self, state: AiraXState) -> str:
        latest_error = (
            state.memory.get("last_execution_error")
            or self._latest_step_error(state)
            or "Workflow failed after maximum retries."
        )

        return self._clean_final_answer(
            "Workflow failed after retry attempts.\n\n"
            f"Reason:\n- {latest_error}"
        )

    def _summarize_successful_output(
        self,
        output: dict,
        *,
        include_output: bool = True,
    ) -> str:
        tool_name = output.get("tool_used") or "tool"
        tool_action = output.get("tool_action") or "action"
        tool_result = output.get("tool_result", {})
        command = tool_result.get("command")
        path = tool_result.get("path")
        code = tool_result.get("code")
        useful_output = self._extract_useful_output(tool_result)

        if tool_name == "python_tool":
            summary = "Ran Python code successfully"
            if include_output and useful_output:
                summary += f" and captured this output: {useful_output}"
            elif code:
                summary += " using the Python tool"
            return summary + "."

        if tool_name == "shell_tool":
            summary = "Ran the shell command successfully"
            if command:
                summary += f": {command}"
            if include_output and useful_output:
                summary += f". Output: {useful_output}"
            return summary + "."

        if tool_name == "file_tool":
            if tool_action == "write_file":
                return f"Wrote the file successfully at {path or 'the requested path'}."
            if tool_action == "read_file":
                summary = f"Read the file successfully from {path or 'the requested path'}"
                if include_output and useful_output:
                    summary += f". Content preview: {useful_output}"
                return summary + "."
            if tool_action == "list_files":
                summary = f"Listed files in {path or 'the requested folder'}"
                if include_output and useful_output:
                    summary += f": {useful_output}"
                return summary + "."

        if tool_name == "git_tool":
            summary = f"Completed Git action `{tool_action}` successfully"
            if command:
                summary += f" with command `{command}`"
            if include_output and useful_output:
                summary += f". Output: {useful_output}"
            return summary + "."

        summary = f"Completed {tool_name}:{tool_action} successfully"
        if include_output and useful_output:
            summary += f". Output: {useful_output}"
        return summary + "."

    def _output_label(self, output: dict, index: int) -> str:
        tool_name = output.get("tool_used") or "tool"
        tool_action = output.get("tool_action") or "action"

        if tool_name == "python_tool":
            return "Python output"

        if tool_name == "shell_tool":
            return "Command output"

        if tool_name == "file_tool":
            return "File output"

        if tool_name == "git_tool":
            return "Git output"

        return f"Step {index} output ({tool_name}:{tool_action})"

    def _extract_useful_output(self, tool_result: dict) -> str:
        raw_output = (
            tool_result.get("output")
            or tool_result.get("stdout")
            or tool_result.get("stderr")
            or ""
        )

        if isinstance(raw_output, list):
            raw_output = "\n".join(str(item) for item in raw_output)

        output = str(raw_output).strip()

        if not output or self._is_generic_success_text(output):
            return ""

        return self._compact_text(output, max_length=1400)

    def _latest_step_error(self, state: AiraXState) -> str | None:
        for step in reversed(state.plan):
            if step.error:
                return step.error

        return None

    def _is_generic_success_text(self, text: str | None) -> bool:
        if not text:
            return True

        normalized = " ".join(str(text).lower().split())

        generic_messages = {
            "workflow completed successfully.",
            "workflow completed successfully",
            "workflow finished.",
            "workflow finished",
            "execution completed successfully.",
            "execution completed successfully",
            "file written successfully.",
            "file written successfully",
            "aira-x dynamic execution working",
            "aira-x executed python code successfully",
            "decision step completed.",
            "decision step completed",
            "goal understood and initial plan created.",
            "goal understood and initial plan created",
        }

        return normalized in generic_messages

    def _compact_text(self, text: str, max_length: int = 1400) -> str:
        compacted = "\n".join(
            line.rstrip()
            for line in str(text).strip().splitlines()
            if line.strip()
        )

        if len(compacted) <= max_length:
            return compacted

        return compacted[: max_length - 3].rstrip() + "..."

    def _clean_final_answer(self, answer: str) -> str:
        return "\n".join(
            line.rstrip()
            for line in answer.strip().splitlines()
        ).strip()
