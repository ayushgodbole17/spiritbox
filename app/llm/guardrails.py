"""
Output validation guardrail for LLM responses.

Parses raw JSON from an LLM, validates it against a Pydantic schema,
and optionally retries with a correction prompt on validation failure.
"""
from __future__ import annotations

import json
import logging
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from app.llm.router import chat_completion, TIER_1

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_CORRECTION_SYSTEM = (
    "You are a JSON repair assistant. The user will show you a JSON object that "
    "failed validation and the error message. Return ONLY a corrected JSON object "
    "that satisfies the schema. No explanation, no markdown fences."
)


async def validate_llm_output(
    raw_json: str,
    schema: Type[T],
    max_retries: int = 1,
) -> T:
    """
    Parse and validate raw LLM JSON output against a Pydantic schema.

    On ValidationError, sends a correction prompt to the LLM (up to max_retries).
    Raises ValidationError if all attempts fail.
    """
    last_error: ValidationError | None = None

    for attempt in range(1 + max_retries):
        try:
            data = json.loads(raw_json)
            return schema.model_validate(data)
        except json.JSONDecodeError as exc:
            logger.warning(f"[guardrails] JSON decode error (attempt {attempt + 1}): {exc}")
            last_error = ValidationError.from_exception_data(
                title=schema.__name__,
                line_errors=[],
            )
        except ValidationError as exc:
            last_error = exc
            logger.warning(
                f"[guardrails] Validation failed (attempt {attempt + 1}): "
                f"{exc.error_count()} errors"
            )

        if attempt < max_retries:
            raw_json = await _retry_with_correction(raw_json, str(last_error))

    raise last_error  # type: ignore[misc]


async def _retry_with_correction(bad_json: str, error_msg: str) -> str:
    """Ask the LLM to fix the JSON based on the validation error."""
    logger.info("[guardrails] requesting LLM correction")
    response, _ = await chat_completion(
        tier=TIER_1,
        messages=[
            {"role": "system", "content": _CORRECTION_SYSTEM},
            {"role": "user", "content": f"Bad JSON:\n{bad_json}\n\nError:\n{error_msg}"},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content or "{}"
