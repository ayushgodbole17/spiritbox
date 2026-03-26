import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from app.agents.graph import run_entry_pipeline
from app.api.deps import get_current_user
from app.transcription.whisper import transcribe

logger = logging.getLogger(__name__)

router = APIRouter()


class TextEntryRequest(BaseModel):
    text: str


class IngestResponse(BaseModel):
    entry_id: str
    raw_text: str
    summary: str
    categories: list[dict[str, Any]]  # [{sentence, categories}, ...]
    entities: dict[str, Any]
    events: list[dict[str, Any]]
    model_used: dict[str, Any] = {}
    cache_hits: dict[str, Any] = {}
    prompt_versions: dict[str, Any] = {}


@router.post("/text", response_model=IngestResponse, summary="Ingest a text journal entry")
async def ingest_text(request: TextEntryRequest, user_id: str = Depends(get_current_user)) -> IngestResponse:
    """
    Accepts a raw text journal entry, runs it through the agent pipeline,
    persists to Weaviate, and returns the structured output.
    """
    logger.info(f"Ingesting text entry for user={user_id}, length={len(request.text)}")

    try:
        result = await run_entry_pipeline(request.text, user_id=user_id)
    except Exception as e:
        logger.error(f"Pipeline error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {e}")

    return IngestResponse(
        entry_id=result["entry_id"],
        raw_text=request.text,
        summary=result.get("summary", ""),
        categories=result.get("categories", []),
        entities=result.get("entities", {}),
        events=result.get("events", []),
        model_used=result.get("model_used", {}),
        cache_hits=result.get("cache_hits", {}),
        prompt_versions=result.get("prompt_versions", {}),
    )


@router.post("/audio", response_model=IngestResponse, summary="Ingest an audio journal entry")
async def ingest_audio(
    file: UploadFile = File(..., description="Audio file (mp3, wav, m4a, etc.)"),
    user_id: str = Depends(get_current_user),
) -> IngestResponse:
    """
    Accepts an audio file, transcribes it with Whisper, then runs the same
    text pipeline as /ingest/text.
    """
    logger.info(f"Ingesting audio entry for user={user_id}, filename={file.filename}")

    if not file.content_type or not file.content_type.startswith("audio/"):
        # Be lenient — Whisper handles many formats; just warn
        logger.warning(f"Non-audio content type received: {file.content_type}")

    try:
        text = await transcribe(file)
    except Exception as e:
        logger.error(f"Transcription failed: {e}", exc_info=True)
        raise HTTPException(status_code=422, detail=f"Transcription failed: {e}")

    logger.info(f"Transcription result ({len(text)} chars): {text[:120]}...")

    # Delegate to the same text pipeline
    try:
        result = await run_entry_pipeline(text, user_id=user_id)
    except Exception as e:
        logger.error(f"Pipeline error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {e}")

    return IngestResponse(
        entry_id=result["entry_id"],
        raw_text=text,
        summary=result.get("summary", ""),
        categories=result.get("categories", []),
        entities=result.get("entities", {}),
        events=result.get("events", []),
        model_used=result.get("model_used", {}),
        cache_hits=result.get("cache_hits", {}),
        prompt_versions=result.get("prompt_versions", {}),
    )
