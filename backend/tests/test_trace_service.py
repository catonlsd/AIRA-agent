# File: backend/tests/test_trace_service.py

import pytest

from app.services.trace_service import TraceService, source_type_for_mode


def test_source_type_mapping():
    assert source_type_for_mode("general_chat") == "model"
    assert source_type_for_mode("web_research") == "web"
    assert source_type_for_mode("document_qa") == "documents"
    assert source_type_for_mode("execution") == "tools"
    assert source_type_for_mode("multi_question") == "mixed"
    assert source_type_for_mode("nonsense") == "unknown"


def test_persist_and_read_back(tmp_path):
    log = tmp_path / "traces.jsonl"
    service = TraceService(log_path=str(log))

    record = service.build_record(
        session_id="s1",
        run_id="r1",
        mode="general_chat",
        latency_ms=12.5,
        final_status="completed",
        trace_events=[{"name": "turn_started"}],
    )
    assert record["source_type"] == "model"
    assert record["created_at"]

    assert service.persist(record) is True

    records = service.recent(limit=10)
    assert len(records) == 1
    assert records[0]["session_id"] == "s1"
    assert records[0]["mode"] == "general_chat"
    assert records[0]["latency_ms"] == 12.5
    assert records[0]["final_status"] == "completed"


def test_recent_returns_newest_window(tmp_path):
    log = tmp_path / "traces.jsonl"
    service = TraceService(log_path=str(log))
    for i in range(5):
        service.persist(
            service.build_record(
                session_id=f"s{i}",
                run_id=f"r{i}",
                mode="execution",
                latency_ms=float(i),
                final_status="completed",
            )
        )

    recent = service.recent(limit=2)
    assert [r["session_id"] for r in recent] == ["s3", "s4"]


def test_persist_is_resilient_to_bad_path(tmp_path):
    # Parent is a regular file, so mkdir/write fails — but must never raise.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    service = TraceService(log_path=str(blocker / "traces.jsonl"))

    assert service.persist({"x": 1}) is False
    assert service.recent() == []


@pytest.mark.asyncio
async def test_supervisor_writes_a_trace(monkeypatch, tmp_path):
    import app.assistant_supervisor as sup
    from app.context_builder import build_turn_context

    log = tmp_path / "sup_traces.jsonl"
    monkeypatch.setenv("AIRA_TRACE_LOG", str(log))

    supervisor = sup.AssistantSupervisor()
    # Point its tracer at the temp log (constructed before the env override).
    supervisor.tracer = sup.TraceService(log_path=str(log))

    ctx = build_turn_context("hello there", session_id="sess-trace")
    await supervisor.run_turn(ctx)

    records = supervisor.tracer.recent(limit=5)
    assert len(records) == 1
    assert records[0]["session_id"] == "sess-trace"
    assert records[0]["mode"] == "general_chat"
    assert records[0]["source_type"] == "model"
    assert any(e["name"] == "turn_started" for e in records[0]["trace_events"])
