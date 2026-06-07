# File: backend/tests/test_turn_classifier.py

from app.turn_classifier import (
    CLARIFICATION_MODE,
    DOCUMENT_QA_MODE,
    EXECUTION_MODE,
    GENERAL_CHAT_MODE,
    RESEARCH_THEN_EXECUTION_MODE,
    SELF_MEMORY_MODE,
    WEB_RESEARCH_MODE,
    classify_turn,
)


def test_general_chat_greeting_is_classified_correctly():
    result = classify_turn("Hello, who are you?")

    assert result.mode == GENERAL_CHAT_MODE
    assert result.needs_research is False
    assert result.needs_execution is False
    assert result.needs_document_analysis is False
    assert result.needs_approval_review is False
    assert result.artifact_type is None


def test_self_memory_question_is_classified_correctly():
    result = classify_turn("Do you know me?")

    assert result.mode == SELF_MEMORY_MODE
    assert result.needs_research is False
    assert result.needs_execution is False
    assert result.needs_document_analysis is False
    assert result.needs_approval_review is False
    assert result.artifact_type is None


def test_document_qa_is_classified_when_files_are_uploaded():
    result = classify_turn(
        "Based on the document I uploaded, what is the main conclusion?",
        has_uploaded_files=True,
        uploaded_file_names=["report.pdf"],
    )

    assert result.mode == DOCUMENT_QA_MODE
    assert result.needs_research is False
    assert result.needs_execution is False
    assert result.needs_document_analysis is True
    assert result.needs_approval_review is False
    assert result.artifact_type is None


def test_document_qa_is_classified_from_uploaded_filename_reference():
    result = classify_turn(
        "What does annual_report.pdf say about revenue growth?",
        has_uploaded_files=True,
        uploaded_file_names=["annual_report.pdf"],
    )

    assert result.mode == DOCUMENT_QA_MODE
    assert result.needs_document_analysis is True


def test_execution_request_is_classified_correctly():
    result = classify_turn("Read file backend/main.py")

    assert result.mode == EXECUTION_MODE
    assert result.needs_research is False
    assert result.needs_execution is True
    assert result.needs_document_analysis is False
    assert result.artifact_type is None


def test_high_risk_execution_marks_approval_review():
    result = classify_turn("pip install requests")

    assert result.mode == EXECUTION_MODE
    assert result.needs_execution is True
    assert result.needs_approval_review is True


def test_web_research_request_is_classified_correctly():
    result = classify_turn("Research the latest AI trends in healthcare.")

    assert result.mode == WEB_RESEARCH_MODE
    assert result.needs_research is True
    assert result.needs_execution is False
    assert result.needs_document_analysis is False
    assert result.needs_approval_review is False
    assert result.artifact_type is None


def test_artifact_request_is_classified_as_research_then_execution():
    result = classify_turn("Make a PPT on renewable energy.")

    assert result.mode == RESEARCH_THEN_EXECUTION_MODE
    assert result.needs_research is True
    assert result.needs_execution is True
    assert result.needs_approval_review is True
    assert result.artifact_type == "pptx"


def test_docx_request_is_classified_as_research_then_execution():
    result = classify_turn("Write a report on climate change in docx format.")

    assert result.mode == RESEARCH_THEN_EXECUTION_MODE
    assert result.artifact_type == "docx"
    assert result.needs_research is True
    assert result.needs_execution is True


def test_xlsx_request_is_classified_as_research_then_execution():
    result = classify_turn("Create an excel spreadsheet for monthly sales analysis.")

    assert result.mode == RESEARCH_THEN_EXECUTION_MODE
    assert result.artifact_type == "xlsx"
    assert result.needs_research is True
    assert result.needs_execution is True


def test_summarize_existing_document_is_document_qa_not_artifact():
    # "document" is an artifact noun, but with no creation verb this is a
    # question about an existing file, not a request to generate a docx.
    result = classify_turn("summarize this document")
    assert result.mode == DOCUMENT_QA_MODE
    assert result.artifact_type is None


def test_question_about_a_report_is_not_an_artifact_request():
    assert classify_turn("what does the report say about revenue").artifact_type is None
    assert classify_turn("summarize the attached file").mode == DOCUMENT_QA_MODE


def test_artifact_still_detected_with_a_creation_verb():
    assert classify_turn("Make a PPT on renewable energy.").artifact_type == "pptx"
    assert classify_turn("Write a report on climate change in docx format.").artifact_type == "docx"
    assert classify_turn("Create an excel spreadsheet for monthly sales.").artifact_type == "xlsx"


def test_knowledge_questions_route_to_general_chat():
    # These are answered conversationally (token-streamed), not via the one-shot
    # web-research path.
    for query in [
        "Explain ChromaDB",
        "Tell me about vector databases",
        "what is a transformer model",
        "how does backpropagation work",
        "define gradient descent",
    ]:
        assert classify_turn(query).mode == GENERAL_CHAT_MODE


def test_research_and_execution_take_precedence_over_knowledge():
    assert classify_turn("compare ChromaDB and Pinecone").mode == WEB_RESEARCH_MODE
    assert classify_turn("what is the latest AI news").mode == WEB_RESEARCH_MODE
    assert classify_turn("run git status").mode == EXECUTION_MODE


def test_empty_prompt_becomes_clarification():
    result = classify_turn("   ")

    assert result.mode == CLARIFICATION_MODE
    assert result.needs_research is False
    assert result.needs_execution is False
    assert result.needs_document_analysis is False
    assert result.needs_approval_review is False
    assert result.artifact_type is None