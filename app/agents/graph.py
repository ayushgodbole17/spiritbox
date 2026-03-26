"""
LangGraph supervisor that orchestrates the four Phase-2 agents:
  entity_extractor -> classifier -> intent_detector -> summarizer -> END

After the graph completes, run_entry_pipeline() saves the entry to Weaviate
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

class EntryState(TypedDict):
    raw_text: str
    entities: dict
    categories: list
    events: list
    summary: str
    entry_id: str
    model_used: dict   # tracks which model tier ran each agent
    cache_hits: dict   # tracks which agents hit the semantic cache


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


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def _build_graph() -> StateGraph:
    graph = StateGraph(EntryState)

    graph.add_node("entity_extractor", node_entity_extractor)
    graph.add_node("classifier", node_classifier)
    graph.add_node("intent_detector", node_intent_detector)
    graph.add_node("summarizer", node_summarizer)

    # Linear supervisor routing
    graph.set_entry_point("entity_extractor")
    graph.add_edge("entity_extractor", "classifier")
    graph.add_edge("classifier", "intent_detector")
    graph.add_edge("intent_detector", "summarizer")
    graph.add_edge("summarizer", END)

    return graph


_compiled_graph = _build_graph().compile()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@observe()
async def run_entry_pipeline(text: str, user_id: str = "default") -> dict:
    """
    Runs the full agent pipeline for a journal entry, then saves to Weaviate.

    Args:
        text:    Raw journal entry text.
        user_id: User identifier for vector store tagging.

    Returns:
        dict with keys: entry_id, entities, categories, events, summary.
    """
    entry_id = str(uuid.uuid4())
    initial_state: EntryState = {
        "raw_text": text,
        "entities": {},
        "categories": [],
        "events": [],
        "summary": "",
        "entry_id": entry_id,
        "model_used": {},
        "cache_hits": {},
    }

    try:
        result = await _compiled_graph.ainvoke(initial_state)
    except Exception as e:
        logger.error(f"Graph invocation failed: {e}", exc_info=True)
        raise

    # Log model tier selections and cache outcomes on the parent span/trace
    get_client().update_current_span(
        metadata={
            "user_id": user_id,
            "model_used": result.get("model_used", {}),
            "cache_hits": result.get("cache_hits", {}),
        },
    )

    categories = result.get("categories", [])

    # Flatten categories for Weaviate storage
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
        await pg_save_entry(
            entry_id=entry_id,
            user_id=user_id,
            raw_text=text,
            summary=result.get("summary", ""),
            categories=categories,
            model_used=result.get("model_used", {}),
            cache_hits=result.get("cache_hits", {}),
        )
        logger.info(f"[graph] Entry {entry_id} saved to PostgreSQL.")
    except Exception as e:
        logger.warning(f"[graph] PostgreSQL save failed (non-fatal): {e}")

    # Persist to Weaviate (vectors + semantic search)
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
        logger.info(f"[graph] Entry {entry_id} upserted to Weaviate.")
    except Exception as e:
        logger.warning(f"[graph] Weaviate upsert failed (non-fatal): {e}")

    return {
        "entry_id": result["entry_id"],
        "entities": result["entities"],
        "categories": result["categories"],
        "events": result["events"],
        "summary": result["summary"],
        "model_used": result.get("model_used", {}),
        "cache_hits": result.get("cache_hits", {}),
    }
