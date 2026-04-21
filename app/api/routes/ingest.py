import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from app.agents.graph import run_entry_pipeline
from app.api.deps import get_current_user
from app.db.crud import create_ingest_job, get_ingest_job, update_ingest_job
from app.jobs.queue import enqueue
from app.llm.token_tracker import get_usage, reset_usage
from app.transcription.whisper import transcribe_bytes

logger = logging.getLogger(__name__)

router = APIRouter()

# Whisper's documented per-request limit is 25 MB; keep text well under any LLM context.
MAX_TEXT_BYTES = 32 * 1024           # 32 KB of prose
MAX_AUDIO_BYTES = 25 * 1024 * 1024   # 25 MB, matching Whisper API cap


class TextEntryRequest(BaseModel):
    text: str


class TokenUsageResponse(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    embedding_tokens: int = 0
    estimated_cost_usd: float = 0.0


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
    token_usage: TokenUsageResponse = TokenUsageResponse()


@router.post("/text", response_model=IngestResponse, summary="Ingest a text journal entry")
async def ingest_text(request: TextEntryRequest, user_id: str = Depends(get_current_user)) -> IngestResponse:
    """
    Accepts a raw text journal entry, runs it through the agent pipeline,
    persists to pgvector, and returns the structured output.
    """
    text_bytes = len(request.text.encode("utf-8"))
    if text_bytes > MAX_TEXT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Text entry too large: {text_bytes} bytes > {MAX_TEXT_BYTES} limit",
        )

    logger.info(f"Ingesting text entry for user={user_id}, length={len(request.text)}")
    reset_usage()

    try:
        result = await run_entry_pipeline(request.text, user_id=user_id)
    except Exception as e:
        logger.error(f"Pipeline error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {e}")

    usage = get_usage()
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
        token_usage=TokenUsageResponse(**usage.to_dict()),
    )


class IngestJobResponse(BaseModel):
    job_id: str
    status: str
    status_url: str


class JobStatusResponse(BaseModel):
    job_id: str
    kind: str
    status: str  # queued | running | completed | failed
    filename: str | None = None
    entry_id: str | None = None
    result: dict[str, Any] | None = None  # full pipeline result on completion
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


async def _run_audio_pipeline(
    job_id: str,
    user_id: str,
    data: bytes,
    filename: str | None,
    content_type: str | None,
) -> None:
    """Background worker: transcribe and ingest, updating ingest_jobs row."""
    try:
        reset_usage()
        await update_ingest_job(job_id, status="running")

        try:
            text = await transcribe_bytes(data, filename=filename, content_type=content_type)
        except Exception as exc:
            logger.error(f"[ingest-job {job_id}] transcription failed: {exc}", exc_info=True)
            await update_ingest_job(job_id, status="failed", error=f"transcription: {exc}")
            return

        try:
            result = await run_entry_pipeline(text, user_id=user_id)
        except Exception as exc:
            logger.error(f"[ingest-job {job_id}] pipeline failed: {exc}", exc_info=True)
            await update_ingest_job(job_id, status="failed", error=f"pipeline: {exc}")
            return

        usage = get_usage()
        full_result = {
            "entry_id":        result["entry_id"],
            "raw_text":        text,
            "summary":         result.get("summary", ""),
            "categories":      result.get("categories", []),
            "entities":        result.get("entities", {}),
            "events":          result.get("events", []),
            "model_used":      result.get("model_used", {}),
            "cache_hits":      result.get("cache_hits", {}),
            "prompt_versions": result.get("prompt_versions", {}),
            "token_usage":     usage.to_dict(),
        }
        await update_ingest_job(
            job_id,
            status="completed",
            entry_id=result["entry_id"],
            result_json=json.dumps(full_result, default=str),
        )
        logger.info(f"[ingest-job {job_id}] completed entry_id={result['entry_id']}")
    except Exception as exc:
        logger.error(f"[ingest-job {job_id}] unexpected: {exc}", exc_info=True)
        try:
            await update_ingest_job(job_id, status="failed", error=str(exc))
        except Exception:
            pass


@router.post(
    "/audio",
    response_model=IngestJobResponse,
    status_code=202,
    summary="Enqueue an audio journal entry (async)",
)
async def ingest_audio(
    file: UploadFile = File(..., description="Audio file (mp3, wav, m4a, etc.)"),
    user_id: str = Depends(get_current_user),
) -> IngestJobResponse:
    """
    Accepts an audio file, validates the size, and queues transcription +
    pipeline work in the background. Returns 202 with a job_id for polling
    `GET /ingest/jobs/{job_id}`.
    """
    logger.info(f"Queuing audio entry for user={user_id}, filename={file.filename}")

    if not file.content_type or not file.content_type.startswith("audio/"):
        logger.warning(f"Non-audio content type received: {file.content_type}")

    data = await file.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Audio file too large: > {MAX_AUDIO_BYTES} bytes",
        )
    if not data:
        raise HTTPException(status_code=400, detail="Empty audio upload")

    job_id = await create_ingest_job(user_id=user_id, kind="audio", filename=file.filename)
    content_type = file.content_type
    enqueue(
        lambda: _run_audio_pipeline(job_id, user_id, data, file.filename, content_type),
        name=f"ingest-audio:{job_id}",
    )
    return IngestJobResponse(
        job_id=job_id,
        status="queued",
        status_url=f"/ingest/jobs/{job_id}",
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Poll the status of an ingest job",
)
async def get_job_status(
    job_id: str,
    user_id: str = Depends(get_current_user),
) -> JobStatusResponse:
    job = await get_ingest_job(job_id, user_id=user_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    result_json = job.pop("result_json", None)
    result_obj = None
    if result_json:
        try:
            result_obj = json.loads(result_json)
        except Exception:
            result_obj = None
    return JobStatusResponse(result=result_obj, **job)
