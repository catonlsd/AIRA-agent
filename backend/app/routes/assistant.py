import re
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.answer_generation import AnswerGenerationAgent
from app.agents.citation_verification import CitationVerificationAgent
from app.agents.memory_agent import MemoryAgent
from app.agents.query_understanding import QueryUnderstandingAgent
from app.agents.retrieval_agent import RetrievalAgent
from app.agents.web_research_agent import WebResearchAgent
from app.db.database import get_db
from app.db.models import Document, DocumentChunk
from app.rag.schemas import RetrievedChunk

from app.routes.aira_x import serialize_state
from graph.aira_workflow import AiraXWorkflow
from memory.workflow_store import WorkflowStore


router = APIRouter(prefix="/assistant", tags=["AIRA-X Assistant"])


AssistantResponseType = Literal[
    "casual_chat",
    "capability_help",
    "general_answer",
    "document_research",
    "web_research",
    "execution_result",
    "approval_required",
    "workflow_followup",
    "multi_task",
    "clarification",
    "error",
]


class AssistantRunRequest(BaseModel):
    message: str
    use_web: bool = False


class AssistantRunResponse(BaseModel):
    response_type: AssistantResponseType
    answer: str
    citations: list[dict] = Field(default_factory=list)
    workflow: dict | None = None
    run_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def normalize_message_text(text: str) -> str:
    normalized = text.lower().strip()

    replacements = {
        "’": "'",
        "‘": "'",
        "“": '"',
        "”": '"',
        "?": "",
        "!": "",
        ".": "",
        ",": "",
        ":": "",
        ";": "",
    }

    for old, new in replacements.items():
        normalized = normalized.replace(old, new)

    return " ".join(normalized.split())


def matches_any(normalized: str, phrases: set[str]) -> bool:
    return normalized in phrases or any(
        normalized.startswith(f"{phrase} ") for phrase in phrases
    )


def get_direct_response(message: str) -> dict | None:
    normalized = normalize_message_text(message)

    greeting_messages = {
        "hi",
        "hii",
        "hello",
        "hey",
        "heyy",
        "yo",
        "namaste",
        "good morning",
        "good afternoon",
        "good evening",
    }

    wellbeing_messages = {
        "how are you",
        "how r u",
        "how are u",
        "how are you doing",
        "how is it going",
        "hows it going",
        "what's up",
        "whats up",
        "sup",
        "so how's life",
        "hows life",
    }

    activity_messages = {
        "what are you doing",
        "what r you doing",
        "what are u doing",
        "what do you do",
        "what are you working on",
        "what is your work",
    }

    thanks_messages = {
        "thanks",
        "thank you",
        "thank u",
        "ty",
        "okay thanks",
        "ok thanks",
        "great thanks",
    }

    goodbye_messages = {
        "bye",
        "goodbye",
        "see you",
        "see ya",
        "talk to you later",
    }

    capability_messages = {
        "help",
        "what can you do",
        "what can u do",
        "what can you help me with",
        "what can u help me with",
        "how can you help",
        "how can u help",
        "how can you assist me",
        "how can u assist me",
        "how can you assist",
        "how can you support me",
        "how can you be useful",
        "what can aira do",
        "what can aira-x do",
        "what can airax do",
        "who are you",
        "what is aira",
        "what is aira x",
        "what is aira-x",
        "tell me about aira",
        "tell me about yourself",
    }

    if matches_any(normalized, greeting_messages):
        return {
            "response_type": "casual_chat",
            "answer": (
                "Hey! I’m AIRA-X — your unified AI research and execution assistant. "
                "You can ask me general questions, analyze documents, run safe tasks, "
                "inspect Git state, execute Python snippets, and review previous workflow output."
            ),
        }

    if matches_any(normalized, wellbeing_messages):
        return {
            "response_type": "casual_chat",
            "answer": (
                "I’m doing great and ready to help. Ask me anything, upload a document, "
                "request research, or give me a task to execute."
            ),
        }

    if matches_any(normalized, activity_messages):
        return {
            "response_type": "casual_chat",
            "answer": (
                "I’m ready to help you think, research, code, summarize, inspect files, "
                "run workflows, validate results, and handle approval-gated actions safely."
            ),
        }

    if matches_any(normalized, thanks_messages):
        return {
            "response_type": "casual_chat",
            "answer": "You’re welcome. Send me the next question or task whenever you’re ready.",
        }

    if matches_any(normalized, goodbye_messages):
        return {
            "response_type": "casual_chat",
            "answer": "See you! I’ll be ready when you want to continue.",
        }

    if matches_any(normalized, capability_messages):
        return {
            "response_type": "capability_help",
            "answer": (
                "I can help across five main areas:\n\n"
                "1. General answers — explain concepts, help with coding, writing, planning, "
                "learning, and everyday questions.\n\n"
                "2. Research — analyze uploaded documents, summarize sources, retrieve relevant "
                "context, and provide citations when documents or web sources are used.\n\n"
                "3. Execution — run safe workflows such as Python snippets, shell commands, file "
                "operations, and Git inspection tasks.\n\n"
                "4. Safety and approvals — pause before risky actions such as Git commits, pushes, "
                "or environment-changing operations.\n\n"
                "5. Workflow memory — show previous code, outputs, commands, run details, and "
                "execution history when you ask follow-up questions."
            ),
        }

    return None


