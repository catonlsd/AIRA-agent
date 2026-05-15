import asyncio

from schemas.aira_state import AiraXState
from agents.planner.planner_agent import PlannerAgent
from agents.execution.execution_agent import ExecutionAgent


async def main():
    state = AiraXState(user_goal="Build and deploy a RAG pipeline")

    planner = PlannerAgent()
    executor = ExecutionAgent()

    state = await planner.run(state)
    state.current_step = 3

    state = await executor.run(state)

    print("Status:", state.status)
    print("Decision:", state.decision)

    for step in state.plan:
        print(step.id, step.title, step.status, step.result)


if __name__ == "__main__":
    asyncio.run(main())