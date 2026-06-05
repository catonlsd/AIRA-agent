from typing import Any

from langgraph.graph import END, START, StateGraph

from schemas.aira_state import AiraXState, utc_now_iso
from agents.planner.planner_agent import PlannerAgent
from agents.decision.decision_agent import DecisionAgent
from agents.execution.execution_agent import ExecutionAgent
from agents.validation.validation_agent import ValidationAgent
from agents.reflection.reflection_agent import ReflectionAgent
from agents.memory.memory_agent import MemoryAgent
from memory.workflow_memory import WorkflowMemory


class LangGraphAiraXWorkflow:
    """
    Parallel LangGraph implementation of the AIRA-X workflow runtime.

    This file does not replace the existing custom AiraXWorkflow yet.
    It reuses the same agents, state schema, workflow memory, and final-answer
    formatting so we can migrate safely.
    """

    def __init__(self):
        self.planner = PlannerAgent()
        self.decision = DecisionAgent()
        self.execution = ExecutionAgent()
        self.validation = ValidationAgent()
        self.reflection = ReflectionAgent()
        self.memory = MemoryAgent()
        self.graph = self._build_graph()

    async def run(self, user_goal: str, run_id: str | None = None) -> AiraXState:
        state = AiraXState(user_goal=user_goal, run_id=run_id)

        WorkflowMemory.add_log(
            state,
            agent="langgraph_aira_x_workflow",
            event="workflow_started",
            details={
                "user_goal": user_goal,
                "run_id": run_id,
                "runtime": "langgraph",
            },
        )

        result = await self.graph.ainvoke(state.model_dump())

        return self._to_state(result)

    async def resume(self, state: AiraXState) -> AiraXState:
        WorkflowMemory.add_log(
            state,
            agent="langgraph_aira_x_workflow",
            event="workflow_resumed_after_approval",
            details={
                "run_id": state.run_id,
                "approved_actions": state.memory.get("approved_actions", []),
                "runtime": "langgraph",
            },
        )

        state.memory["_langgraph_skip_planner"] = True

        result = await self.graph.ainvoke(state.model_dump())

        resumed_state = self._to_state(result)
        resumed_state.memory.pop("_langgraph_skip_planner", None)

        return resumed_state

    def _build_graph(self):
        graph = StateGraph(dict)

        graph.add_node("entry", self._entry_node)
        graph.add_node("planner", self._planner_node)
        graph.add_node("decision", self._decision_node)
        graph.add_node("complete_planner_step", self._complete_planner_step_node)
        graph.add_node("execution", self._execution_node)
        graph.add_node("reflection", self._reflection_node)
        graph.add_node("retry_prepared", self._retry_prepared_node)
        graph.add_node("validation", self._validation_node)
        graph.add_node("complete_tool_step", self._complete_tool_step_node)
        graph.add_node("complete_workflow", self._complete_workflow_node)
        graph.add_node("safety_blocked", self._safety_blocked_node)
        graph.add_node("approval_required", self._approval_required_node)
        graph.add_node(
            "non_retryable_failure",
            self._non_retryable_failure_node,
        )
        graph.add_node("max_retries_failed", self._max_retries_failed_node)
        graph.add_node("unknown_decision_failed", self._unknown_decision_failed_node)

        graph.add_edge(START, "entry")

        graph.add_conditional_edges(
            "entry",
            self._route_entry,
            {
                "planner": "planner",
                "decision": "decision",
            },
        )

        graph.add_edge("planner", "decision")

        graph.add_conditional_edges(
            "decision",
            self._route_decision,
            {
                "run_planner": "complete_planner_step",
                "run_execution": "execution",
                "execution_failed": "reflection",
                "reflect_and_retry": "reflection",
                "retry_prepared": "retry_prepared",
                "run_validation": "validation",
                "run_tool": "complete_tool_step",
                "continue_workflow": "decision",
                "validate_final_result": "complete_workflow",
                "finish": "complete_workflow",
                "stop_safety_block": "safety_blocked",
                "stop_approval_required": "approval_required",
                "stop_non_retryable_failure": "non_retryable_failure",
                "stop_max_retries": "max_retries_failed",
                "unknown": "unknown_decision_failed",
            },
        )

        graph.add_edge("complete_planner_step", "decision")
        graph.add_edge("execution", "decision")
        graph.add_edge("reflection", "decision")
        graph.add_edge("retry_prepared", "decision")
        graph.add_edge("validation", "decision")
        graph.add_edge("complete_tool_step", "decision")

        graph.add_edge("complete_workflow", END)
        graph.add_edge("safety_blocked", END)
        graph.add_edge("approval_required", END)
        graph.add_edge("non_retryable_failure", END)
        graph.add_edge("max_retries_failed", END)
        graph.add_edge("unknown_decision_failed", END)

        return graph.compile()

    async def _entry_node(self, state_data: dict[str, Any]) -> dict[str, Any]:
        return state_data

    def _route_entry(self, state_data: dict[str, Any]) -> str:
        memory = state_data.get("memory") or {}

        if memory.get("_langgraph_skip_planner"):
            return "decision"

        return "planner"

    async def _planner_node(self, state_data: dict[str, Any]) -> dict[str, Any]:
        state = self._to_state(state_data)
        state = await self.planner.run(state)

        return self._to_dict(state)

    async def _decision_node(self, state_data: dict[str, Any]) -> dict[str, Any]:
        state = self._to_state(state_data)
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
                "runtime": "langgraph",
            },
        )

        return self._to_dict(state)

    def _route_decision(self, state_data: dict[str, Any]) -> str:
        decision = state_data.get("decision")

        known_decisions = {
            "run_planner",
            "run_execution",
            "execution_failed",
            "reflect_and_retry",
            "retry_prepared",
            "run_validation",
            "run_tool",
            "continue_workflow",
            "validate_final_result",
            "finish",
            "stop_safety_block",
            "stop_approval_required",
            "stop_non_retryable_failure",
            "stop_max_retries",
        }

        if decision in known_decisions:
            return decision

        return "unknown"

    async def _complete_planner_step_node(
        self,
        state_data: dict[str, Any],
    ) -> dict[str, Any]:
        state = self._to_state(state_data)
        current_step = self._get_current_step(state)

        if current_step:
            current_step.status = "completed"
            current_step.result = (
                current_step.description
                or "Goal understood and initial plan created."
            )

        return self._to_dict(state)

    async def _execution_node(self, state_data: dict[str, Any]) -> dict[str, Any]:
        state = self._to_state(state_data)
        state = await self.execution.run(state)

        return self._to_dict(state)

    async def _reflection_node(self, state_data: dict[str, Any]) -> dict[str, Any]:
        state = self._to_state(state_data)
        state = await self.reflection.run(state)

        return self._to_dict(state)

    async def _retry_prepared_node(
        self,
        state_data: dict[str, Any],
    ) -> dict[str, Any]:
        state = self._to_state(state_data)
        state.status = "retrying"

        return self._to_dict(state)

    async def _validation_node(self, state_data: dict[str, Any]) -> dict[str, Any]:
        state = self._to_state(state_data)
        state = await self.validation.run(state)

        return self._to_dict(state)

    async def _complete_tool_step_node(
        self,
        state_data: dict[str, Any],
    ) -> dict[str, Any]:
        state = self._to_state(state_data)
        current_step = self._get_current_step(state)

        if current_step:
            current_step.status = "completed"
            current_step.result = (
                current_step.description
                or "Decision step completed."
            )
            state.decision = "tool_step_completed"

        return self._to_dict(state)

    async def _complete_workflow_node(
        self,
        state_data: dict[str, Any],
    ) -> dict[str, Any]:
        state = self._to_state(state_data)
        state.status = "completed"
        state.final_answer = self._build_final_answer(state)
        state.completed_at = utc_now_iso()
        state.updated_at = state.completed_at

        WorkflowMemory.add_log(
            state,
            agent="langgraph_aira_x_workflow",
            event="workflow_completed",
            details={
                "final_answer": state.final_answer,
                "execution_outputs_count": len(state.execution_outputs),
                "runtime": "langgraph",
            },
        )

        state = await self.memory.run(state)

        return self._to_dict(state)

    async def _safety_blocked_node(
        self,
        state_data: dict[str, Any],
    ) -> dict[str, Any]:
        state = self._to_state(state_data)
        state.status = "failed"
        state.completed_at = utc_now_iso()
        state.updated_at = state.completed_at

        WorkflowMemory.add_log(
            state,
            agent="langgraph_aira_x_workflow",
            event="workflow_blocked_by_safety",
            details={
                "final_answer": state.final_answer,
                "runtime": "langgraph",
            },
        )

        state = await self.memory.run(state)

        return self._to_dict(state)

    async def _approval_required_node(
        self,
        state_data: dict[str, Any],
    ) -> dict[str, Any]:
        state = self._to_state(state_data)
        state.status = "requires_approval"
        state.updated_at = utc_now_iso()

        WorkflowMemory.add_log(
            state,
            agent="langgraph_aira_x_workflow",
            event="workflow_waiting_for_approval",
            details={
                "final_answer": state.final_answer,
                "runtime": "langgraph",
            },
        )

        state = await self.memory.run(state)

        return self._to_dict(state)

    async def _non_retryable_failure_node(
        self,
        state_data: dict[str, Any],
    ) -> dict[str, Any]:
        state = self._to_state(state_data)
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
            agent="langgraph_aira_x_workflow",
            event="workflow_stopped_non_retryable_failure",
            details={
                "final_answer": state.final_answer,
                "runtime": "langgraph",
            },
        )

        state = await self.memory.run(state)

        return self._to_dict(state)

    async def _max_retries_failed_node(
        self,
        state_data: dict[str, Any],
    ) -> dict[str, Any]:
        state = self._to_state(state_data)
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
            agent="langgraph_aira_x_workflow",
            event="workflow_failed_max_retries",
            details={
                "retry_count": state.retry_count,
                "final_answer": state.final_answer,
                "runtime": "langgraph",
            },
        )

        state = await self.memory.run(state)

        return self._to_dict(state)

    async def _unknown_decision_failed_node(
        self,
        state_data: dict[str, Any],
    ) -> dict[str, Any]:
        state = self._to_state(state_data)
        state.status = "failed"
        state.final_answer = f"Unknown decision: {state.decision}"
        state.completed_at = utc_now_iso()
        state.updated_at = state.completed_at

        WorkflowMemory.add_log(
            state,
            agent="langgraph_aira_x_workflow",
            event="workflow_failed_unknown_decision",
            details={
                "decision": state.decision,
                "runtime": "langgraph",
            },
        )

        state = await self.memory.run(state)

        return self._to_dict(state)

    def _to_state(self, state_data: dict[str, Any] | AiraXState) -> AiraXState:
        if isinstance(state_data, AiraXState):
            return state_data

        return AiraXState.model_validate(state_data)

    def _to_dict(self, state: AiraXState) -> dict[str, Any]:
        return state.model_dump()

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