def classify_message(message: str, use_web: bool) -> str:
    normalized = normalize_message_text(message)

    if is_workflow_followup(normalized):
        return "workflow_followup"

    if is_execution_request(normalized):
        return "execution_workflow"

    if is_document_request(normalized):
        return "document_research"

    if use_web or is_web_request(normalized):
        return "web_research"

    return "general_answer"


def is_workflow_followup(normalized: str) -> bool:
    direct_patterns = [
        "show me the details of the previous code",
        "show previous code",
        "show last code",
        "what did you just run",
        "what did you run",
        "show previous output",
        "show last output",
        "details of previous workflow",
        "details of last workflow",
        "show last run",
        "show previous run",
    ]

    if any(pattern in normalized for pattern in direct_patterns):
        return True

    previous_terms = {
        "previous",
        "last",
        "earlier",
        "just",
        "recent",
        "latest",
    }

    workflow_terms = {
        "code",
        "command",
        "output",
        "result",
        "workflow",
        "run",
        "execution",
        "task",
        "details",
    }

    has_previous = any(term in normalized for term in previous_terms)
    has_workflow = any(term in normalized for term in workflow_terms)

    return has_previous and has_workflow


def is_execution_request(normalized: str) -> bool:
    execution_phrases = [
        "run python",
        "python code",
        "execute python",
        "run code",
        "run command",
        "execute command",
        "shell command",
        "terminal command",
        "create file",
        "write file",
        "make file",
        "save file",
        "read file",
        "open file",
        "show file",
        "display file",
        "list files",
        "show files",
        "list directory",
        "show directory",
        "git status",
        "git branch",
        "git remote",
        "git log",
        "recent commits",
        "last commit",
        "git diff",
        "show changes",
        "full diff",
        "git add",
        "stage changes",
        "git commit",
        "commit changes",
        "commit all changes",
        "git push",
        "push to",
        "install package",
        "pip install",
        "test retry",
        "retry demo",
    ]

    if normalized.strip() in {"dir", "ls", "push"}:
        return True

    return any(phrase in normalized for phrase in execution_phrases)


def is_document_request(normalized: str) -> bool:
    document_phrases = [
        "uploaded document",
        "uploaded file",
        "my document",
        "my file",
        "the document",
        "this document",
        "the pdf",
        "this pdf",
        "summarize document",
        "summarize the document",
        "summarize my document",
        "summarize uploaded",
        "according to the document",
        "based on the document",
        "from the document",
        "from my file",
        "in the pdf",
        "knowledge base",
        "source",
        "sources",
        "citations",
    ]

    return any(phrase in normalized for phrase in document_phrases)


