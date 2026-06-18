# File: backend/tests/conftest.py
"""
Shared test fixtures.

The suite must stay hermetic: even though a real LLM provider may be configured
in the environment, tests must never make live API calls (slow, costly,
non-deterministic). We stub ``LLMClient.generate`` for every test with a
deterministic, branded response. The execution workflow itself is
LLM-free, so this only affects conversational/general-chat paths.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

sys.path.append(str(Path(__file__).resolve().parents[1]))

# Keep turn traces out of ./storage during tests — write them to a temp file.
os.environ.setdefault(
    "AIRA_TRACE_LOG", str(Path(tempfile.gettempdir()) / "aira_x_test_traces.jsonl")
)

# Use the dependency-free embedding backend in tests (no model download / torch
# load), and keep any persistent Chroma data in a temp dir.
os.environ.setdefault("AIRA_EMBEDDING_PROVIDER", "hashing")
os.environ.setdefault("AIRA_CHROMA_DIR", str(Path(tempfile.gettempdir()) / "aira_x_test_chroma"))

import app.core.llm as llm_module
from app.routes.aira_x import AiraXRunRequest, run_aira_x


_STUB_LLM_RESPONSE = "Hello! I am AIRA-X, your AI assistant. How can I help you today?"


@pytest.fixture(autouse=True)
def stub_llm(monkeypatch):
    """Replace live LLM calls with a deterministic branded response."""

    def _fake_generate(self, system: str, prompt: str, temperature: float = 0.2) -> str:
        return _STUB_LLM_RESPONSE

    monkeypatch.setattr(llm_module.LLMClient, "generate", _fake_generate)


@pytest.fixture(autouse=True)
def _isolate_guided_flows():
    """Guided-flow state, usage quotas, and memory are durable / process-local —
    wipe them between tests so pending approvals, quota counters, and saved
    preferences never leak across tests or owners."""
    from app.activity import activity_service
    from app.artifacts.images import set_image_provider
    from app.bundles import bundle_service
    from app.core.config import settings
    from app.execution_queue import execution_queue
    from app.guided_flow_store import guided_flow_store
    from app.memory.preference_memory import preference_memory
    from app.memory.session_memory import session_memory
    from app.middleware import reset_rate_limit
    from app.observability import observability
    from app.pins import pin_service
    from app.usage_limits import usage_limiter

    # Keep tests hermetic: no live web grounding, no network image sourcing.
    settings.artifact_research_grounding = False
    settings.enable_artifact_images = False
    set_image_provider(None)

    guided_flow_store.clear_all()
    usage_limiter.reset()
    reset_rate_limit()  # fresh per-minute window per test (shared unauth bucket)
    preference_memory.clear_all()
    session_memory.clear_all()
    activity_service.clear_all()
    pin_service.clear_all()
    bundle_service.clear_all()
    execution_queue.clear_all()
    observability.clear_all()
    yield
    guided_flow_store.clear_all()
    usage_limiter.reset()
    reset_rate_limit()
    preference_memory.clear_all()
    session_memory.clear_all()
    activity_service.clear_all()
    pin_service.clear_all()
    bundle_service.clear_all()
    execution_queue.clear_all()
    set_image_provider(None)


@pytest_asyncio.fixture
async def sample_run():
    """A real completed workflow run, persisted to the workflow store.

    Used by the workflow runs/detail API tests, which assert the run shows up
    in history. The hand-rolled suite originally passed this in manually from
    ``main()``; under pytest it is provided as a proper fixture.
    """
    return await run_aira_x(
        AiraXRunRequest(goal='run python code: print("Hello from AIRA-X")')
    )
