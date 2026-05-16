import subprocess
from typing import Dict, Any


class ShellTool:
    name = "shell_tool"

    @staticmethod
    def run(command: str) -> Dict[str, Any]:
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )

            return {
                "success": result.returncode == 0,
                "tool_name": "shell_tool",
                "action": "run",
                "command": command,
                "output": result.stdout,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
            }

        except Exception as e:
            return {
                "success": False,
                "tool_name": "shell_tool",
                "action": "run",
                "command": command,
                "output": "",
                "error": str(e),
            }