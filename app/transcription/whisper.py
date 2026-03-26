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

logger = logging.getLogger(__name__)

_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

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
    """
    Transcribe an audio UploadFile using OpenAI Whisper (whisper-1).

    The file is written to a temporary file on disk (Whisper API requires a
    seekable file object), transcribed, then the temp file is deleted.

    Supported formats: mp3, wav, m4a, webm (audio/webm and audio/webm;codecs=opus),
    ogg, flac, mp4.

    Args:
        file: FastAPI UploadFile (audio content).

    Returns:
        Transcribed text string.

    Raises:
        ValueError: If the uploaded file is empty.
        openai.OpenAIError: On API-level errors.
    """
    content = await file.read()
    if not content:
        raise ValueError("Uploaded audio file is empty.")

    suffix = _resolve_extension(file)

    logger.info(
        f"Transcribing audio: filename={file.filename!r}, "
        f"content_type={file.content_type!r}, "
        f"resolved_suffix={suffix}, "
        f"size={len(content)} bytes"
    )

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        with open(tmp_path, "rb") as audio_file:
            response = await _client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text",
            )
        # response is a plain str when response_format="text"
        transcript = response if isinstance(response, str) else response.text
        logger.info(f"Transcription complete ({len(transcript)} chars).")
        return transcript.strip()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError as e:
            logger.warning(f"Could not delete temp file {tmp_path}: {e}")