def is_web_request(normalized: str) -> bool:
    web_phrases = [
        "latest",
        "current",
        "today",
        "recent news",
        "news",
        "search web",
        "search the web",
        "browse",
        "look up",
        "online",
        "internet",
        "2026",
    ]

    return any(phrase in normalized for phrase in web_phrases)


def is_vague_document_followup(question: str) -> bool:
    lower = question.lower().strip()

    followup_phrases = [
        "what is this document about",
        "what is the document about",
        "summarize this document",
        "summarize the document",
        "summarize it",
        "summary",
        "list the key points",
        "key points",
        "main points",
        "important points",
        "what are the key points",
        "explain this",
        "explain it",
        "tell me more",
        "give me the overview",
        "overview",
    ]

    return any(phrase in lower for phrase in followup_phrases)


def latest_document_chunks(db: Session, limit: int = 12) -> list[RetrievedChunk]:
    document = db.query(Document).order_by(Document.created_at.desc()).first()

    if not document:
        return []

    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document.id)
        .order_by(DocumentChunk.chunk_index.asc())
        .limit(limit)
        .all()
    )

    return [
        RetrievedChunk(
            document_id=document.id,
            document_name=document.original_filename,
            chunk_id=chunk.id,
            chunk_index=chunk.chunk_index,
            page=chunk.page,
            text=chunk.text,
        )
        for chunk in chunks
    ]


def build_contextual_query(question: str, history: list[dict]) -> str:
    if not history:
        return question

    recent_context = " ".join(
        item.get("content", "")
        for item in history[-4:]
        if isinstance(item, dict)
    )

    if not recent_context.strip():
        return question

    return f"{question}\n\nRecent conversation context:\n{recent_context}"


def latest_workflow_state():
    runs = WorkflowStore.list_runs()

    if not runs:
        return None

    sorted_runs = sorted(
        runs,
        key=lambda item: (
            item.get("updated_at")
            or item.get("completed_at")
            or item.get("created_at")
            or ""
        ),
        reverse=True,
    )

    for run_summary in sorted_runs:
        run_id = run_summary.get("run_id")

        if not run_id:
            continue

        state = WorkflowStore.get(run_id)

        if state:
            return state

    return None


def build_workflow_followup_answer(message: str) -> AssistantRunResponse:
    state = latest_workflow_state()

    if not state:
        return AssistantRunResponse(
            response_type="workflow_followup",
            answer=(
                "I could not find a previous workflow run yet. Run a task first, "
                "then ask me to show the previous code, output, command, or details."
            ),
            metadata={"route": "workflow_followup", "found_previous_run": False},
        )

    latest_output = None

    for output in reversed(state.execution_outputs):
        if output.get("tool_result"):
            latest_output = output
            break

    if not latest_output:
        return AssistantRunResponse(
            response_type="workflow_followup",
            answer=(
                "I found the previous workflow, but it does not contain a recorded "
                "tool execution output."
            ),
            workflow=serialize_state(state),
            run_id=state.run_id,
            metadata={"route": "workflow_followup", "found_previous_run": True},
        )

    tool_name = latest_output.get("tool_used") or "tool"
    tool_action = latest_output.get("tool_action") or "action"
    tool_result = latest_output.get("tool_result", {})

    code = tool_result.get("code")
    command = tool_result.get("command")
    path = tool_result.get("path")
    output_text = tool_result.get("output") or tool_result.get("stdout") or ""
    stderr = tool_result.get("stderr") or ""
    return_code = tool_result.get("return_code")
    success = tool_result.get("success")

    answer_lines = [
        "Here are the details of the previous workflow run.",
        "",
        f"Tool used: {tool_name}:{tool_action}",
    ]

    if code:
        answer_lines.extend(["", "Code:", str(code).strip()])

    if command:
        answer_lines.extend(["", "Command:", str(command).strip()])

    if path:
        answer_lines.extend(["", "Path:", str(path).strip()])

    if output_text:
        if isinstance(output_text, list):
            output_text = "\n".join(str(item) for item in output_text)

        answer_lines.extend(["", "Output:", str(output_text).strip()])

    if stderr and not output_text:
        answer_lines.extend(["", "Error output:", str(stderr).strip()])

    answer_lines.extend(
        [
            "",
            "Execution status:",
            f"- Success: {'yes' if success else 'no'}",
        ]
    )

    if return_code is not None:
        answer_lines.append(f"- Return code: {return_code}")

    answer_lines.append(f"- Run ID: {state.run_id}")

    if state.final_answer:
        answer_lines.extend(["", "Previous final answer:", state.final_answer])

    return AssistantRunResponse(
        response_type="workflow_followup",
        answer="\n".join(answer_lines).strip(),
        workflow=serialize_state(state),
        run_id=state.run_id,
        metadata={
            "route": "workflow_followup",
            "found_previous_run": True,
            "tool_name": tool_name,
            "tool_action": tool_action,
        },
    )




