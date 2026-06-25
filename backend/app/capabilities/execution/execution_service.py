# File: backend/app/capabilities/execution/execution_service.py
"""
Execution capability.

Wraps the LangGraph execution workflow as a service the supervisor calls. The
workflow itself (`graph/langgraph_aira_workflow.py`) stays the execution
subgraph; this service is the thin boundary the supervisor talks to.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.turn_classifier import EXECUTION_MODE, RESEARCH_THEN_EXECUTION_MODE


class ExecutionService:
    """Runs a toolable/executable goal through the workflow and normalizes it."""

    async def run(self, goal: str, *, mode: str, run_id: str | None = None) -> dict[str, Any]:
        # Imported lazily, and via the route module, so test monkeypatches on
        # aira_x.LangGraphAiraXWorkflow / WorkflowStore still take effect, and to
        # avoid an import cycle while these helpers still live in the route.
        from app.routes import aira_x as ax

        run_id = run_id or uuid4().hex

        workflow = ax.LangGraphAiraXWorkflow()
        state = await workflow.run(goal, run_id=run_id)
        ax.WorkflowStore.save(state)

        cleaned = ax._build_clean_single_run_response(ax.serialize_state(state))
        cleaned["mode"] = (
            RESEARCH_THEN_EXECUTION_MODE
            if mode == RESEARCH_THEN_EXECUTION_MODE
            else EXECUTION_MODE
        )
        return cleaned
