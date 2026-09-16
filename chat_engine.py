from __future__ import annotations

import os
import re
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from context import TWIN_SYSTEM_PROMPT
from rag import RetrievedChunk, format_retrieved_context, retrieve
from tools import handle_tool_calls, tools

load_dotenv(override=True)

MODEL_NAME = os.getenv("MODEL_NAME", "gpt-5.4-mini")
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "700"))
OPENAI_TIMEOUT_SECONDS = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))
SYSTEM_MESSAGES = [{"role": "system", "content": TWIN_SYSTEM_PROMPT}]


@dataclass
class SourceCard:
    title: str
    meta: str
    kind: str
    excerpt: str
    supports: str
    link: str | None = None


@dataclass
class ChatResult:
    answer: str
    sources: list[SourceCard]
    grounded: bool
    suggestions: list[str]
    why: str


def retrieval_query(message: str, history: list[dict] | None = None) -> str:
    recent = []
    for item in clean_history(history or [])[-6:]:
        role = "User" if item["role"] == "user" else "Ask Anish"
        recent.append(f"{role}: {item['content']}")
    if not recent:
        return message
    return "\n".join(
        [
            "Use the recent conversation only to resolve references like 'that project' or 'the other one'.",
            *recent,
            f"Current question: {message}",
        ]
    )


def build_grounding_message(
    message: str,
    history: list[dict] | None = None,
) -> tuple[dict, list[RetrievedChunk]]:
    chunks = retrieve(retrieval_query(message, history))
    grounding = f"""
# Retrieved career evidence

{format_retrieved_context(chunks)}

# Grounding rules

Use the retrieved evidence above as the source of truth for professional facts.
Do not use general knowledge or guesses to fill gaps.
If the evidence does not answer the user's question at all, say that the information is not in the current career documents and use the unknown-question tool.
Do not use the unknown-question tool when retrieved evidence supports a useful full or partial answer.
Distinguish exact verified facts from supported interpretations. If no numerical metric is documented, do not invent one; describe the verified qualitative outcome instead.
When a follow-up refers to "that", "it", "the project", or similar wording, use the recent conversation only to understand the topic, then rely on retrieved evidence for factual claims.
Answer in first person as Ask Anish.
Keep the answer concise, warm, natural, and specific.
Do not include raw source paths, citation metadata, chunk ids, file names, relevance scores, or grounding footers in the written answer.
The interface will display sources separately.
""".strip()
    return {"role": "system", "content": grounding}, chunks


