from tools.tool_router import ToolRouter


result = ToolRouter.run(
    tool_name="python_tool",
    action="run_code",
    payload={
        "code": "print('AIRA-X Python Tool Working')"
    },
)

print(result)