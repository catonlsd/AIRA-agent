# File: backend/app/multi_question_handler.py

from __future__ import annotations

from typing import Any, Awaitable, Callable
from uuid import uuid4

from app.prompt_parsing import ParsedPrompt, ParsedQuestion, parse_prompt_for_questions


SinglePromptRunner = Callable[[str], Awaitable[dict[str, Any]]]


async def handle_multi_question_prompt(
    prompt: str,
    run_single_prompt: SinglePromptRunner,
    max_questions: int = 20,
) -> dict[str, Any]:
    parsed = parse_prompt_for_questions(prompt)

    if not parsed.is_multi_question:
        return await run_single_prompt(prompt)

    if len(parsed.questions) > max_questions:
        message = (
            f"I found {len(parsed.questions)} questions in your prompt. "
            f"Please send at most {max_questions} questions in one request."
        )

        return {
            "run_id": str(uuid4()),
            "status": "failed",
            "decision": "too_many_questions",
            "final_answer": message,
            "message": message,
            "sources": [],
            "artifacts": [],
            "approval_summary": None,
            "sub_answers": [],
            "meta": {
                "is_multi_question": True,
                "question_count": len(parsed.questions),
                "max_questions": max_questions,
                "completed_count": 0,
                "failed_count": 0,
                "requires_approval_count": 0,
            },
        }

    sub_answers: list[dict[str, Any]] = []

    for position, question in enumerate(parsed.questions, start=1):
        child_result = await run_single_prompt(question.text)
        normalized_child = _normalize_child_result(
            position=position,
            question=question,
            child_result=_coerce_dict(child_result),
        )
        sub_answers.append(normalized_child)

    final_status = _derive_final_status(sub_answers)
    final_decision = _derive_final_decision(final_status)
    final_answer = _compose_final_answer(parsed, sub_answers)

    sources = _dedupe_dict_list(
        source
        for child in sub_answers
        for source in child.get("sources", [])
        if isinstance(source, dict)
    )
    artifacts = _dedupe_dict_list(
        artifact
        for child in sub_answers
        for artifact in child.get("artifacts", [])
        if isinstance(artifact, dict)
    )

    approval_summary = [
        {
            "question_number": child["question_number"],
            "question": child["question"],
            "run_id": child.get("run_id"),
            "approval_summary": child.get("approval_summary"),
        }
        for child in sub_answers
        if child.get("approval_summary") is not None
    ] or None

    return {
        "run_id": str(uuid4()),
        "status": final_status,
        "decision": final_decision,
        "final_answer": final_answer,
        "message": final_answer,
        "sources": sources,
        "artifacts": artifacts,
        "approval_summary": approval_summary,
        "sub_answers": sub_answers,
        "meta": {
            "is_multi_question": True,
            "question_count": len(sub_answers),
            "completed_count": sum(1 for item in sub_answers if item["status"] == "completed"),
            "failed_count": sum(1 for item in sub_answers if item["status"] == "failed"),
            "requires_approval_count": sum(
                1 for item in sub_answers if item["status"] == "requires_approval"
            ),
        },
    }


def _normalize_child_result(
    position: int,
    question: ParsedQuestion,
    child_result: dict[str, Any],
) -> dict[str, Any]:
    message = _extract_answer_text(child_result)

    sources = child_result.get("sources")
    if not isinstance(sources, list):
        sources = []

    artifacts = child_result.get("artifacts")
    if not isinstance(artifacts, list):
        artifacts = []

    approval_summary = child_result.get("approval_summary")
    if approval_summary is None:
        approval_summary = child_result.get("approval")

    return {
        "question_number": position,
        "original_question_number": question.number,
        "question": question.text,
        "run_id": child_result.get("run_id"),
        "status": str(child_result.get("status", "completed")),
        "decision": child_result.get("decision"),
        "answer": message,
        "message": message,
        "sources": [item for item in sources if isinstance(item, dict)],
        "artifacts": [item for item in artifacts if isinstance(item, dict)],
        "approval_summary": approval_summary,
        "raw_result": child_result,
    }


def _extract_answer_text(child_result: dict[str, Any]) -> str:
    for field_name in ("message", "final_answer", "answer"):
        value = child_result.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return "No answer was generated for this question."


def _derive_final_status(sub_answers: list[dict[str, Any]]) -> str:
    statuses = {item["status"] for item in sub_answers}

    if statuses == {"completed"}:
        return "completed"

    if "requires_approval" in statuses:
        return "requires_approval"

    if statuses == {"failed"}:
        return "failed"

    if "failed" in statuses:
        return "partially_completed"

    return "completed"


def _derive_final_decision(status: str) -> str:
    mapping = {
        "completed": "multi_question_completed",
        "failed": "multi_question_failed",
        "partially_completed": "multi_question_partially_completed",
        "requires_approval": "multi_question_requires_approval",
    }
    return mapping.get(status, "multi_question_completed")


def _compose_final_answer(
    parsed: ParsedPrompt,
    sub_answers: list[dict[str, Any]],
) -> str:
    lines: list[str] = []

    lines.append("I found multiple questions in your prompt and answered each one separately.")
    lines.append("")

    if parsed.intro_text:
        lines.append(f"Request understood: {parsed.intro_text}")
        lines.append("")

    lines.extend(_build_summary_block(sub_answers))
    lines.append("")

    for item in sub_answers:
        lines.extend(_build_question_block(item))
        lines.append("")

    return "\n".join(line for line in lines).strip()


def _build_summary_block(sub_answers: list[dict[str, Any]]) -> list[str]:
    completed_count = sum(1 for item in sub_answers if item["status"] == "completed")
    failed_count = sum(1 for item in sub_answers if item["status"] == "failed")
    approval_count = sum(1 for item in sub_answers if item["status"] == "requires_approval")

    return [
        "Summary:",
        f"- Total questions: {len(sub_answers)}",
        f"- Completed: {completed_count}",
        f"- Requires approval: {approval_count}",
        f"- Failed: {failed_count}",
    ]


def _build_question_block(item: dict[str, Any]) -> list[str]:
    lines: list[str] = [
        f"{item['question_number']}. {item['question']}",
        f"Status: {_humanize_status(item['status'])}",
        "",
    ]

    if item["status"] == "requires_approval":
        lines.append("This item requires approval before it can be completed.")
        lines.append("")
        lines.append("Current response:")
        lines.append(item["message"])
        return lines

    if item["status"] == "failed":
        lines.append("This item could not be completed successfully.")
        lines.append("")
        lines.append("Current response:")
        lines.append(item["message"])
        return lines

    lines.append("Answer:")
    lines.append(item["message"])
    return lines


def _humanize_status(status: str) -> str:
    mapping = {
        "completed": "Completed",
        "failed": "Failed",
        "requires_approval": "Requires approval",
        "partially_completed": "Partially completed",
    }
    return mapping.get(status, status.replace("_", " ").strip().title())


def _dedupe_dict_list(items) -> list[dict[str, Any]]:
    unique_items: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in items:
        marker = repr(sorted(item.items()))
        if marker in seen:
            continue
        seen.add(marker)
        unique_items.append(item)

    return unique_items


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value

    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        if isinstance(dumped, dict):
            return dumped

    if hasattr(value, "dict"):
        dumped = value.dict()
        if isinstance(dumped, dict):
            return dumped

    raise TypeError(
        "run_single_prompt must return a dictionary or a Pydantic model."
    )