def clean_assistant_text(text: str | None) -> str:
    if not text:
        return "I got an empty response. Please try asking again."
    cleaned = re.sub(r"\n*_Grounded in:.*?_$", "", text, flags=re.DOTALL).strip()
    cleaned = re.sub(
        r"\n*\s*If (?:you want|you'd like|you would like),? I can also .*?[.!?]\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return cleaned.strip()


def answer_is_unavailable(answer: str) -> bool:
    return bool(
        re.search(
            r"\b(don't|do not|don’t|cannot|can't|can’t)\s+have\b.*\b(information|verified|current career documents|sources)\b",
            answer,
            re.IGNORECASE,
        )
        or re.search(r"\bnot in (?:my|the) current (?:career )?(?:documents|sources)\b", answer, re.IGNORECASE)
    )


def friendly_source_title(chunk: RetrievedChunk) -> str:
    source = chunk.source.replace("\\", "/")
    stem = Path(source).stem
    stem = re.sub(r"[_-]+", " ", stem).strip()
    stem = re.sub(r"\s+", " ", stem)

    lowered = source.lower()
    if chunk.source_type == "github" or lowered.startswith("github/"):
        if "profile" in lowered:
            return "GitHub - Profile"
        repo_name = stem.split("__")[-1] if "__" in stem else stem
        return f"GitHub - {repo_name.title()}"

    if "linkedin" in lowered:
        return "LinkedIn - Experience"

    if "breast" in lowered or "cancer" in lowered:
        return "Breast Cancer Classification Research"

    if "project" in lowered:
        return "Anish Kulkarni - Project Resume"

    if "business" in lowered or "buisness" in lowered or "ba_fin" in lowered:
        return "Anish Kulkarni - Business Analytics Resume"

    if "consultant" in lowered:
        return "Anish Kulkarni - Consulting Resume"

    if "resume" in lowered or "resumes" in lowered:
        return "Anish Kulkarni - Resume"

    if "summary" in lowered:
        return "Anish Kulkarni - Profile Summary"

    return stem.title() or "Verified source"


def source_meta(chunk: RetrievedChunk) -> str:
    pieces = []
    if chunk.page:
        pieces.append(f"Page {chunk.page}")
    if chunk.source_type == "github":
        pieces.append("Repository context")
    elif chunk.source_type == "pdf":
        pieces.append("Verified document")
    else:
        pieces.append("Profile context")
    return " · ".join(pieces)


def source_link(chunk: RetrievedChunk) -> str | None:
    if chunk.source_type != "github":
        return None
    match = re.search(r"https://github\.com/[^\s)]+", chunk.text)
    return match.group(0).rstrip(".,")


def excerpt(text: str, limit: int = 230) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[email redacted]", cleaned)
    cleaned = re.sub(r"(\+?\d[\d\s().-]{7,}\d)", "[phone redacted]", cleaned)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rsplit(" ", 1)[0] + "…"


def supported_claim(chunk: RetrievedChunk) -> str:
    title = friendly_source_title(chunk)
    lowered_title = title.lower()
    if "linkedin" in lowered_title:
        return "LinkedIn profile details, listed skills, and professional experience used in this answer."
    if "github" in lowered_title:
        return "GitHub project context, repository description, language, or README details."
    if "project resume" in lowered_title:
        return "Project scope, business context, technologies, or documented outcomes."
    if "business analytics" in lowered_title:
        return "Business analytics experience, skills, education, or project evidence."
    if "consulting" in lowered_title:
        return "Consulting-focused experience, responsibilities, or project evidence."
    if "resume" in lowered_title:
        return "Resume-backed education, skills, experience, and project evidence."
    if "profile summary" in lowered_title:
        return "Verified profile summary details about Anish’s background and strengths."

    text = chunk.text.lower()
    if "education" in text or "university" in text or "graduation" in text:
        return "Education, program details, or academic context used in this answer."
    if "experience" in text or "intern" in text or "analyst" in text:
        return "Professional experience, responsibilities, or role-specific work."
    if "project" in text or "platform" in text or "dashboard" in text:
        return "Project scope, technologies, or documented outcomes."
    if "research" in text or "resnet" in text or "vgg" in text or "densenet" in text:
        return "Research topic, methods, or model details."
    return f"Verified details from {title} used in this answer."


def source_cards(chunks: list[RetrievedChunk], limit: int = 5) -> list[SourceCard]:
    cards = []
    seen = set()
    for chunk in chunks:
        title = friendly_source_title(chunk)
        meta = source_meta(chunk)
        key = (title, meta)
        if key in seen:
            continue
        seen.add(key)
        cards.append(
            SourceCard(
                title=title,
                meta=meta,
                kind=chunk.source_type,
                excerpt=excerpt(chunk.text),
                supports=supported_claim(chunk),
                link=source_link(chunk),
            )
        )
        if len(cards) >= limit:
            break
    return cards


def clean_history(history: list[dict]) -> list[dict]:
    cleaned = []
    for item in history[-20:]:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            cleaned.append({"role": role, "content": content.strip()})
    return cleaned


def build_chat_messages(message: str, history: list[dict] | None = None) -> tuple[list[dict], list[RetrievedChunk]]:
    grounding_message, chunks = build_grounding_message(message, history)
    messages = (
        SYSTEM_MESSAGES
        + [grounding_message]
        + clean_history(history or [])
        + [{"role": "user", "content": message}]
    )
    return messages, chunks


def source_dicts(cards: list[SourceCard]) -> list[dict]:
    return [
        {
            "title": source.title,
            "meta": source.meta,
            "kind": source.kind,
            "excerpt": source.excerpt,
            "supports": source.supports,
            "link": source.link,
        }
        for source in cards
    ]


def follow_up_suggestions(question: str, answer: str, history: list[dict] | None = None) -> list[str]:
    used = {item.get("content", "").strip().lower() for item in clean_history(history or [])}
    used.add(question.strip().lower())
    lowered = f"{question} {answer}".lower()
    if answer_is_unavailable(answer):
        return [
            "Which related skills are documented?",
            "What evidence is available?",
            "Ask about Anish’s projects instead.",
        ]
    candidates: list[str]
    if any(word in lowered for word in ["project", "platform", "dashboard", "github", "repository"]):
        candidates = [
            "What was Anish’s contribution?",
            "Which technologies did he use?",
            "What was the outcome?",
            "Explain the architecture.",
        ]
    elif any(word in lowered for word in ["research", "model", "classification", "cancer"]):
        candidates = [
            "What models did Anish use?",
            "What was the research outcome?",
            "Explain it to a recruiter.",
        ]
    elif any(word in lowered for word in ["role", "fit", "skill", "technical", "data", "ai"]):
        candidates = [
            "Which skills are strongest?",
            "Give me the recruiter version.",
            "Which projects prove that?",
        ]
    else:
        candidates = [
            "Summarize it in two sentences.",
            "Give me a recruiter version.",
            "What evidence supports that?",
        ]

    return [item for item in candidates if item.lower() not in used][:3]


def why_this_answer(
    question: str,
    chunks: list[RetrievedChunk],
    history: list[dict] | None = None,
) -> str:
    if not chunks:
        return (
            "I did not find verified source evidence for this exact question, so the answer avoids "
            "claiming unsupported facts and redirects to what is available."
        )

    titles = []
    for chunk in chunks:
        title = friendly_source_title(chunk)
        if title not in titles:
            titles.append(title)
    context_used = bool(history) and bool(
        re.search(
            r"\b(that|it|this|those|the other|the project)\b",
            question,
            re.IGNORECASE,
        )
    )
    prefix = (
        "The recent conversation helped resolve the follow-up topic, and fresh verified sources were retrieved. "
        if context_used
        else "The answer was grounded by retrieving verified career sources for this question. "
    )
    return (
        f"{prefix}The main sources used were {', '.join(titles[:3])}. "
        "Exact facts are stated from the retrieved evidence; broader impact statements are treated as supported interpretations when no numerical metric is documented."
    )


def answer_question(message: str, history: list[dict] | None = None) -> ChatResult:
    if not os.getenv("OPENAI_API_KEY"):
        return ChatResult(
            answer=(
                "I need an OpenAI API key in the project `.env` file before I can answer "
                "from Anish’s verified career documents."
            ),
            sources=[],
            grounded=False,
            suggestions=[],
            why="The app cannot retrieve verified evidence until an OpenAI API key is configured.",
        )

    try:
        messages, chunks = build_chat_messages(message, history)
    except Exception:  # noqa: BLE001 - retrieval errors should stay visitor-safe.
        return ChatResult(
            answer=(
                "I’m having trouble reading the verified career sources right now. "
                "Please rebuild the index or try again in a moment."
            ),
            sources=[],
            grounded=False,
            suggestions=["How do I rebuild the source index?"],
            why="Retrieval failed before verified sources could be read.",
        )

    try:
        client = OpenAI(timeout=OPENAI_TIMEOUT_SECONDS)
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            tools=tools,
            max_completion_tokens=MAX_OUTPUT_TOKENS,
        )
        while response.choices[0].finish_reason == "tool_calls":
            assistant_message = response.choices[0].message
            messages.append(assistant_message)
            messages.extend(handle_tool_calls(assistant_message.tool_calls))
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                tools=tools,
                max_completion_tokens=MAX_OUTPUT_TOKENS,
            )
    except Exception:  # noqa: BLE001 - model/API errors should stay visitor-safe.
        return ChatResult(
            answer=(
                "I’m having trouble reaching the model right now. Please check the "
                "connection and try again in a moment."
            ),
            sources=[],
            grounded=False,
            suggestions=["Try again", "Ask a more specific question"],
            why="The model request failed after retrieval, so no new answer evidence could be completed.",
        )

    answer = clean_assistant_text(response.choices[0].message.content)
    unavailable = answer_is_unavailable(answer)
    cards = [] if unavailable else source_cards(chunks)
    return ChatResult(
        answer=answer,
        sources=cards,
        grounded=bool(cards),
        suggestions=follow_up_suggestions(message, answer, history),
        why=why_this_answer(message, [] if unavailable else chunks, history),
    )


