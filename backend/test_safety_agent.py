import asyncio

from schemas.aira_state import AiraXState
from agents.safety.safety_agent import SafetyAgent


async def main():
    safety = SafetyAgent()

    safe_state = AiraXState(user_goal="List files")
    safe_state.memory["pending_action"] = "dir"

    safe_state = await safety.run(safe_state)

    print("SAFE TEST")
    print("Status:", safe_state.status)
    print("Decision:", safe_state.decision)
    print()

    unsafe_state = AiraXState(user_goal="Delete everything")
    unsafe_state.memory["pending_action"] = "rm -rf /"

    unsafe_state = await safety.run(unsafe_state)

    print("UNSAFE TEST")
    print("Status:", unsafe_state.status)
    print("Decision:", unsafe_state.decision)
    print("Final Answer:", unsafe_state.final_answer)


if __name__ == "__main__":
    asyncio.run(main())
    