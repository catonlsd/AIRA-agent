# File: backend/app/prompt_parsing.py

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import List


@dataclass(slots=True)
class ParsedQuestion:
    number: int
    text: str


@dataclass(slots=True)
class ParsedPrompt:
    original_text: str
    cleaned_text: str
    is_multi_question: bool
    intro_text: str
    questions: List[ParsedQuestion]


_BULLET_QUESTION_RE = re.compile(r"^\s*[-*•]\s+(.*)$")

_LINE_NUMBERED_QUESTION_RE = re.compile(
    r"""
    ^\s*
    (?:
        question\s*
        |
        q(?:uestion)?\s*
        |
        q\s*\.?\s*no\.?\s*
    )?
    (?P<number>\d{1,3})
    \s*
    [\)\.\:\-]+
    \s*
    (?P<text>.*)
    $
    """,
    re.IGNORECASE | re.VERBOSE,
)

_INLINE_NUMBERED_QUESTION_RE = re.compile(
    r"""
    (?ix)
    (?<![A-Za-z0-9])
    (?:
        question\s*
        |
        q(?:uestion)?\s*
        |
        q\s*\.?\s*no\.?\s*
    )?
    (?P<number>\d{1,3})
    \s*
    [\)\.\:\-]+
    \s*
    """,
    re.VERBOSE,
)

_MULTI_QUESTION_INTRO_RE = re.compile(
    r"\b(answer|solve|respond to|reply to|handle)\b.*\b(question|questions)\b",
    re.IGNORECASE,
)

_PLACEHOLDER_PHRASES = {
    "and so on",
    "and so on etc",
    "and so forth",
    "etc",
    "etcetera",
    "so on",
}


def parse_prompt_for_questions(prompt: str) -> ParsedPrompt:
    cleaned_text = _normalize_whitespace(prompt)

    if not cleaned_text:
        return ParsedPrompt(
            original_text=prompt,
            cleaned_text="",
            is_multi_question=False,
            intro_text="",
            questions=[],
        )

    numbered_questions = _extract_numbered_questions(prompt)
    if len(numbered_questions) >= 2:
        return ParsedPrompt(
            original_text=prompt,
            cleaned_text=cleaned_text,
            is_multi_question=True,
            intro_text=_extract_intro_text(prompt),
            questions=numbered_questions,
        )

    bulleted_questions = _extract_bulleted_questions(prompt)
    if len(bulleted_questions) >= 2 and _MULTI_QUESTION_INTRO_RE.search(prompt):
        return ParsedPrompt(
            original_text=prompt,
            cleaned_text=cleaned_text,
            is_multi_question=True,
            intro_text=_extract_intro_text(prompt),
            questions=bulleted_questions,
        )

    return ParsedPrompt(
        original_text=prompt,
        cleaned_text=cleaned_text,
        is_multi_question=False,
        intro_text="",
        questions=[],
    )


def _extract_numbered_questions(prompt: str) -> List[ParsedQuestion]:
    line_based_questions = _extract_line_numbered_questions(prompt)
    if len(line_based_questions) >= 2:
        return line_based_questions

    inline_questions = _extract_inline_numbered_questions(prompt)
    if len(inline_questions) >= 2:
        return inline_questions

    return []


def _extract_line_numbered_questions(prompt: str) -> List[ParsedQuestion]:
    lines = _normalize_line_breaks(prompt).splitlines()

    questions: List[ParsedQuestion] = []
    current_number: int | None = None
    current_parts: List[str] = []

    for raw_line in lines:
        line = raw_line.rstrip()

        if not line.strip():
            if current_number is not None and current_parts:
                current_parts.append("")
            continue

        match = _LINE_NUMBERED_QUESTION_RE.match(line)
        if match:
            if current_number is not None:
                finalized_text = _finalize_question_text(current_parts)
                if finalized_text and not _is_placeholder_question_text(finalized_text):
                    questions.append(
                        ParsedQuestion(number=current_number, text=finalized_text)
                    )

            current_number = int(match.group("number"))
            first_text = match.group("text").strip()
            current_parts = [first_text] if first_text else []
            continue

        if current_number is not None:
            current_parts.append(line.strip())

    if current_number is not None:
        finalized_text = _finalize_question_text(current_parts)
        if finalized_text and not _is_placeholder_question_text(finalized_text):
            questions.append(
                ParsedQuestion(number=current_number, text=finalized_text)
            )

    return questions if len(questions) >= 2 else []


def _extract_inline_numbered_questions(prompt: str) -> List[ParsedQuestion]:
    normalized_prompt = _normalize_whitespace(prompt)
    matches = list(_INLINE_NUMBERED_QUESTION_RE.finditer(normalized_prompt))

    if len(matches) < 2:
        return []

    questions: List[ParsedQuestion] = []

    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized_prompt)

        question_text = _normalize_whitespace(normalized_prompt[start:end])
        if not question_text or _is_placeholder_question_text(question_text):
            continue

        questions.append(
            ParsedQuestion(
                number=int(match.group("number")),
                text=question_text,
            )
        )

    return questions if len(questions) >= 2 else []


def _extract_bulleted_questions(prompt: str) -> List[ParsedQuestion]:
    lines = _normalize_line_breaks(prompt).splitlines()

    questions: List[ParsedQuestion] = []
    current_number: int | None = None
    current_parts: List[str] = []

    for raw_line in lines:
        line = raw_line.rstrip()

        if not line.strip():
            if current_number is not None and current_parts:
                current_parts.append("")
            continue

        match = _BULLET_QUESTION_RE.match(line)
        if match:
            if current_number is not None:
                finalized_text = _finalize_question_text(current_parts)
                if finalized_text and not _is_placeholder_question_text(finalized_text):
                    questions.append(
                        ParsedQuestion(number=current_number, text=finalized_text)
                    )

            current_number = len(questions) + 1
            first_text = match.group(1).strip()
            current_parts = [first_text] if first_text else []
            continue

        if current_number is not None:
            current_parts.append(line.strip())

    if current_number is not None:
        finalized_text = _finalize_question_text(current_parts)
        if finalized_text and not _is_placeholder_question_text(finalized_text):
            questions.append(
                ParsedQuestion(number=current_number, text=finalized_text)
            )

    return questions if len(questions) >= 2 else []


def _extract_intro_text(prompt: str) -> str:
    normalized_prompt = _normalize_line_breaks(prompt)

    line_match = re.search(_LINE_NUMBERED_QUESTION_RE, normalized_prompt)
    if line_match:
        return _normalize_whitespace(normalized_prompt[: line_match.start()])

    inline_prompt = _normalize_whitespace(prompt)
    inline_match = _INLINE_NUMBERED_QUESTION_RE.search(inline_prompt)
    if inline_match:
        return _normalize_whitespace(inline_prompt[: inline_match.start()])

    intro_lines: List[str] = []

    for raw_line in normalized_prompt.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if _BULLET_QUESTION_RE.match(line):
            break

        intro_lines.append(line)

    return _normalize_whitespace(" ".join(intro_lines))


def _finalize_question_text(parts: List[str]) -> str:
    merged = " ".join(part.strip() for part in parts if part.strip())
    return _normalize_whitespace(merged)


def _is_placeholder_question_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True

    lowered = stripped.lower()
    normalized = re.sub(r"[.\-_–—]+", " ", lowered)
    normalized = _normalize_whitespace(normalized)

    if not normalized:
        return True

    if normalized in _PLACEHOLDER_PHRASES:
        return True

    if normalized.startswith("and so on"):
        return True

    if normalized.startswith("etc"):
        return True

    return False


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalize_line_breaks(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")