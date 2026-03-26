"""
Summarizer Agent — Phase 2.

Uses GPT-4o to produce a concise 2-3 sentence summary of the journal entry,
suitable for display in a feed.
"""
import logging

from langfuse import observe

from app.agents.graph import EntryState
from app.llm.router import chat_completion, TIER_1
from app.llm.cache import get_cached, set_cached
from app.prompts.summarize import SYSTEM as SUMMARIZE_SYSTEM, USER_TEMPLATE as SUMMARIZE_USER
from app.prompts.loader import get_messages

logger = logging.getLogger(__name__)

_NAMESPACE = "summarizer"


@observe()
async def summarize_entry(state: EntryState) -> EntryState:
    """
    Produce a short summary of the journal entry.

    Checks the semantic cache first; on miss calls the model router (Tier 1),
    stores the result, and updates state['summary'] and tracking fields.

    Args:
        state: Current EntryState containing 'raw_text'.

    Returns:
        Updated EntryState with 'summary', 'model_used', 'cache_hits' populated.
    """
    raw_text = state["raw_text"]

    # --- Cache lookup ---
    cached = await get_cached(raw_text, namespace=_NAMESPACE)
    if cached is not None:
        logger.debug("[summarizer] cache hit")
        return {
            **state,
            "summary": cached,
            "model_used": {**state.get("model_used", {}), _NAMESPACE: "cache"},
            "cache_hits": {**state.get("cache_hits", {}), _NAMESPACE: True},
        }

    try:
        messages, prompt_version = get_messages(
            name="spiritbox.summarize.v1",
            fallback=[
                {"role": "system", "content": SUMMARIZE_SYSTEM},
                {"role": "user",   "content": SUMMARIZE_USER},
            ],
            variables={"transcript": raw_text},
        )
        response, model_name = await chat_completion(
            tier=TIER_1,
            messages=messages,
            temperature=0.3,
        )
        summary = (response.choices[0].message.content or "").strip()
        logger.debug(f"[summarizer] generated summary ({len(summary)} chars).")
        await set_cached(raw_text, summary, namespace=_NAMESPACE)
        return {
            **state,
            "summary": summary,
            "model_used": {**state.get("model_used", {}), _NAMESPACE: model_name},
            "cache_hits": {**state.get("cache_hits", {}), _NAMESPACE: False},
            "prompt_versions": {**state.get("prompt_versions", {}), _NAMESPACE: prompt_version},
        }

    except Exception as exc:
        logger.error(f"[summarizer] unexpected error: {exc}", exc_info=True)
        return {**state, "summary": ""}


@observe()
async def summarize(text: str) -> str:
    """
    Backward-compatible wrapper: summarize a raw text string.

    Returns the summary string, or an empty string on failure.
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
    result = await summarize_entry(state)
    return result["summary"]
