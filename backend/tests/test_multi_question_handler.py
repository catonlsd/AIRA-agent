import pytest

from app.multi_question_handler import handle_multi_question_prompt


@pytest.mark.asyncio
async def test_single_prompt_passes_through_without_batching():
    async def fake_runner(prompt: str) -> dict:
        return {
            "run_id": "single-run",
            "status": "completed",
            "decision": "completed",
            "final_answer": f"Handled: {prompt}",
            "message": f"Handled: {prompt}",
            "sources": [{"type": "note", "value": "single"}],
            "artifacts": [],
            "approval_summary": None,
        }

    result = await handle_multi_question_prompt(
        prompt="Explain what LangGraph is.",
        run_single_prompt=fake_runner,
    )

    assert result["run_id"] == "single-run"
    assert result["status"] == "completed"
    assert result["final_answer"] == "Handled: Explain what LangGraph is."
    assert result["message"] == "Handled: Explain what LangGraph is."
    assert result["sources"] == [{"type": "note", "value": "single"}]
    assert result["artifacts"] == []
    assert result["approval_summary"] is None


@pytest.mark.asyncio
async def test_multiple_questions_are_answered_separately():
    async def fake_runner(prompt: str) -> dict:
        return {
            "run_id": f"run-{prompt}",
            "status": "completed",
            "decision": "completed",
            "final_answer": f"Answer for: {prompt}",
            "message": f"Answer for: {prompt}",
            "sources": [{"type": "qa", "question": prompt}],
            "artifacts": [{"type": "text", "name": f"{prompt}.txt"}],
            "approval_summary": None,
        }

    prompt = """
    Answer the following questions:
    1. What is Python?
    2. What is LangGraph?
    3. What is ChromaDB?
    """

    result = await handle_multi_question_prompt(
        prompt=prompt,
        run_single_prompt=fake_runner,
    )

    assert result["status"] == "completed"
    assert result["decision"] == "multi_question_completed"
    assert result["message"] == result["final_answer"]
    assert result["meta"]["is_multi_question"] is True
    assert result["meta"]["question_count"] == 3
    assert result["meta"]["completed_count"] == 3
    assert len(result["sub_answers"]) == 3

    assert result["sub_answers"][0]["question"] == "What is Python?"
    assert result["sub_answers"][0]["message"] == "Answer for: What is Python?"
    assert result["sub_answers"][0]["answer"] == "Answer for: What is Python?"
    assert result["sub_answers"][0]["sources"] == [{"type": "qa", "question": "What is Python?"}]
    assert result["sub_answers"][0]["artifacts"] == [{"type": "text", "name": "What is Python?.txt"}]
    assert result["sub_answers"][0]["approval_summary"] is None

    assert result["sub_answers"][1]["question"] == "What is LangGraph?"
    assert result["sub_answers"][2]["question"] == "What is ChromaDB?"

    assert "1. What is Python?" in result["final_answer"]
    assert "2. What is LangGraph?" in result["final_answer"]
    assert "3. What is ChromaDB?" in result["final_answer"]

    assert len(result["sources"]) == 3
    assert len(result["artifacts"]) == 3
    assert result["approval_summary"] is None


@pytest.mark.asyncio
async def test_requires_approval_is_preserved_per_question():
    async def fake_runner(prompt: str) -> dict:
        if "install" in prompt.lower():
            return {
                "run_id": "approval-run",
                "status": "requires_approval",
                "decision": "approval_required",
                "final_answer": "This action requires approval before execution.",
                "message": "This action requires approval before execution.",
                "sources": [],
                "artifacts": [],
                "approval_summary": {
                    "required": True,
                    "action": prompt,
                    "message": "Approval required before execution.",
                },
            }

        return {
            "run_id": "safe-run",
            "status": "completed",
            "decision": "completed",
            "final_answer": f"Completed safely: {prompt}",
            "message": f"Completed safely: {prompt}",
            "sources": [],
            "artifacts": [],
            "approval_summary": None,
        }

    prompt = """
    Answer the following questions:
    1. What is Python?
    2. Install requests package.
    """

    result = await handle_multi_question_prompt(
        prompt=prompt,
        run_single_prompt=fake_runner,
    )

    assert result["status"] == "requires_approval"
    assert result["decision"] == "multi_question_requires_approval"
    assert result["meta"]["requires_approval_count"] == 1
    assert result["approval_summary"] is not None
    assert len(result["approval_summary"]) == 1

    approval_item = result["approval_summary"][0]
    assert approval_item["question_number"] == 2
    assert approval_item["question"] == "Install requests package."
    assert approval_item["run_id"] == "approval-run"
    assert approval_item["approval_summary"]["required"] is True

    assert result["sub_answers"][0]["status"] == "completed"
    assert result["sub_answers"][1]["status"] == "requires_approval"
    assert "requires approval" in result["sub_answers"][1]["message"].lower()


@pytest.mark.asyncio
async def test_failed_question_marks_batch_as_partially_completed():
    async def fake_runner(prompt: str) -> dict:
        if "second" in prompt.lower():
            return {
                "run_id": "failed-run",
                "status": "failed",
                "decision": "execution_failed",
                "final_answer": "I could not complete this question.",
                "message": "I could not complete this question.",
                "sources": [],
                "artifacts": [],
                "approval_summary": None,
            }

        return {
            "run_id": "ok-run",
            "status": "completed",
            "decision": "completed",
            "final_answer": f"Done: {prompt}",
            "message": f"Done: {prompt}",
            "sources": [],
            "artifacts": [],
            "approval_summary": None,
        }

    prompt = """
    Answer the following questions:
    1. First question
    2. Second question
    3. Third question
    """

    result = await handle_multi_question_prompt(
        prompt=prompt,
        run_single_prompt=fake_runner,
    )

    assert result["status"] == "partially_completed"
    assert result["decision"] == "multi_question_partially_completed"
    assert result["meta"]["failed_count"] == 1
    assert len(result["sub_answers"]) == 3
    assert result["sub_answers"][1]["status"] == "failed"
    assert result["sub_answers"][1]["message"] == "I could not complete this question."


@pytest.mark.asyncio
async def test_too_many_questions_is_blocked():
    async def fake_runner(prompt: str) -> dict:
        return {
            "run_id": "unused",
            "status": "completed",
            "decision": "completed",
            "final_answer": prompt,
            "message": prompt,
            "sources": [],
            "artifacts": [],
            "approval_summary": None,
        }

    prompt = """
    Answer the following questions:
    1. One
    2. Two
    3. Three
    """

    result = await handle_multi_question_prompt(
        prompt=prompt,
        run_single_prompt=fake_runner,
        max_questions=2,
    )

    assert result["status"] == "failed"
    assert result["decision"] == "too_many_questions"
    assert result["sub_answers"] == []
    assert result["sources"] == []
    assert result["artifacts"] == []
    assert result["approval_summary"] is None
    assert result["message"] == result["final_answer"]
    assert result["meta"]["question_count"] == 3
    assert result["meta"]["max_questions"] == 2