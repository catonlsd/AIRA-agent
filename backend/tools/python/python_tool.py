import subprocess
import sys
from pathlib import Path
from typing import Dict, Any


class PythonTool:
    name = "python_tool"

    blocked_patterns = [
        "os.system",
        "subprocess",
        "shutil.rmtree",
        "socket",
        "requests.",
        "urllib",
        "httpx",
        "eval(",
        "exec(",
        "__import__",
        "open(",
        "Path(",
        "unlink(",
        "remove(",
        "rmdir(",
        "write_text(",
        "write_bytes(",
        "chmod(",
        "chown(",
    ]

    @staticmethod
    def _workspace_root() -> Path:
        return Path(__file__).resolve().parents[2]

    @staticmethod
    def _is_blocked(code: str) -> str | None:
        normalized_code = code.lower()

        for pattern in PythonTool.blocked_patterns:
            if pattern.lower() in normalized_code:
                return pattern

        return None

    @staticmethod
    def run_code(code: str) -> Dict[str, Any]:
        try:
            if not code or not code.strip():
                return {
                    "success": False,
                    "tool_name": "python_tool",
                    "action": "run_code",
                    "output": "",
                    "error": "Empty Python code is not allowed.",
                }

            blocked_pattern = PythonTool._is_blocked(code)

            if blocked_pattern:
                return {
                    "success": False,
                    "tool_name": "python_tool",
                    "action": "run_code",
                    "output": "",
                    "error": (
                        "Python code blocked by PythonTool security guard. "
                        f"Matched pattern: {blocked_pattern}"
                    ),
                    "blocked_pattern": blocked_pattern,
                }

            workspace_root = PythonTool._workspace_root()

            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=workspace_root,
                capture_output=True,
                text=True,
                timeout=10,
            )

            output = result.stdout.strip() or result.stderr.strip()

            return {
                "success": result.returncode == 0,
                "tool_name": "python_tool",
                "action": "run_code",
                "code": code,
                "cwd": str(workspace_root),
                "output": output,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "tool_name": "python_tool",
                "action": "run_code",
                "code": code,
                "output": "",
                "error": "Python code execution timed out.",
            }

        except Exception as e:
            return {
                "success": False,
                "tool_name": "python_tool",
                "action": "run_code",
                "code": code,
                "output": "",
                "error": str(e),
            }