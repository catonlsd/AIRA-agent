import asyncio

from schemas.aira_state import AiraXState
from agents.planner.planner_agent import PlannerAgent
from agents.reflection.reflection_agent import ReflectionAgent


async def main():
    state = AiraXState(user_goal="Build and deploy a RAG pipeline")

    planner = PlannerAgent()
    reflector = ReflectionAgent()

    state = await planner.run(state)

    state.current_step = 3
    failed_step = state.plan[2]
    failed_step.status = "failed"
    failed_step.error = "Dependency installation failed"

    state = await reflector.run(state)

    print("Workflow Status:", state.status)
    print("Decision:", state.decision)
    print("Retry Count:", state.retry_count)
    print("Memory:", state.memory)

    for step in state.plan:
        print(step.id, step.title, step.status, step.error)


if __name__ == "__main__":
    asyncio.run(main())