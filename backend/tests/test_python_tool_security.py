import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from tools.tool_router import ToolRouter


def assert_true(condition, label):
    if not condition:
        raise AssertionError(f"{label} failed.")


print("Testing safe Python code...")

safe_result = ToolRouter.run(
    tool_name="python_tool",
    action="run_code",
    payload={"code": "print('AIRA-X Python security test')"},
)

assert_true(safe_result["success"], "Safe Python code should succeed")
assert_true(
    "AIRA-X Python security test" in safe_result["output"],
    "Safe Python code should return expected output",
)

print("✅ Safe Python code passed")


print("Testing blocked Python code...")

blocked_result = ToolRouter.run(
    tool_name="python_tool",
    action="run_code",
    payload={"code": "import os\nos.system('rm -rf /')"},
)

assert_true(
    blocked_result["success"] is False,
    "Dangerous Python code should fail",
)

assert_true(
    "blocked" in blocked_result["error"].lower(),
    "Dangerous Python code should return blocked error",
)

print("✅ Dangerous Python code blocked successfully")


print("Testing Python timeout...")

timeout_result = ToolRouter.run(
    tool_name="python_tool",
    action="run_code",
    payload={"code": "while True:\n    pass"},
)

assert_true(
    timeout_result["success"] is False,
    "Infinite Python code should fail safely",
)

assert_true(
    "timed out" in timeout_result["error"].lower(),
    "Infinite Python code should return timeout error",
)

print("✅ Python timeout handled safely")

print("\n🎉 Python Tool security tests passed!\n")