def stream_answer_question(
    message: str,
    history: list[dict] | None = None,
) -> Generator[dict, None, None]:
    if not os.getenv("OPENAI_API_KEY"):
        yield {
            "type": "done",
            "answer": (
                "I need an OpenAI API key in the project `.env` file before I can answer "
                "from Anish’s verified career documents."
            ),
            "sources": [],
            "grounded": False,
        }
        return

    try:
        yield {"type": "status", "label": "Searching Anish’s verified sources…"}
        messages, chunks = build_chat_messages(message, history)
        cards = source_cards(chunks)
    except Exception:  # noqa: BLE001 - retrieval errors should stay visitor-safe.
        yield {
            "type": "done",
            "answer": (
                "I’m having trouble reading the verified career sources right now. "
                "Please rebuild the index or try again in a moment."
            ),
            "sources": [],
            "grounded": False,
            "suggestions": ["How do I rebuild the source index?"],
            "why": "Retrieval failed before verified sources could be read.",
        }
        return

    yield {"type": "status", "label": "Reviewing relevant information…"}
    yield {
        "type": "meta",
        "sources": source_dicts(cards),
        "grounded": bool(chunks),
    }

    try:
        client = OpenAI(timeout=OPENAI_TIMEOUT_SECONDS)
        final_answer = ""
        for _ in range(3):
            yield {"type": "status", "label": "Preparing a grounded answer…"}
            text_parts: list[str] = []
            tool_calls: dict[int, dict] = {}
            finish_reason = None
            stream = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                tools=tools,
                max_completion_tokens=MAX_OUTPUT_TOKENS,
                stream=True,
            )

            yielded_thinking = False
            for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                finish_reason = choice.finish_reason or finish_reason
                delta = choice.delta

                if delta.content:
                    if not yielded_thinking:
                        yield {"type": "status", "label": "Anish is thinking…"}
                        yielded_thinking = True
                    text_parts.append(delta.content)
                    yield {"type": "token", "content": delta.content}

                for tool_delta in delta.tool_calls or []:
                    call = tool_calls.setdefault(
                        tool_delta.index,
                        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                    )
                    if tool_delta.id:
                        call["id"] = tool_delta.id
                    if tool_delta.type:
                        call["type"] = tool_delta.type
                    if tool_delta.function:
                        if tool_delta.function.name:
                            call["function"]["name"] += tool_delta.function.name
                        if tool_delta.function.arguments:
                            call["function"]["arguments"] += tool_delta.function.arguments

            final_answer = clean_assistant_text("".join(text_parts))
            if finish_reason != "tool_calls":
                break

            ordered_calls = [tool_calls[index] for index in sorted(tool_calls)]
            messages.append(
                {
                    "role": "assistant",
                    "content": final_answer or None,
                    "tool_calls": ordered_calls,
                }
            )
            messages.extend(handle_tool_calls(ordered_calls))
        else:
            final_answer = (
                "I needed too many follow-up tool steps to answer cleanly. "
                "Please try a more specific version of the question."
            )
    except Exception:  # noqa: BLE001 - model/API errors should stay visitor-safe.
        yield {
            "type": "done",
            "answer": (
                "I’m having trouble reaching the model right now. Please check the "
                "connection and try again in a moment."
            ),
            "sources": [],
            "grounded": False,
            "suggestions": ["Try again", "Ask a more specific question"],
            "why": "The model request failed after retrieval, so no completed answer could be produced.",
        }
        return

    yield {
        "type": "done",
        "answer": final_answer,
        "sources": [] if answer_is_unavailable(final_answer) else source_dicts(cards),
        "grounded": bool(chunks) and not answer_is_unavailable(final_answer),
        "suggestions": follow_up_suggestions(message, final_answer, history),
        "why": why_this_answer(
            message,
            [] if answer_is_unavailable(final_answer) else chunks,
            history,
        ),
    }
