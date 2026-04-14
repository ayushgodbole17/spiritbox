"""
Chat route — POST /chat

Accepts a user message and optional conversation history, runs RAG over
past journal entries, and returns the answer plus source references.
"""
from typing import Any

from fastapi import APIRouter
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
