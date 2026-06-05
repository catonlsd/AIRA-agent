# File: backend/tests/test_prompt_parsing_placeholder_items.py

from app.prompt_parsing import parse_prompt_for_questions


def test_trailing_placeholder_item_is_ignored():
    prompt = """
    Answer the following questions:
    1. What is Python?
    2. What is LangGraph?
    3. What is ChromaDB?
    4....... and so on etc
    """

    parsed = parse_prompt_for_questions(prompt)

    assert parsed.is_multi_question is True
    assert len(parsed.questions) == 3
    assert parsed.questions[0].number == 1
    assert parsed.questions[0].text == "What is Python?"
    assert parsed.questions[1].number == 2
    assert parsed.questions[1].text == "What is LangGraph?"
    assert parsed.questions[2].number == 3
    assert parsed.questions[2].text == "What is ChromaDB?"


def test_placeholder_like_line_does_not_count_as_real_question():
    prompt = """
    Solve these:
    1. Explain Git.
    2. Explain Docker.
    3.......
    """

    parsed = parse_prompt_for_questions(prompt)

    assert parsed.is_multi_question is True
    assert len(parsed.questions) == 2
    assert parsed.questions[0].text == "Explain Git."
    assert parsed.questions[1].text == "Explain Docker."


def test_and_so_on_line_without_real_question_text_is_ignored():
    prompt = """
    Answer these:
    1. What is an API?
    2. What is JSON?
    3. and so on
    """

    parsed = parse_prompt_for_questions(prompt)

    assert parsed.is_multi_question is True
    assert len(parsed.questions) == 2
    assert parsed.questions[0].text == "What is an API?"
    assert parsed.questions[1].text == "What is JSON?"