def is_multi_task_request(message: str) -> bool:
    normalized = normalize_message_text(message)

    if "one by one" in normalized or "following tasks" in normalized:
        return len(split_multi_task_message(message)) >= 2

    return len(split_multi_task_message(message)) >= 3


def split_multi_task_message(message: str) -> list[str]:
    cleaned = message.strip()
    matches = list(re.finditer(r"(?:^|\s)(\d+)[\.)]\s*", cleaned))

    if len(matches) < 2:
        return []

    tasks: list[str] = []

    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
        task = cleaned[start:end].strip(" \n\t-:;")

        if task:
            tasks.append(task)

    return tasks


def short_task_title(task: str, max_length: int = 90) -> str:
    compact = " ".join(task.strip().split())

    if len(compact) <= max_length:
        return compact

    return compact[: max_length - 3].rstrip() + "..."


def format_subtask_answer(answer: str, max_length: int = 2200) -> str:
    cleaned = str(answer or "").strip()

    if not cleaned:
        return "No answer was produced."

    if len(cleaned) <= max_length:
        return cleaned

    return cleaned[: max_length - 3].rstrip() + "..."


async def handle_single_assistant_task(
    message: str,
    *,
    use_web: bool,
    db: Session,
    store_turn: bool = True,
) -> AssistantRunResponse:
    direct_response = get_direct_response(message)

    if direct_response:
        response = AssistantRunResponse(
            response_type=direct_response["response_type"],
            answer=direct_response["answer"],
            metadata={"route": direct_response["response_type"]},
        )

        if store_turn:
            store_assistant_turn(db, message, response.answer, [])

        return response

    route = classify_message(message, use_web)

    if route == "workflow_followup":
        response = build_workflow_followup_answer(message)

        if store_turn:
            store_assistant_turn(db, message, response.answer, [])

        return response

    if route == "execution_workflow":
        run_id = str(uuid4())

        workflow = AiraXWorkflow()
        state = await workflow.run(message, run_id=run_id)

        WorkflowStore.save(state)

        serialized = serialize_state(state)
        response_type: AssistantResponseType = (
            "approval_required"
            if state.status == "requires_approval"
            else "execution_result"
        )

        answer = (
            state.final_answer
            or "AIRA-X created a workflow, but no final answer was produced."
        )

        if store_turn:
            store_assistant_turn(db, message, answer, [])

        return AssistantRunResponse(
            response_type=response_type,
            answer=answer,
            workflow=serialized,
            run_id=state.run_id,
            metadata={
                "route": route,
                "status": state.status,
                "decision": state.decision,
            },
        )

    memory_agent = MemoryAgent()
    history, preferences = memory_agent.context(db)

    planner = QueryUnderstandingAgent()
    plan = planner.plan(message)

    if route == "document_research":
        plan.needs_documents = True
        plan.needs_web = False

    elif route == "web_research":
        plan.needs_web = True
        plan.needs_documents = False

    else:
        plan.needs_documents = False
        plan.needs_web = False

    if plan.needs_documents:
        if is_vague_document_followup(message):
            doc_chunks = latest_document_chunks(db, limit=12)
        else:
            contextual_query = build_contextual_query(plan.rewritten_query, history)
            doc_chunks = RetrievalAgent().retrieve(contextual_query)
    else:
        doc_chunks = []

    web_results = (
        WebResearchAgent().search(plan.rewritten_query)
        if plan.needs_web
        else []
    )

    answer = AnswerGenerationAgent().answer(
        message,
        doc_chunks,
        web_results,
        history,
        preferences,
    )

    answer = CitationVerificationAgent().verify(answer)
    citations = [citation.model_dump() for citation in answer.citations]

    if store_turn:
        store_assistant_turn(db, message, answer.answer, citations)

    response_type: AssistantResponseType = (
        "document_research"
        if doc_chunks
        else "web_research"
        if web_results
        else "general_answer"
    )

    return AssistantRunResponse(
        response_type=response_type,
        answer=answer.answer,
        citations=citations,
        metadata={
            "route": route,
            "plan": plan.model_dump(),
            "web_enabled": plan.needs_web,
            "web_results_count": len(web_results),
            "document_chunks_count": len(doc_chunks),
        },
    )


