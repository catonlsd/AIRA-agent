from tools.tool_registry import ToolRegistry
from tools.tool_router import ToolRouter


print("AVAILABLE TOOLS:")
for tool in ToolRegistry.describe_tools():
    print(tool)


print("\nVALID TOOL TEST:")
valid_result = ToolRouter.run(
    tool_name="python_tool",
    action="run_code",
    payload={"code": "print('Tool registry test working')"},
)

print(valid_result)


print("\nINVALID TOOL TEST:")
invalid_tool_result = ToolRouter.run(
    tool_name="unknown_tool",
    action="run",
    payload={},
)

print(invalid_tool_result)


print("\nINVALID ACTION TEST:")
invalid_action_result = ToolRouter.run(
    tool_name="python_tool",
    action="delete_file",
    payload={},
)

print(invalid_action_result)