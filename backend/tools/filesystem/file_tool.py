from pathlib import Path
from typing import Dict, Any


class FileTool:
    name = "file_tool"

    @staticmethod
    def read_file(path: str) -> Dict[str, Any]:
        try:
            file_path = Path(path)

            if not file_path.exists():
                return {
                    "success": False,
                    "path": path,
                    "error": "File does not exist.",
                }

            return {
                "success": True,
                "tool_name": "file_tool",
                "action": "read_file",
                "path": path,
                "output": file_path.read_text(encoding="utf-8"),
                "content": file_path.read_text(encoding="utf-8"),
            }

        except Exception as e:
            return {
                "success": False,
                "path": path,
                "error": str(e),
            }

    @staticmethod
    def write_file(path: str, content: str) -> Dict[str, Any]:
        try:
            file_path = Path(path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

            return {
                "success": True,
                "tool_name": "file_tool",
                "action": "write_file",
                "path": path,
                "output": "File written successfully.",
                "message": "File written successfully.",
            }

        except Exception as e:
            return {
                "success": False,
                "path": path,
                "error": str(e),
            }

    @staticmethod
    def list_files(path: str = ".") -> Dict[str, Any]:
        try:
            folder = Path(path)

            if not folder.exists():
                return {
                    "success": False,
                    "path": path,
                    "error": "Path does not exist.",
            }

            files = [str(item) for item in folder.iterdir()]

            return {
                "success": True,
                "tool_name": "file_tool",
                "action": "list_files",
                "path": path,
                "output": files,
                "files": files,
            }

        except Exception as e:
            return {
                "success": False,
                "path": path,
                "error": str(e),
            }