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
from typing import Any

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from app.config import settings

logger = logging.getLogger(__name__)

TIER_1 = "tier1"
TIER_2 = "tier2"

_MODEL_MAP = {
    TIER_1: settings.LLM_TIER_1,  # gpt-4o-mini
    TIER_2: settings.LLM_TIER_2,  # gpt-4o
}


async def chat_completion(
    tier: str,
    messages: list[dict],
    temperature: float = 0,
    **kwargs: Any,
) -> tuple[ChatCompletion, str]:
    """
    Call the OpenAI chat completions API using the specified tier.

    Falls back from Tier 1 → Tier 2 if the primary call fails or returns
    an empty content string.

    Args:
        tier:        TIER_1 or TIER_2.
        messages:    List of {role, content} dicts.
        temperature: Sampling temperature.
        **kwargs:    Additional kwargs forwarded to client.chat.completions.create
                     (e.g. response_format).

    Returns:
        Tuple of (ChatCompletion response, model_name_used).
    """
    client = AsyncOpenAI()
    primary_model = _MODEL_MAP.get(tier, settings.LLM_TIER_2)
    fallback_model = settings.LLM_TIER_2  # always fall back to the strongest tier

    # --- Primary attempt ---
    try:
        response = await client.chat.completions.create(
            model=primary_model,
            messages=messages,
            temperature=temperature,
            **kwargs,
        )
        content = response.choices[0].message.content or ""
        if content.strip():
            logger.debug(f"[router] {tier} → {primary_model} (ok)")
            return response, primary_model
        # Empty content — cascade
        logger.warning(
            f"[router] {primary_model} returned empty content — cascading to {fallback_model}"
        )
    except Exception as exc:
        logger.warning(
            f"[router] {primary_model} failed ({exc}) — cascading to {fallback_model}"
        )

    # --- Fallback to Tier 2 ---
    response = await client.chat.completions.create(
        model=fallback_model,
        messages=messages,
        temperature=temperature,
        **kwargs,
    )
    logger.info(f"[router] Cascade: used {fallback_model} (original tier: {tier})")
    return response, fallback_model
