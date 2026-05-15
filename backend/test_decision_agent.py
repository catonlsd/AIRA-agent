import asyncio

from schemas.aira_state import AiraXState
from agents.planner.planner_agent import PlannerAgent
from agents.decision.decision_agent import DecisionAgent


async def main():
    state = AiraXState(user_goal="Build and deploy a RAG pipeline")

    planner = PlannerAgent()
    decision = DecisionAgent()

    state = await planner.run(state)
    state = await decision.run(state)

    print("Status:", state.status)
    print("Decision:", state.decision)
    print("Current Step:", state.current_step)

    for step in state.plan:
        print(step.id, step.title, step.status, step.assigned_agent)


if __name__ == "__main__":
    asyncio.run(main())