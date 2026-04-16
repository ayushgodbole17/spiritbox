"""
RAG Chat Agent — answers questions about past journal entries.

Flow:
  1. Retrieve the top-k entries via hybrid search (semantic + keyword with RRF)
  2. Build a context block from those entries (summary + raw_text + date)
  3. Call GPT-4o with the context + conversation history + user question
  4. Return the answer and the source entries used

Uses the model router (TIER_2 — gpt-4o) since this is a reasoning task.
"""
from __future__ import annotations

import logging
from datetime import datetime

from langfuse import observe

from app.llm.router import chat_completion, chat_completion_stream, TIER_2

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are Spiritbox, a personal AI journal assistant. You have access to the user's \
past journal entries, which are provided below as context. Answer the user's question \
thoughtfully and specifically, drawing on the journal entries when relevant.

Guidelines:
- Be concise but warm.
- Reference specific details from the entries when they support your answer.
- If the entries don't contain enough information to answer, say so honestly.
- Never fabricate details that aren't in the entries.
- Format dates as natural language (e.g. "last Tuesday", "on March 12th").
- If asked about patterns or trends, synthesise across multiple entries.

Context (relevant journal entries):
{context}
"""


def _format_entry(entry: dict, index: int) -> str:
    date_raw = entry.get("entry_date", "")
    try:
        dt = datetime.fromisoformat(date_raw.rstrip("Z"))
        date_str = dt.strftime("%-d %b %Y")
    except Exception:
        date_str = date_raw or "unknown date"

    summary = entry.get("summary", "").strip()
    raw = entry.get("raw_text", "").strip()
    text = summary if summary else raw[:400]
    return f"[Entry {index + 1} — {date_str}]\n{text}"


def _build_context(entries: list[dict]) -> str:
    if not entries:
        return "No relevant journal entries found."
    return "\n\n".join(_format_entry(e, i) for i, e in enumerate(entries))


@observe()
async def chat(
    message: str,
    history: list[dict] | None = None,
    top_k: int = 5,
) -> dict:
    """
    Answer a question using RAG over past journal entries.

    Args:
        message: The user's question or message.
        history: Prior conversation turns as [{role, content}] dicts.
        top_k:   Number of entries to retrieve via pgvector.

    Returns:
        dict with keys:
          - answer: str
          - sources: list of entry dicts used as context
    """
    from app.memory.vector_store import hybrid_search

    # 1. Retrieve relevant entries
    try:
        sources = await hybrid_search(message, limit=top_k)
        if not sources:
            logger.info(f"[chat_agent] hybrid_search returned 0 matches for query={message!r}")
    except Exception as exc:
        logger.warning(f"[chat_agent] hybrid_search raised: {exc!r}. Proceeding without context.")
        sources = []

    # 2. Build messages
    context = _build_context(sources)
    system_content = SYSTEM_PROMPT.format(context=context)

    messages = [{"role": "system", "content": system_content}]

    # Append prior turns (cap at last 10 to keep context manageable)
    if history:
        messages.extend(history[-10:])

    messages.append({"role": "user", "content": message})

    # 3. Call LLM
    response, model_used = await chat_completion(
        tier=TIER_2,
        messages=messages,
        temperature=0.4,
    )
    answer = (response.choices[0].message.content or "").strip()
    logger.debug(f"[chat_agent] answered ({len(answer)} chars, {len(sources)} sources, model={model_used})")

    return {
        "answer": answer,
        "sources": [
            {
                "entry_id": s.get("entry_id", ""),
                "entry_date": s.get("entry_date", ""),
                "summary": s.get("summary", ""),
                "score": s.get("score"),
            }
            for s in sources
        ],
    }


@observe()
async def chat_stream(
    message: str,
    history: list[dict] | None = None,
    top_k: int = 5,
):
    """
    Streaming variant of chat(). Yields (token, sources_or_none) tuples.
    The final yield has token="" and includes the sources list.
    """
    from app.memory.vector_store import hybrid_search

    try:
        sources = await hybrid_search(message, limit=top_k)
        if not sources:
            logger.info(f"[chat_agent] hybrid_search returned 0 matches for query={message!r}")
    except Exception as exc:
        logger.warning(f"[chat_agent] hybrid_search raised: {exc!r}. Proceeding without context.")
        sources = []

    context = _build_context(sources)
    system_content = SYSTEM_PROMPT.format(context=context)
    messages = [{"role": "system", "content": system_content}]
    if history:
        messages.extend(history[-10:])
    messages.append({"role": "user", "content": message})

    source_list = [
        {
            "entry_id": s.get("entry_id", ""),
            "entry_date": s.get("entry_date", ""),
            "summary": s.get("summary", ""),
            "score": s.get("score"),
        }
        for s in sources
    ]

    token_iter, model_used = await chat_completion_stream(
        tier=TIER_2,
        messages=messages,
        temperature=0.4,
    )
    async for token in token_iter:
        yield token, None

    logger.debug(f"[chat_agent] stream complete ({len(source_list)} sources, model={model_used})")
    yield "", source_list
