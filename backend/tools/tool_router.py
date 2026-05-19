from typing import Dict, Any

from tools.shell.shell_tool import ShellTool
from tools.filesystem.file_tool import FileTool
from tools.python.python_tool import PythonTool
from tools.git.git_tool import GitTool
from tools.tool_registry import ToolRegistry


class ToolRouter:
    name = "tool_router"

    @staticmethod
    def run(tool_name: str, action: str, payload: Dict[str, Any] | None = None):
        if payload is None:
            payload = {}

        if not ToolRegistry.is_tool_available(tool_name):
            return {
                "success": False,
                "tool_name": tool_name,
                "action": action,
                "output": "",
                "error": f"Tool '{tool_name}' is not registered.",
            }

        if not ToolRegistry.is_action_allowed(tool_name, action):
            return {
                "success": False,
                "tool_name": tool_name,
                "action": action,
                "output": "",
                "error": f"Action '{action}' is not allowed for tool '{tool_name}'.",
            }

        if tool_name == "shell_tool":
            if action == "run":
                command = payload.get("command", "")
                return ShellTool.run(command=command)

        if tool_name == "file_tool":
            if action == "read_file":
                path = payload.get("path", "")
                return FileTool.read_file(path=path)

            if action == "write_file":
                path = payload.get("path", "")
                content = payload.get("content", "")
                return FileTool.write_file(path=path, content=content)

            if action == "list_files":
                path = payload.get("path", ".")
                return FileTool.list_files(path=path)

        if tool_name == "python_tool":
            if action == "run_code":
                code = payload.get("code", "")
                return PythonTool.run_code(code=code)

        if tool_name == "git_tool":
            if action == "status":
                return GitTool.status()

            if action == "branch":
                return GitTool.branch()

            if action == "recent_commits":
                limit = payload.get("limit", 5)
                return GitTool.recent_commits(limit=limit)

            if action == "diff":
                return GitTool.diff()

            if action == "full_diff":
                return GitTool.full_diff()

            if action == "staged_files":
                return GitTool.staged_files()

            if action == "staged_diff":
                return GitTool.staged_diff()

            if action == "full_staged_diff":
                return GitTool.full_staged_diff()

            if action == "stage_all":
                return GitTool.stage_all()

            if action == "unstage_all":
                return GitTool.unstage_all()

            if action == "commit":
                message = payload.get("message", "AIRA-X automated commit")
                return GitTool.commit(message=message)

        return {
            "success": False,
            "tool_name": tool_name,
            "action": action,
            "output": "",
            "error": f"No router implementation for {tool_name}.{action}.",
        }