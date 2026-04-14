"""
Chat route — POST /chat, POST /chat/stream

Accepts a user message and optional conversation history, runs RAG over
past journal entries, and returns the answer plus source references.
The /stream variant uses SSE for real-time token delivery.
"""
import json
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()


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
async def chat_endpoint(req: ChatRequest):
    """
    Answer a question about past journal entries using RAG.

    - Retrieves the top-k most relevant entries via pgvector
    - Feeds them as context to GPT-4o along with conversation history
    - Returns the answer and the source entries used
    """
    from app.agents.chat_agent import chat

    history = [{"role": m.role, "content": m.content} for m in req.history]
    result = await chat(message=req.message, history=history, top_k=req.top_k)
    return result


@router.post("/stream", summary="Streaming chat via SSE")
async def chat_stream_endpoint(req: ChatRequest):
    """
    Streaming variant of /chat. Returns an SSE stream of token events.

    Each event is a JSON object:
      - During generation: {"token": "...", "done": false}
      - Final event:       {"token": "", "done": true, "sources": [...]}
    """
    from app.agents.chat_agent import chat_stream

    history = [{"role": m.role, "content": m.content} for m in req.history]

    async def event_generator():
        try:
            async for token, sources in chat_stream(
                message=req.message, history=history, top_k=req.top_k
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
