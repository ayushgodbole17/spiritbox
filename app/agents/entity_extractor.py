"""
Entity Extractor Agent — Phase 2.

Uses GPT-4o to extract structured entities (people, places, amounts, events,
dates, organizations) from a journal entry.
"""
import json
import logging

from langfuse import observe

from app.agents.graph import EntryState
from app.llm.router import chat_completion, TIER_2
from app.llm.cache import get_cached, set_cached
from app.prompts.extract_entities import SYSTEM as ENTITY_SYSTEM, USER_TEMPLATE as ENTITY_USER
from app.prompts.loader import get_messages

logger = logging.getLogger(__name__)

ALLOWED_KEYS = {"people", "places", "dates", "events", "amounts", "organizations"}

_NAMESPACE = "entity_extractor"


@observe()
async def extract_entities(state: EntryState) -> EntryState:
    """
    Extract named entities from the journal entry text.

    Checks the semantic cache first; on miss calls the model router (Tier 2),
    stores the result, and updates state['entities'], 'events', and tracking fields.

    Args:
        state: Current EntryState containing 'raw_text'.

    Returns:
        Updated EntryState with 'entities', 'events', 'model_used', 'cache_hits' populated.
    """
    raw_text = state["raw_text"]

    # --- Cache lookup ---
    cached = await get_cached(raw_text, namespace=_NAMESPACE)
    if cached is not None:
        logger.debug("[entity_extractor] cache hit")
        entities, events = cached
        return {
            **state,
            "entities": entities,
            "events": events,
            "model_used": {**state.get("model_used", {}), _NAMESPACE: "cache"},
            "cache_hits": {**state.get("cache_hits", {}), _NAMESPACE: True},
        }

    try:
        messages, prompt_version = get_messages(
            name="spiritbox.extract_entities.v1",
            fallback=[
                {"role": "system", "content": ENTITY_SYSTEM},
                {"role": "user",   "content": ENTITY_USER},
            ],
            variables={"transcript": raw_text},
        )
        response, model_name = await chat_completion(
            tier=TIER_2,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw = response.choices[0].message.content or "{}"
        parsed = json.loads(raw)

        # Strip any keys not in our schema
        entities = {k: v for k, v in parsed.items() if k in ALLOWED_KEYS}

        # Ensure list fields are actually lists
        for key in ("people", "places", "dates", "organizations"):
            if key in entities and not isinstance(entities[key], list):
                entities[key] = []
        if "events" in entities and not isinstance(entities["events"], list):
            entities["events"] = []
        if "amounts" in entities and not isinstance(entities["amounts"], list):
            entities["amounts"] = []

        events = entities.get("events", [])
        logger.debug(
            f"[entity_extractor] extracted {len(entities)} entity types, "
            f"{len(events)} events."
        )
        await set_cached(raw_text, (entities, events), namespace=_NAMESPACE)
        return {
            **state,
            "entities": entities,
            "events": events,
            "model_used": {**state.get("model_used", {}), _NAMESPACE: model_name},
            "cache_hits": {**state.get("cache_hits", {}), _NAMESPACE: False},
            "prompt_versions": {**state.get("prompt_versions", {}), _NAMESPACE: prompt_version},
        }

    except json.JSONDecodeError as exc:
        logger.warning(f"[entity_extractor] JSON parse error: {exc}. Returning empty dict.")
        return {**state, "entities": {}, "events": []}
    except Exception as exc:
        logger.error(f"[entity_extractor] unexpected error: {exc}", exc_info=True)
        return {**state, "entities": {}, "events": []}


@observe()
async def extract(text: str) -> dict:
    """
    Backward-compatible wrapper: extract entities from a raw text string.

    Returns entity dict, or an empty dict on failure.
    """
    from app.agents.graph import EntryState
    state: EntryState = {
        "raw_text": text,
        "entities": {},
        "categories": [],
        "events": [],
        "summary": "",
        "entry_id": "",
    }
    result = await extract_entities(state)
    return result["entities"]
