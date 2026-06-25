from app.prompt_parsing import parse_prompt_for_questions


def test_single_prompt_is_not_marked_as_multi_question():
    prompt = "Explain what LangGraph is and why it is useful."

    parsed = parse_prompt_for_questions(prompt)

    assert parsed.is_multi_question is False
    assert parsed.questions == []
    assert parsed.cleaned_text == "Explain what LangGraph is and why it is useful."


def test_numbered_questions_are_extracted_correctly():
    prompt = """
    Answer the following questions:
    1. What is Python?
    2. What is LangGraph?
    3. What is ChromaDB?
    """

    parsed = parse_prompt_for_questions(prompt)

    assert parsed.is_multi_question is True
    assert parsed.intro_text == "Answer the following questions:"
    assert len(parsed.questions) == 3
    assert parsed.questions[0].number == 1
    assert parsed.questions[0].text == "What is Python?"
    assert parsed.questions[1].number == 2
    assert parsed.questions[1].text == "What is LangGraph?"
    assert parsed.questions[2].number == 3
    assert parsed.questions[2].text == "What is ChromaDB?"


def test_question_prefix_format_is_extracted_correctly():
    prompt = """
    Solve these:
    Q1: What is an API?
    Q2: What is JSON?
    """

    parsed = parse_prompt_for_questions(prompt)

    assert parsed.is_multi_question is True
    assert len(parsed.questions) == 2
    assert parsed.questions[0].text == "What is an API?"
    assert parsed.questions[1].text == "What is JSON?"


def test_bulleted_questions_work_when_intro_is_present():
    prompt = """
    Please answer these questions:
    - What is retrieval augmented generation?
    - What is vector search?
    """

    parsed = parse_prompt_for_questions(prompt)

    assert parsed.is_multi_question is True
    assert len(parsed.questions) == 2
    assert parsed.questions[0].number == 1
    assert parsed.questions[0].text == "What is retrieval augmented generation?"
    assert parsed.questions[1].number == 2
    assert parsed.questions[1].text == "What is vector search?"


def test_multiline_question_blocks_are_merged_cleanly():
    prompt = """
    Answer the following questions:
    1. Explain LangGraph
       in simple words.
    2. Explain ChromaDB
       with one example.
    """

    parsed = parse_prompt_for_questions(prompt)

    assert parsed.is_multi_question is True
    assert len(parsed.questions) == 2
    assert parsed.questions[0].text == "Explain LangGraph in simple words."
    assert parsed.questions[1].text == "Explain ChromaDB with one example."