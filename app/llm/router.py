"""
Model Router — Phase 3.

Provides a thin wrapper around the OpenAI AsyncClient that selects the correct
model tier for each agent:

  Tier 1 (cheap/fast)  — classifier, summarizer         → gpt-4o-mini
  Tier 2 (accurate)    — entity_extractor, intent_detector → gpt-4o

If a Tier 1 call fails or returns an empty response, the router automatically
retries on Tier 2 (cascade fallback) and logs the downgrade.

Usage:
    from app.llm.router import chat_completion, TIER_1, TIER_2

    response, model_used = await chat_completion(
        tier=TIER_1,
        messages=messages,
        temperature=0,
        response_format={"type": "json_object"},
    )
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from app.config import settings
from app.llm.resilience import openai_breaker, openai_retry
from app.llm.token_tracker import record_usage

logger = logging.getLogger(__name__)

TIER_1 = "tier1"
TIER_2 = "tier2"

_MODEL_MAP = {
    TIER_1: settings.LLM_TIER_1,  # gpt-4o-mini
    TIER_2: settings.LLM_TIER_2,  # gpt-4o
}


@openai_retry(max_attempts=5)
async def _openai_chat_create(
    client: AsyncOpenAI,
    model: str,
    messages: list[dict],
    temperature: float,
    **kwargs: Any,
) -> ChatCompletion:
    """Inner call guarded by exponential-backoff retry and the OpenAI breaker."""
    return await openai_breaker.call(
        client.chat.completions.create,
        model=model,
        messages=messages,
        temperature=temperature,
        **kwargs,
    )


async def chat_completion(
    tier: str,
    messages: list[dict],
    temperature: float = 0,
    **kwargs: Any,
) -> tuple[ChatCompletion, str]:
    """
    Call the OpenAI chat completions API using the specified tier.

    Each tier is retried on transient errors (rate limit / timeout / connection
    / 5xx) before the tier-1 → tier-2 cascade fires. The shared circuit breaker
    short-circuits calls while OpenAI is flapping.

    Returns:
        Tuple of (ChatCompletion response, model_name_used).
    """
    client = AsyncOpenAI()
    primary_model = _MODEL_MAP.get(tier, settings.LLM_TIER_2)
    fallback_model = settings.LLM_TIER_2

    # --- Primary attempt (with retries on transient errors) ---
    try:
        response = await _openai_chat_create(
            client, primary_model, messages, temperature, **kwargs,
        )
        content = response.choices[0].message.content or ""
        if content.strip():
            if response.usage:
                record_usage(primary_model, response.usage.prompt_tokens, response.usage.completion_tokens)
            return response, primary_model
        logger.warning(
            f"[router] {primary_model} returned empty content — cascading to {fallback_model}"
        )
    except Exception as exc:
        logger.warning(
            f"[router] {primary_model} failed after retries ({exc!r}) — cascading to {fallback_model}"
        )

    # --- Fallback to Tier 2 (also retried) ---
    response = await _openai_chat_create(
        client, fallback_model, messages, temperature, **kwargs,
    )
    if response.usage:
        record_usage(fallback_model, response.usage.prompt_tokens, response.usage.completion_tokens)
    logger.info(f"[router] Cascade: used {fallback_model} (original tier: {tier})")
    return response, fallback_model


async def chat_completion_stream(
    tier: str,
    messages: list[dict],
    temperature: float = 0,
    **kwargs: Any,
) -> tuple[AsyncIterator[str], str]:
    """
    Streaming variant of chat_completion(). Returns an async iterator of
    content-delta strings plus the model name used.

    Falls back from Tier 1 -> Tier 2 on error (same as non-streaming).
    """
    client = AsyncOpenAI()
    primary_model = _MODEL_MAP.get(tier, settings.LLM_TIER_2)
    fallback_model = settings.LLM_TIER_2

    async def _stream(model: str) -> AsyncIterator[str]:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            stream=True,
            **kwargs,
        )
        async for chunk in response:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta

    try:
        return _stream(primary_model), primary_model
    except Exception as exc:
        logger.warning(
            f"[router] {primary_model} stream failed ({exc}) — cascading to {fallback_model}"
        )
        return _stream(fallback_model), fallback_model
