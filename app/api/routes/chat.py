"""
Chat route — POST /chat, POST /chat/stream

Accepts a user message and optional conversation history, runs RAG over
past journal entries, and returns the answer plus source references.
The /stream variant uses SSE for real-time token delivery.
"""
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.llm.guardrails import detect_injection
from app.observability.metrics import record_latency

logger = logging.getLogger(__name__)

router = APIRouter()


async def _guard_chat_input(message: str, user_id: str) -> None:
    """Raise 400 if the message is a prompt-injection attempt."""
    verdict = await detect_injection(message)
    if verdict["blocked"]:
        logger.warning(
            f"[chat] injection blocked for user={user_id}: {verdict['reason']!r}"
        )
        raise HTTPException(
            status_code=400,
            detail={"error": "prompt_injection_blocked", "reason": verdict["reason"]},
        )


class ChatMessage(BaseModel):
    role: str          # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
    top_k: int = 5


class SourceEntry(BaseModel):
    entry_id: str
    entry_date: str
    summary: str
    score: float | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceEntry]


@router.post("", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest, user_id: str = Depends(get_current_user)):
    """
    Answer a question about past journal entries using RAG.

    - Retrieves the top-k most relevant entries via pgvector
    - Feeds them as context to GPT-4o along with conversation history
    - Returns the answer and the source entries used
    """
    from app.agents.chat_agent import chat

    await _guard_chat_input(req.message, user_id)

    history = [{"role": m.role, "content": m.content} for m in req.history]
    started = time.perf_counter()
    status = "ok"
    try:
        result = await chat(message=req.message, history=history, top_k=req.top_k, user_id=user_id)
    except Exception:
        status = "error"
        raise
    finally:
        await record_latency(
            "chat", int((time.perf_counter() - started) * 1000),
            user_id=user_id, status=status,
        )
    return result


@router.post("/stream", summary="Streaming chat via SSE")
async def chat_stream_endpoint(req: ChatRequest, user_id: str = Depends(get_current_user)):
    """
    Streaming variant of /chat. Returns an SSE stream of token events.

    Each event is a JSON object:
      - During generation: {"token": "...", "done": false}
      - Final event:       {"token": "", "done": true, "sources": [...]}
    """
    from app.agents.chat_agent import chat_stream

    await _guard_chat_input(req.message, user_id)

    history = [{"role": m.role, "content": m.content} for m in req.history]

    async def event_generator():
        try:
            async for token, sources in chat_stream(
                message=req.message, history=history, top_k=req.top_k, user_id=user_id
            ):
                if sources is not None:
                    data = json.dumps({"token": "", "done": True, "sources": sources})
                else:
                    data = json.dumps({"token": token, "done": False})
                yield f"data: {data}\n\n"
        except Exception as exc:
            data = json.dumps({"token": "", "done": True, "error": str(exc), "sources": []})
            yield f"data: {data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
