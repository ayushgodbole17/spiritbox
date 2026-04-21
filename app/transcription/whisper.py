"""
OpenAI Whisper transcription wrapper.

Uses the whisper-1 model via the OpenAI API to transcribe audio files
uploaded through the FastAPI UploadFile interface.

Supported formats: mp3, wav, m4a, webm (including webm/opus from browsers), ogg.
"""
import logging
import tempfile
import os
from pathlib import Path

from fastapi import UploadFile
from openai import AsyncOpenAI

from app.config import settings
from app.llm.resilience import openai_retry, whisper_breaker

logger = logging.getLogger(__name__)

_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


@openai_retry(max_attempts=3)
async def _whisper_create(audio_file) -> str:
    """Whisper transcription wrapped in retry + breaker guards."""
    return await whisper_breaker.call(
        _client.audio.transcriptions.create,
        model="whisper-1",
        file=audio_file,
        response_format="text",
    )

# Audio MIME types accepted by Whisper (informational — OpenAI detects format automatically)
SUPPORTED_AUDIO_TYPES = {
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
    "audio/mp4", "audio/m4a", "audio/ogg", "audio/webm",
    "audio/flac", "audio/x-flac",
}

# Map of MIME type prefixes/exact values → file extension for temp file naming.
# Whisper uses the file extension to detect the codec, so this must be accurate.
_MIME_TO_EXT: dict[str, str] = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mp4": ".mp4",
    "audio/m4a": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/ogg": ".ogg",
    # webm (including "audio/webm;codecs=opus" from Chrome/Firefox MediaRecorder)
    "audio/webm": ".webm",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
}


def _resolve_extension(file: UploadFile) -> str:
    """
    Determine the best file extension for the uploaded audio.

    Resolution order:
      1. Original filename extension (if present and non-empty).
      2. content_type → extension mapping (strips codec parameters first).
      3. Fallback to .webm (most common browser recording format).
    """
    # 1. Use filename if it has a meaningful extension
    if file.filename:
        suffix = Path(file.filename).suffix.lower()
        if suffix and suffix != ".":
            return suffix

    # 2. Derive from content_type, stripping codec parameters
    #    e.g. "audio/webm;codecs=opus" → "audio/webm"
    content_type = (file.content_type or "").lower().split(";")[0].strip()
    if content_type in _MIME_TO_EXT:
        return _MIME_TO_EXT[content_type]

    # 3. Try prefix match (e.g. "audio/webm" with extra parameters)
    for mime_prefix, ext in _MIME_TO_EXT.items():
        if content_type.startswith(mime_prefix):
            return ext

    # 4. Default — webm is the most common browser recording format
    logger.warning(
        f"Could not determine audio extension from filename={file.filename!r} "
        f"content_type={file.content_type!r}. Defaulting to .webm."
    )
    return ".webm"


async def transcribe(file: UploadFile) -> str:
    """Transcribe an UploadFile — drains to bytes then delegates to transcribe_bytes."""
    content = await file.read()
    return await transcribe_bytes(
        content,
        filename=file.filename,
        content_type=file.content_type,
    )


async def transcribe_bytes(
    content: bytes,
    *,
    filename: str | None,
    content_type: str | None,
) -> str:
    """
    Transcribe raw audio bytes using OpenAI Whisper (whisper-1).

    Separate from `transcribe` so the async ingest worker can call it without
    constructing a fake UploadFile. Extension is resolved from filename first,
    then content_type, then falls back to .webm.
    """
    if not content:
        raise ValueError("Uploaded audio file is empty.")

    class _Stub:
        pass

    stub = _Stub()
    stub.filename = filename  # type: ignore[attr-defined]
    stub.content_type = content_type  # type: ignore[attr-defined]
    suffix = _resolve_extension(stub)  # type: ignore[arg-type]

    logger.info(
        f"Transcribing audio: filename={filename!r}, "
        f"content_type={content_type!r}, "
        f"resolved_suffix={suffix}, "
        f"size={len(content)} bytes"
    )

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        with open(tmp_path, "rb") as audio_file:
            response = await _whisper_create(audio_file)
        transcript = response if isinstance(response, str) else response.text
        logger.info(f"Transcription complete ({len(transcript)} chars).")
        return transcript.strip()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError as e:
            logger.warning(f"Could not delete temp file {tmp_path}: {e}")
