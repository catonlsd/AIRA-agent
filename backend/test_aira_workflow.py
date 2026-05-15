import asyncio

from graph.aira_workflow import AiraXWorkflow


async def main():
    workflow = AiraXWorkflow()

    state = await workflow.run("Build and deploy a RAG pipeline")

    print("Final Status:", state.status)
    print("Final Decision:", state.decision)
    print("Final Answer:", state.final_answer)
    print()

    print("Plan:")
    for step in state.plan:
        print(f"{step.id}. {step.title} | {step.status} | {step.assigned_agent}")

    print()

    print("Execution Outputs:")
    for output in state.execution_outputs:
        print(output)


if __name__ == "__main__":
    asyncio.run(main())
    