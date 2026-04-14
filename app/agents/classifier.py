"""
Classifier Agent — Phase 2.

Uses GPT-4o to classify each sentence of a journal entry into life-domain
categories (health, finances, work, music, etc.).
"""
import json
import logging

from langfuse import observe

from pydantic import ValidationError

from app.agents.graph import EntryState
from app.agents.schemas import ClassificationResult
from app.llm.guardrails import validate_llm_output
from app.llm.router import chat_completion, TIER_1
from app.llm.cache import get_cached, set_cached
from app.prompts.classify import SYSTEM as CLASSIFY_SYSTEM, USER_TEMPLATE as CLASSIFY_USER
from app.prompts.loader import get_messages

logger = logging.getLogger(__name__)

_NAMESPACE = "classifier"


@observe()
async def classify_sentences(state: EntryState) -> EntryState:
    """
    Classify each sentence of the journal entry into life-domain categories.

    Checks the semantic cache first; on miss calls the model router (Tier 1),
    stores the result, and updates state['categories'] and tracking fields.

    Args:
        state: Current EntryState containing 'raw_text'.

    Returns:
        Updated EntryState with 'categories', 'model_used', 'cache_hits' populated.
    """
    raw_text = state["raw_text"]

    # --- Cache lookup ---
    cached = await get_cached(raw_text, namespace=_NAMESPACE)
    if cached is not None:
        logger.debug("[classifier] cache hit")
        return {
            **state,
            "categories": cached,
            "model_used": {**state.get("model_used", {}), _NAMESPACE: "cache"},
            "cache_hits": {**state.get("cache_hits", {}), _NAMESPACE: True},
        }

    try:
        messages, prompt_version = get_messages(
            name="spiritbox.classify.v1",
            fallback=[
                {"role": "system", "content": CLASSIFY_SYSTEM},
                {"role": "user",   "content": CLASSIFY_USER},
            ],
            variables={"transcript": raw_text},
        )
        response, model_name = await chat_completion(
            tier=TIER_1,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw = response.choices[0].message.content or "{}"

        # Normalise: wrap bare arrays in {"classifications": [...]}
        try:
            pre = json.loads(raw)
        except json.JSONDecodeError:
            pre = {}
        if isinstance(pre, list):
            raw = json.dumps({"classifications": pre})
        elif isinstance(pre, dict) and "classifications" not in pre:
            for v in pre.values():
                if isinstance(v, list):
                    raw = json.dumps({"classifications": v})
                    break

        validated = await validate_llm_output(raw, ClassificationResult)
        sanitised = [item.model_dump() for item in validated.classifications]

        logger.debug(f"[classifier] classified {len(sanitised)} sentences.")
        await set_cached(raw_text, sanitised, namespace=_NAMESPACE)
        return {
            **state,
            "categories": sanitised,
            "model_used": {**state.get("model_used", {}), _NAMESPACE: model_name},
            "cache_hits": {**state.get("cache_hits", {}), _NAMESPACE: False},
            "prompt_versions": {**state.get("prompt_versions", {}), _NAMESPACE: prompt_version},
        }

    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning(f"[classifier] output validation failed: {exc}. Returning empty list.")
        return {**state, "categories": []}
    except Exception as exc:
        logger.error(f"[classifier] unexpected error: {exc}", exc_info=True)
        return {**state, "categories": []}


@observe()
async def classify(text: str) -> list:
    """
    Backward-compatible wrapper: classify a raw text string.

    Returns a list of {sentence, categories} dicts, or an empty list on failure.
    """
    # Build a minimal state so we can reuse classify_sentences
    from app.agents.graph import EntryState
    state: EntryState = {
        "raw_text": text,
        "entities": {},
        "categories": [],
        "events": [],
        "summary": "",
        "entry_id": "",
    }
    result = await classify_sentences(state)
    return result["categories"]
