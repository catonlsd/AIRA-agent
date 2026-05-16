import subprocess
from typing import Dict, Any


class PythonTool:
    name = "python_tool"

    @staticmethod
    def run_code(code: str) -> Dict[str, Any]:
        try:
            result = subprocess.run(
                ["python", "-c", code],
                capture_output=True,
                text=True,
                timeout=30,
            )

            return {
                "success": result.returncode == 0,
                "tool_name": "python_tool",
                "action": "run_code",
                "output": result.stdout,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
            }

        except Exception as e:
            return {
                "success": False,
                "tool_name": "python_tool",
                "action": "run_code",
                "output": "",
                "error": str(e),
            }