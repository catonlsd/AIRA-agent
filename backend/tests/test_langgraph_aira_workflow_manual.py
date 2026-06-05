import asyncio

from graph.langgraph_aira_workflow import LangGraphAiraXWorkflow


async def main():
    workflow = LangGraphAiraXWorkflow()

    state = await workflow.run(
        'run python code: print("Hello from LangGraph AIRA-X")',
        run_id="langgraph-manual-test",
    )

    print("STATUS:", state.status)
    print("DECISION:", state.decision)
    print("FINAL ANSWER:")
    print(state.final_answer)
    print()
    print("PLAN STEPS:", len(state.plan))
    print("EXECUTION OUTPUTS:", len(state.execution_outputs))


if __name__ == "__main__":
    asyncio.run(main())