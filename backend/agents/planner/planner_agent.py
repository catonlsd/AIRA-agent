import re

from agents.base_agent import BaseAgent
from schemas.aira_state import AiraXState, AiraXStep
from memory.workflow_memory import WorkflowMemory


class PlannerAgent(BaseAgent):
    name = "planner_agent"
    description = "Breaks user goals into executable tool-ready steps."

    async def run(self, state: AiraXState) -> AiraXState:
        state.status = "planning"

        WorkflowMemory.add_log(
            state,
            agent=self.name,
            event="planning_started",
            details={"user_goal": state.user_goal},
        )

        user_goal = " ".join(state.user_goal.strip().split())
        goal = user_goal.lower()
        plan: list[AiraXStep] = []

        if self._is_list_files_request(goal):
            path = self._extract_path(user_goal) or "."
            plan.append(
                AiraXStep(
                    id=1,
                    title="List workspace files",
                    description=f"List files in: {path}",
                    assigned_agent="execution_agent",
                    tool_name="file_tool",
                    tool_action="list_files",
                    tool_payload={"path": path},
                )
            )

        elif self._is_read_file_request(goal):
            path = self._extract_path(user_goal)

            if not path:
                plan = self._clarification_plan(
                    "I need the file path to read. Try: read file backend/main.py"
                )
            else:
                plan.append(
                    AiraXStep(
                        id=1,
                        title="Read file",
                        description=f"Read the requested file: {path}",
                        assigned_agent="execution_agent",
                        tool_name="file_tool",
                        tool_action="read_file",
                        tool_payload={"path": path},
                    )
                )

        elif self._is_write_file_request(goal):
            path = self._extract_path(user_goal) or "tmp/aira_x_generated.txt"
            content = self._extract_file_content(user_goal)

            plan.append(
                AiraXStep(
                    id=1,
                    title="Write file",
                    description=f"Write requested content to: {path}",
                    assigned_agent="execution_agent",
                    tool_name="file_tool",
                    tool_action="write_file",
                    tool_payload={
                        "path": path,
                        "content": content,
                    },
                )
            )

        elif self._is_python_request(goal):
            code = self._extract_python_code(user_goal) or self._build_python_code(user_goal)

            if not code:
                plan = self._clarification_plan(
                    "I need exact Python code or a clearly calculable instruction. "
                    "Try: run python code: print('Hello from AIRA-X')"
                )
            else:
                plan.append(
                    AiraXStep(
                        id=1,
                        title="Run Python code",
                        description="Execute the requested Python logic using the Python tool.",
                        assigned_agent="execution_agent",
                        tool_name="python_tool",
                        tool_action="run_code",
                        tool_payload={"code": code},
                    )
                )

        elif self._is_shell_command_request(goal):
            command = self._extract_shell_command(user_goal)

            if not command:
                plan = self._clarification_plan(
                    "I need the exact shell command to run. Try: run command dir"
                )
            else:
                plan.append(
                    AiraXStep(
                        id=1,
                        title="Run shell command",
                        description=f"Execute shell command: {command}",
                        assigned_agent="execution_agent",
                        tool_name="shell_tool",
                        tool_action="run",
                        tool_payload={"command": command},
                    )
                )

        elif "install package" in goal or "pip install" in goal:
            package_name = self._extract_package_name(user_goal) or "requests"

            plan.append(
                AiraXStep(
                    id=1,
                    title="Install Python package",
                    description=(
                        "Attempt to install a Python package. "
                        "This may require approval depending on policy."
                    ),
                    assigned_agent="execution_agent",
                    tool_name="shell_tool",
                    tool_action="run",
                    tool_payload={"command": f"pip install {package_name}"},
                )
            )

        elif "git status" in goal:
            plan.append(
                AiraXStep(
                    id=1,
                    title="Check Git status",
                    description="Check current repository status using the Git tool.",
                    assigned_agent="execution_agent",
                    tool_name="git_tool",
                    tool_action="status",
                    tool_payload={},
                )
            )

        elif "git branch" in goal:
            plan.append(
                AiraXStep(
                    id=1,
                    title="Check Git branch",
                    description="Check current Git branch using the Git tool.",
                    assigned_agent="execution_agent",
                    tool_name="git_tool",
                    tool_action="branch",
                    tool_payload={},
                )
            )

        elif "git remote" in goal or "remote info" in goal:
            plan.append(
                AiraXStep(
                    id=1,
                    title="Show Git remotes",
                    description="Show configured Git remotes using the Git tool.",
                    assigned_agent="execution_agent",
                    tool_name="git_tool",
                    tool_action="remote_info",
                    tool_payload={},
                )
            )

        elif "git log" in goal or "recent commits" in goal:
            plan.append(
                AiraXStep(
                    id=1,
                    title="Show recent Git commits",
                    description="Show recent commits using the Git tool.",
                    assigned_agent="execution_agent",
                    tool_name="git_tool",
                    tool_action="recent_commits",
                    tool_payload={"limit": 5},
                )
            )

        elif "last commit" in goal:
            plan.append(
                AiraXStep(
                    id=1,
                    title="Show latest Git commit",
                    description="Show the latest local Git commit using the Git tool.",
                    assigned_agent="execution_agent",
                    tool_name="git_tool",
                    tool_action="last_commit",
                    tool_payload={},
                )
            )

        elif "full diff" in goal or "show full changes" in goal:
            plan.append(
                AiraXStep(
                    id=1,
                    title="Show full Git diff",
                    description="Show full uncommitted Git changes.",
                    assigned_agent="execution_agent",
                    tool_name="git_tool",
                    tool_action="full_diff",
                    tool_payload={},
                )
            )

        elif "git diff" in goal or "show changes" in goal:
            plan.append(
                AiraXStep(
                    id=1,
                    title="Show Git diff summary",
                    description="Show a summary of uncommitted Git changes.",
                    assigned_agent="execution_agent",
                    tool_name="git_tool",
                    tool_action="diff",
                    tool_payload={},
                )
            )

        elif (
            "commit all changes" in goal
            or "stage and commit" in goal
            or "stage then commit" in goal
        ):
            commit_message = self._extract_commit_message(user_goal)

            plan = [
                AiraXStep(
                    id=1,
                    title="Stage Git changes",
                    description="Stage all current Git changes. This requires approval.",
                    assigned_agent="execution_agent",
                    tool_name="git_tool",
                    tool_action="stage_all",
                    tool_payload={},
                ),
                AiraXStep(
                    id=2,
                    title="Commit Git changes",
                    description="Create a local Git commit after staging. This requires approval.",
                    assigned_agent="execution_agent",
                    tool_name="git_tool",
                    tool_action="commit",
                    tool_payload={"message": commit_message},
                ),
            ]

        elif "git add" in goal or "stage changes" in goal:
            plan.append(
                AiraXStep(
                    id=1,
                    title="Stage Git changes",
                    description="Stage all current Git changes. This requires approval.",
                    assigned_agent="execution_agent",
                    tool_name="git_tool",
                    tool_action="stage_all",
                    tool_payload={},
                )
            )

        elif "git commit" in goal or "commit changes" in goal:
            commit_message = self._extract_commit_message(user_goal)

            plan.append(
                AiraXStep(
                    id=1,
                    title="Commit Git changes",
                    description="Create a local Git commit. This requires approval.",
                    assigned_agent="execution_agent",
                    tool_name="git_tool",
                    tool_action="commit",
                    tool_payload={"message": commit_message},
                )
            )

        elif "git push" in goal or goal.strip() == "push":
            push_target = self._extract_push_target(user_goal)

            plan.append(
                AiraXStep(
                    id=1,
                    title="Push Git changes",
                    description="Push local commits to a remote Git repository. This requires approval.",
                    assigned_agent="execution_agent",
                    tool_name="git_tool",
                    tool_action="push",
                    tool_payload={
                        "remote": push_target["remote"],
                        "branch": push_target["branch"],
                    },
                )
            )

        elif "rm -rf" in goal or "delete system32" in goal or "format disk" in goal:
            plan.append(
                AiraXStep(
                    id=1,
                    title="Run dangerous command",
                    description="Attempt dangerous command execution.",
                    assigned_agent="execution_agent",
                    tool_name="shell_tool",
                    tool_action="run",
                    tool_payload={"command": "rm -rf /"},
                )
            )

        elif "test retry" in goal or "retry demo" in goal:
            plan.append(
                AiraXStep(
                    id=1,
                    title="Run retry demo command",
                    description="Intentionally fail once, then self-correct and retry.",
                    assigned_agent="execution_agent",
                    tool_name="shell_tool",
                    tool_action="run",
                    tool_payload={"command": "non_existing_command_for_retry_demo"},
                )
            )

        else:
            plan = self._clarification_plan(
                "AIRA-X needs a specific executable action before it can run tools. "
                "Try asking it to run a command, run Python code, read/write/list a file, "
                "or inspect Git status/diff/branch/logs."
            )

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
                        "tool_name": step.tool_name,
                        "tool_action": step.tool_action,
                        "tool_payload": step.tool_payload,
                    }
                    for step in state.plan
                ]
            },
        )

        return state

    def _clarification_plan(self, message: str) -> list[AiraXStep]:
        return [
            AiraXStep(
                id=1,
                title="Clarify executable action",
                description=message,
                assigned_agent="planner_agent",
            )
        ]

    def _is_list_files_request(self, goal: str) -> bool:
        return (
            "list files" in goal
            or "show files" in goal
            or "list directory" in goal
            or "show directory" in goal
            or goal.strip() in {"dir", "ls"}
        )

    def _is_read_file_request(self, goal: str) -> bool:
        return (
            "read file" in goal
            or "open file" in goal
            or "show file" in goal
            or "display file" in goal
        )

    def _is_write_file_request(self, goal: str) -> bool:
        return (
            "create file" in goal
            or "write file" in goal
            or "make file" in goal
            or "save file" in goal
        )

    def _is_python_request(self, goal: str) -> bool:
        return (
            "run python" in goal
            or "python code" in goal
            or "execute python" in goal
            or "calculate" in goal
            or "compute" in goal
            or "evaluate" in goal
            or "factorial" in goal
            or "fibonacci" in goal
        )

    def _is_shell_command_request(self, goal: str) -> bool:
        return (
            "run command" in goal
            or "execute command" in goal
            or "shell command" in goal
            or "terminal command" in goal
        )

    def _extract_path(self, user_goal: str) -> str | None:
        quoted = re.search(r'["\']([^"\']+\.[A-Za-z0-9]+)["\']', user_goal)

        if quoted:
            return quoted.group(1).strip()

        patterns = [
            r"(?:file|path|folder|directory)\s+([A-Za-z0-9_./\\-]+\.[A-Za-z0-9]+)",
            r"(?:in|inside|from)\s+([A-Za-z0-9_./\\-]+)",
            r"([A-Za-z0-9_./\\-]+\.[A-Za-z0-9]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, user_goal, flags=re.IGNORECASE)

            if match:
                return match.group(1).strip().strip(".,;:")

        return None

    def _extract_file_content(self, user_goal: str) -> str:
        patterns = [
            r"content\s*:\s*(.+)$",
            r"with content\s+(.+)$",
            r"containing\s+(.+)$",
            r"write\s+(.+?)\s+to\s+file",
        ]

        for pattern in patterns:
            match = re.search(pattern, user_goal, flags=re.IGNORECASE)

            if match:
                return match.group(1).strip().strip('"').strip("'")

        return "Created by AIRA-X."

    def _extract_python_code(self, user_goal: str) -> str | None:
        fenced = re.search(
            r"```(?:python)?\s*(.*?)```",
            user_goal,
            flags=re.IGNORECASE | re.DOTALL,
        )

        if fenced:
            code = fenced.group(1).strip()

            if code:
                return code

        patterns = [
            r"run python code\s*:?\s*(.+)$",
            r"python code\s*:?\s*(.+)$",
            r"execute python\s*:?\s*(.+)$",
            r"run this code\s*:?\s*(.+)$",
            r"code\s*:?\s*(.+)$",
        ]

        for pattern in patterns:
            match = re.search(pattern, user_goal, flags=re.IGNORECASE | re.DOTALL)

            if match:
                code = match.group(1).strip()

                if code:
                    return code

        return None

    def _build_python_code(self, user_goal: str) -> str | None:
        goal = user_goal.lower()

        expression = self._extract_math_expression(user_goal)

        if expression:
            return f"result = {expression}\nprint(result)"

        factorial_match = re.search(r"factorial(?:\s+of)?\s+(\d+)", goal)

        if factorial_match:
            number = int(factorial_match.group(1))

            return (
                "import math\n"
                f"number = {number}\n"
                "print(math.factorial(number))"
            )

        fibonacci_match = re.search(r"fibonacci(?:\s+of)?\s+(\d+)", goal)

        if fibonacci_match:
            number = int(fibonacci_match.group(1))

            return (
                f"n = {number}\n"
                "a, b = 0, 1\n"
                "sequence = []\n"
                "for _ in range(n):\n"
                "    sequence.append(a)\n"
                "    a, b = b, a + b\n"
                "print(sequence)"
            )

        if "hello world" in goal:
            return 'print("Hello, world!")'

        print_match = re.search(
            r"print\s+(.+)$",
            user_goal,
            flags=re.IGNORECASE,
        )

        if print_match:
            message = print_match.group(1).strip().strip('"').strip("'")
            safe_message = message.replace("\\", "\\\\").replace('"', '\\"')

            return f'print("{safe_message}")'

        return None

    def _extract_math_expression(self, user_goal: str) -> str | None:
        patterns = [
            r"(?:calculate|compute|evaluate)\s+([0-9+\-*/(). %]+)",
            r"what is\s+([0-9+\-*/(). %]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, user_goal, flags=re.IGNORECASE)

            if not match:
                continue

            expression = match.group(1).strip()

            if expression and re.fullmatch(r"[0-9+\-*/(). %]+", expression):
                return expression

        return None

    def _extract_shell_command(self, user_goal: str) -> str | None:
        patterns = [
            r"run command\s*:?\s*(.+)$",
            r"execute command\s*:?\s*(.+)$",
            r"shell command\s*:?\s*(.+)$",
            r"terminal command\s*:?\s*(.+)$",
        ]

        for pattern in patterns:
            match = re.search(pattern, user_goal, flags=re.IGNORECASE | re.DOTALL)

            if match:
                command = match.group(1).strip()

                if command:
                    return command

        return None

    def _extract_package_name(self, user_goal: str) -> str | None:
        match = re.search(
            r"(?:pip install|install package)\s+([A-Za-z0-9_.-]+)",
            user_goal,
            flags=re.IGNORECASE,
        )

        if match:
            return match.group(1).strip()

        return None

    def _extract_commit_message(self, user_goal: str) -> str:
        patterns = [
            r'-m\s+"([^"]+)"',
            r"-m\s+'([^']+)'",
            r'with message\s+"([^"]+)"',
            r"with message\s+'([^']+)'",
            r'message\s+"([^"]+)"',
            r"message\s+'([^']+)'",
        ]

        for pattern in patterns:
            match = re.search(pattern, user_goal, flags=re.IGNORECASE)

            if match:
                message = match.group(1).strip()

                if message:
                    return message

        return "AIRA-X automated commit"

    def _extract_push_target(self, user_goal: str) -> dict:
        goal = user_goal.strip()

        match = re.search(
            r"git\s+push\s+([A-Za-z0-9._/-]+)\s+([A-Za-z0-9._/-]+)",
            goal,
            flags=re.IGNORECASE,
        )

        if match:
            return {
                "remote": match.group(1).strip(),
                "branch": match.group(2).strip(),
            }

        match = re.search(
            r"push\s+to\s+([A-Za-z0-9._/-]+)\s+([A-Za-z0-9._/-]+)",
            goal,
            flags=re.IGNORECASE,
        )

        if match:
            return {
                "remote": match.group(1).strip(),
                "branch": match.group(2).strip(),
            }

        return {
            "remote": "origin",
            "branch": None,
        }
