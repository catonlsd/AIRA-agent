# File: backend/tests/test_prompt_parsing_edge_cases.py

from app.prompt_parsing import parse_prompt_for_questions


def test_inline_numbered_questions_on_single_line_are_detected():
    prompt = (
        "Answer the following questions: "
        "1. What is Python? "
        "2. What is LangGraph? "
        "3. What is ChromaDB?"
    )

    parsed = parse_prompt_for_questions(prompt)

    assert parsed.is_multi_question is True
    assert len(parsed.questions) == 3
    assert parsed.questions[0].number == 1
    assert parsed.questions[0].text == "What is Python?"
    assert parsed.questions[1].number == 2
    assert parsed.questions[1].text == "What is LangGraph?"
    assert parsed.questions[2].number == 3
    assert parsed.questions[2].text == "What is ChromaDB?"


def test_question_number_style_is_detected():
    prompt = """
    Answer the following:
    Question 1: What is an API?
    Question 2: What is JSON?
    Question 3: What is REST?
    """

    parsed = parse_prompt_for_questions(prompt)

    assert parsed.is_multi_question is True
    assert len(parsed.questions) == 3
    assert parsed.questions[0].text == "What is an API?"
    assert parsed.questions[1].text == "What is JSON?"
    assert parsed.questions[2].text == "What is REST?"


def test_q_no_style_is_detected():
    prompt = """
    Answer these:
    Q. No. 1: What is a vector database?
    Q. No. 2: What is retrieval augmented generation?
    """

    parsed = parse_prompt_for_questions(prompt)

    assert parsed.is_multi_question is True
    assert len(parsed.questions) == 2
    assert parsed.questions[0].number == 1
    assert parsed.questions[0].text == "What is a vector database?"
    assert parsed.questions[1].number == 2
    assert parsed.questions[1].text == "What is retrieval augmented generation?"


def test_mixed_spacing_and_parenthesis_numbering_are_detected():
    prompt = """
    Solve these questions:
    1) What is Git?
    2 ) What is Docker?
    3 : What is Kubernetes?
    """

    parsed = parse_prompt_for_questions(prompt)

    assert parsed.is_multi_question is True
    assert len(parsed.questions) == 3
    assert parsed.questions[0].text == "What is Git?"
    assert parsed.questions[1].text == "What is Docker?"
    assert parsed.questions[2].text == "What is Kubernetes?"