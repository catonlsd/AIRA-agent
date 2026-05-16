from typing import Dict, Any

from tools.shell.shell_tool import ShellTool
from tools.filesystem.file_tool import FileTool
from tools.python.python_tool import PythonTool


class ToolRouter:
    name = "tool_router"

    @staticmethod
    def run(tool_name: str, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "shell_tool":
            command = payload.get("command")

            if not command:
                return {
                    "success": False,
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

            return {
                "success": False,
                "error": f"Unknown file_tool action: {action}",
            }

        if tool_name == "python_tool":
            if action == "run_code":
                code = payload.get("code")

                if not code:
                    return {
                        "success": False,
                        "error": "Missing code for python_tool.",
                    }

                return PythonTool.run_code(code)

            return {
                "success": False,
                "error": f"Unknown python_tool action: {action}",
            }

        return {
            "success": False,
            "error": f"Unknown tool: {tool_name}",
        }