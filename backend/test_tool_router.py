from tools.tool_router import ToolRouter


shell_result = ToolRouter.run(
    tool_name="shell_tool",
    action="run",
    payload={"command": "echo AIRA-X Tool Router Shell Test"},
)

print("SHELL RESULT:", shell_result)

file_write_result = ToolRouter.run(
    tool_name="file_tool",
    action="write_file",
    payload={
        "path": "tmp/router_test.txt",
        "content": "AIRA-X Tool Router File Test",
    },
)

print("FILE WRITE RESULT:", file_write_result)

file_read_result = ToolRouter.run(
    tool_name="file_tool",
    action="read_file",
    payload={"path": "tmp/router_test.txt"},
)

print("FILE READ RESULT:", file_read_result)