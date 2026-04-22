"""
LangGraph supervisor that orchestrates the four Phase-2 agents:
  entity_extractor -> classifier -> intent_detector -> summarizer -> END

After the graph completes, run_entry_pipeline() saves the entry to pgvector
via app/memory/vector_store.upsert_entry().
"""
import json
import logging
import uuid
from typing import TypedDict

from langgraph.graph import StateGraph, END
from langfuse import observe, get_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------

class EntryState(TypedDict, total=False):
    raw_text: str
    entities: dict
    categories: list
    events: list
    summary: str
    entry_id: str
    user_id: str
    habits: dict          # {matched: [habit_id], new: [name]}
    model_used: dict      # tracks which model tier ran each agent
    cache_hits: dict      # tracks which agents hit the semantic cache
    prompt_versions: dict # tracks which LangFuse prompt version each agent used


# ---------------------------------------------------------------------------
# Node functions (thin wrappers — import agents lazily to avoid circular deps)
# ---------------------------------------------------------------------------

async def node_entity_extractor(state: EntryState) -> EntryState:
    logger.debug("Node: entity_extractor")
    from app.agents.entity_extractor import extract_entities
    return await extract_entities(state)


async def node_classifier(state: EntryState) -> EntryState:
    logger.debug("Node: classifier")
    from app.agents.classifier import classify_sentences
    return await classify_sentences(state)


async def node_intent_detector(state: EntryState) -> EntryState:
    logger.debug("Node: intent_detector")
    from app.agents.intent_detector import detect_intents
    return await detect_intents(state)


async def node_summarizer(state: EntryState) -> EntryState:
    logger.debug("Node: summarizer")
    from app.agents.summarizer import summarize_entry
    return await summarize_entry(state)


async def node_habit_tracker(state: EntryState) -> EntryState:
    logger.debug("Node: habit_tracker")
    try:
        from app.agents.habit_tracker import track_habits
        return await track_habits(state)
    except Exception as exc:
        logger.warning(f"[graph] habit_tracker bombed (non-fatal): {exc!r}")
        return {**state, "habits": {"matched": [], "new": []}}


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def _build_graph() -> StateGraph:
    graph = StateGraph(EntryState)

    graph.add_node("entity_extractor", node_entity_extractor)
    graph.add_node("classifier", node_classifier)
    graph.add_node("intent_detector", node_intent_detector)
    graph.add_node("summarizer", node_summarizer)
    graph.add_node("habit_tracker", node_habit_tracker)

    # Linear supervisor routing
    graph.set_entry_point("entity_extractor")
    graph.add_edge("entity_extractor", "classifier")
    graph.add_edge("classifier", "intent_detector")
    graph.add_edge("intent_detector", "summarizer")
    graph.add_edge("summarizer", "habit_tracker")
    graph.add_edge("habit_tracker", END)

    return graph


_compiled_graph = _build_graph().compile()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@observe()
async def run_entry_pipeline(text: str, user_id: str = "default") -> dict:
    """
    Runs the full agent pipeline for a journal entry, then saves to pgvector.

    Args:
        text:    Raw journal entry text.
        user_id: User identifier for vector store tagging.

    Returns:
        dict with keys: entry_id, entities, categories, events, summary.
    """
    entry_id = str(uuid.uuid4())

    # Propagate the incoming request's correlation ID onto the LangFuse trace
    # so structured logs and traces can be cross-referenced.
    try:
        from app.middleware.correlation import correlation_id
        cid = correlation_id.get("-")
        if cid and cid != "-":
            get_client().update_current_trace(metadata={"correlation_id": cid})
    except Exception:
        pass

    # Scrub PII before the text ever reaches an external LLM.
    # The original text is still what we persist to the user's own journal.
    from app.llm.guardrails import redact_pii
    redacted_text, pii_map = redact_pii(text)
    if pii_map:
        logger.info(f"[graph] redacted {len(pii_map)} PII tokens before LLM calls")

    initial_state: EntryState = {
        "raw_text": redacted_text,
        "entities": {},
        "categories": [],
        "events": [],
        "summary": "",
        "entry_id": entry_id,
        "user_id": user_id,
        "habits": {"matched": [], "new": []},
        "model_used": {},
        "cache_hits": {},
        "prompt_versions": {},
    }

    try:
        result = await _compiled_graph.ainvoke(initial_state)
    except Exception as e:
        logger.error(f"Graph invocation failed: {e}", exc_info=True)
        raise

    # Rehydrate: substitute redaction tokens back with their originals so the
    # user sees their own journal, not "[EMAIL_1]". Only user-visible fields.
    if pii_map:
        summary = result.get("summary") or ""
        for token, original in pii_map.items():
            summary = summary.replace(token, original)
        result["summary"] = summary

    # Log model tier selections and cache outcomes on the parent span/trace
    get_client().update_current_span(
        metadata={
            "user_id": user_id,
            "model_used": result.get("model_used", {}),
            "cache_hits": result.get("cache_hits", {}),
            "prompt_versions": result.get("prompt_versions", {}),
        },
    )

    categories = result.get("categories", [])

    # Flatten categories for storage
    flat_categories: list[str] = []
    seen: set[str] = set()
    for item in categories:
        if isinstance(item, dict):
            for cat in item.get("categories", []):
                if cat not in seen:
                    flat_categories.append(cat)
                    seen.add(cat)
        elif isinstance(item, str) and item not in seen:
            flat_categories.append(item)
            seen.add(item)

    # Persist to PostgreSQL (source of truth)
    try:
        from app.db.crud import save_entry as pg_save_entry
        from app.llm.token_tracker import get_usage
        await pg_save_entry(
            entry_id=entry_id,
            user_id=user_id,
            raw_text=text,
            summary=result.get("summary", ""),
            categories=categories,
            model_used=result.get("model_used", {}),
            cache_hits=result.get("cache_hits", {}),
            token_usage=get_usage().to_dict(),
        )
        logger.info(f"[graph] Entry {entry_id} saved to PostgreSQL.")
    except Exception as e:
        logger.warning(f"[graph] PostgreSQL save failed (non-fatal): {e}")

    # Persist to pgvector (vectors + semantic search)
    try:
        from app.memory.vector_store import upsert_entry
        await upsert_entry(
            {
                "entry_id": entry_id,
                "raw_text": text,
                "summary": result.get("summary", ""),
                "categories": flat_categories,
                "sentence_tags": json.dumps(categories),
                "user_id": user_id,
            }
        )
        logger.info(f"[graph] Entry {entry_id} upserted to pgvector.")
    except Exception as e:
        logger.warning(f"[graph] pgvector upsert failed (non-fatal): {e}")

    return {
        "entry_id": result["entry_id"],
        "entities": result["entities"],
        "categories": result["categories"],
        "events": result["events"],
        "summary": result["summary"],
        "model_used": result.get("model_used", {}),
        "cache_hits": result.get("cache_hits", {}),
        "prompt_versions": result.get("prompt_versions", {}),
    }
