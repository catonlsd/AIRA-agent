from typing import Dict, Any

from tools.shell.shell_tool import ShellTool
from tools.filesystem.file_tool import FileTool
from tools.python.python_tool import PythonTool
from tools.git.git_tool import GitTool
from tools.tool_registry import ToolRegistry


class ToolRouter:
    name = "tool_router"

    @staticmethod
    def run(tool_name: str, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not ToolRegistry.is_tool_available(tool_name):
            return {
                "success": False,
                "tool_name": tool_name,
                "action": action,
                "output": "",
                "error": f"Unknown tool: {tool_name}",
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
            command = payload.get("command")

            if not command:
                return {
                    "success": False,
                    "tool_name": tool_name,
                    "action": action,
                    "output": "",
                    "error": "Missing command for shell_tool.",
                }

            return ShellTool.run(command)

        if tool_name == "file_tool":
            if action == "read_file":
                return FileTool.read_file(payload.get("path", ""))

            if action == "write_file":
                return FileTool.write_file(
                    payload.get("path", ""),
                    payload.get("content", ""),
                )

            if action == "list_files":
                return FileTool.list_files(payload.get("path", "."))

        if tool_name == "python_tool":
            if action == "run_code":
                code = payload.get("code")

                if not code:
                    return {
                        "success": False,
                        "tool_name": tool_name,
                        "action": action,
                        "output": "",
                        "error": "Missing code for python_tool.",
                    }

                return PythonTool.run_code(code)

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

        return {
            "success": False,
            "tool_name": tool_name,
            "action": action,
            "output": "",
            "error": f"No execution handler found for {tool_name}:{action}.",
        }