async def handle_multi_task_request(
    message: str,
    *,
    use_web: bool,
    db: Session,
) -> AssistantRunResponse:
    tasks = split_multi_task_message(message)

    if len(tasks) < 2:
        return await handle_single_assistant_task(
            message,
            use_web=use_web,
            db=db,
            store_turn=True,
        )

    sections: list[str] = [
        f"I ran the request as {len(tasks)} separate tasks, one by one.",
    ]
    workflow: dict | None = None
    run_id: str | None = None
    response_types: list[str] = []
    failed_tasks: list[int] = []

    for index, task in enumerate(tasks, start=1):
        try:
            response = await handle_single_assistant_task(
                task,
                use_web=use_web,
                db=db,
                store_turn=False,
            )

            response_types.append(response.response_type)

            if response.workflow:
                workflow = response.workflow

            if response.run_id:
                run_id = response.run_id

            sections.extend(
                [
                    "",
                    f"Task {index}: {short_task_title(task)}",
                    "",
                    format_subtask_answer(response.answer),
                ]
            )

        except Exception as error:
            failed_tasks.append(index)
            sections.extend(
                [
                    "",
                    f"Task {index}: {short_task_title(task)}",
                    "",
                    f"This task failed: {error}",
                ]
            )

    if failed_tasks:
        sections.extend(
            [
                "",
                "Summary:",
                f"- Completed: {len(tasks) - len(failed_tasks)}",
                f"- Failed: {len(failed_tasks)}",
            ]
        )
    else:
        sections.extend(
            [
                "",
                "Summary:",
                f"- Completed all {len(tasks)} tasks successfully.",
            ]
        )

    final_answer = "\n".join(sections).strip()
    store_assistant_turn(db, message, final_answer, [])

    return AssistantRunResponse(
        response_type="multi_task",
        answer=final_answer,
        workflow=workflow,
        run_id=run_id,
        metadata={
            "route": "multi_task",
            "task_count": len(tasks),
            "failed_tasks": failed_tasks,
            "response_types": response_types,
        },
    )


def store_assistant_turn(
    db: Session,
    message: str,
    answer: str,
    citations: list[dict] | None = None,
) -> None:
    MemoryAgent().store_turn(db, message, answer, citations or [])


def build_direct_run_response(
    message: str,
    response_type: AssistantResponseType,
    answer: str,
    db: Session,
) -> AssistantRunResponse:
    store_assistant_turn(db, message, answer, [])

    return AssistantRunResponse(
        response_type=response_type,
        answer=answer,
        metadata={"route": response_type},
    )


@router.post("/run", response_model=AssistantRunResponse)
async def run_assistant(
    payload: AssistantRunRequest,
    db: Session = Depends(get_db),
) -> AssistantRunResponse:
    message = payload.message.strip()

    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    if is_multi_task_request(message):
        return await handle_multi_task_request(
            message,
            use_web=payload.use_web,
            db=db,
        )

    return await handle_single_assistant_task(
        message,
        use_web=payload.use_web,
        db=db,
        store_turn=True,
    )
