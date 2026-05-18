from tools.tool_router import ToolRouter


print("GIT STATUS TEST")
status_result = ToolRouter.run(
    tool_name="git_tool",
    action="status",
    payload={},
)
print(status_result)


print("\nGIT BRANCH TEST")
branch_result = ToolRouter.run(
    tool_name="git_tool",
    action="branch",
    payload={},
)
print(branch_result)


print("\nGIT RECENT COMMITS TEST")
log_result = ToolRouter.run(
    tool_name="git_tool",
    action="recent_commits",
    payload={"limit": 5},
)
print(log_result)


print("\nGIT DIFF SUMMARY TEST")
diff_result = ToolRouter.run(
    tool_name="git_tool",
    action="diff",
    payload={},
)
print(diff_result)


print("\nGIT FULL DIFF TEST")
full_diff_result = ToolRouter.run(
    tool_name="git_tool",
    action="full_diff",
    payload={},
)
print(full_diff_result)