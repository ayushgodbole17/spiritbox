"""
Weaviate vector store wrapper for Spiritbox JournalEntry objects.

Provides:
  - init_schema()         — idempotently creates the JournalEntry class
  - upsert_entry(entry)   — insert or update a JournalEntry, returns UUID
  - semantic_search(...)  — near-text vector search
  - get_entry(entry_id)   — fetch single object by UUID
  - list_entries(limit)   — paginated listing
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import weaviate
import weaviate.classes as wvc
from weaviate.classes.config import Configure, Property, DataType

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema definition
# ---------------------------------------------------------------------------

JOURNAL_CLASS = "JournalEntry"

_SCHEMA = {
    "class": JOURNAL_CLASS,
    "properties": [
        {"name": "raw_text", "dataType": ["text"]},
        {"name": "summary", "dataType": ["text"]},
        {"name": "categories", "dataType": ["text[]"]},
        {"name": "sentence_tags", "dataType": ["text"]},   # JSON string
        {"name": "entry_date", "dataType": ["date"]},
        {"name": "user_id", "dataType": ["text"]},
    ],
    "vectorizer": "text2vec-openai",
}


def _get_client() -> weaviate.WeaviateClient:
    """Create and return a connected Weaviate client."""
    auth = None
    if settings.WEAVIATE_API_KEY:
        auth = weaviate.auth.AuthApiKey(settings.WEAVIATE_API_KEY)

    client = weaviate.connect_to_custom(
        http_host=settings.WEAVIATE_URL.replace("http://", "").replace("https://", "").split(":")[0],
        http_port=int(settings.WEAVIATE_URL.split(":")[-1]) if ":" in settings.WEAVIATE_URL.split("//")[-1] else 80,
        http_secure=settings.WEAVIATE_URL.startswith("https"),
        grpc_host=settings.WEAVIATE_URL.replace("http://", "").replace("https://", "").split(":")[0],
        grpc_port=50051,
        grpc_secure=False,
        auth_credentials=auth,
        headers={"X-OpenAI-Api-Key": settings.OPENAI_API_KEY} if settings.OPENAI_API_KEY else {},
    )
    return client


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

async def init_schema() -> None:
    """
    Idempotently ensures the JournalEntry collection exists in Weaviate.
    Safe to call multiple times — does nothing if already present.
    """
    try:
        client = _get_client()
        with client:
            collections = client.collections.list_all()
            existing = [c for c in collections]
            if JOURNAL_CLASS not in existing:
                client.collections.create_from_dict(_SCHEMA)
                logger.info(f"Created Weaviate collection '{JOURNAL_CLASS}'.")
            else:
                logger.info(f"Weaviate collection '{JOURNAL_CLASS}' already exists — skipping.")
    except Exception as e:
        logger.warning(f"init_schema failed: {e}")
        raise


async def upsert_entry(entry: dict) -> str:
    """
    Insert a JournalEntry into Weaviate. Returns the UUID used.

    Uses the entry_id from the dict if provided (so it matches the PostgreSQL
    row), otherwise generates a new UUID.

    Args:
        entry: dict with keys matching the schema properties.

    Returns:
        UUID string of the inserted object.
    """
    entry_id = entry.get("entry_id") or str(uuid.uuid4())

    properties = {
        "raw_text": entry.get("raw_text", ""),
        "summary": entry.get("summary", ""),
        "categories": entry.get("categories", []),
        "sentence_tags": entry.get("sentence_tags", "{}"),
        "entry_date": datetime.now(timezone.utc).isoformat(),
        "user_id": entry.get("user_id", "default"),
    }

    client = _get_client()
    with client:
        collection = client.collections.get(JOURNAL_CLASS)
        result = collection.data.insert(
            properties=properties,
            uuid=entry_id,
        )
        return str(result)


async def semantic_search(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """
    Perform near-text (semantic) search against JournalEntry objects.

    Args:
        query: Natural language search string.
        limit: Maximum number of results.

    Returns:
        List of matching entry dicts with a 'score' field.
    """
    client = _get_client()
    with client:
        collection = client.collections.get(JOURNAL_CLASS)
        response = collection.query.near_text(
            query=query,
            limit=limit,
            return_metadata=wvc.query.MetadataQuery(certainty=True, distance=True),
        )
        results = []
        for obj in response.objects:
            item = dict(obj.properties)
            item["entry_id"] = str(obj.uuid)
            item["score"] = obj.metadata.certainty if obj.metadata else None
            results.append(item)
        return results


async def get_entry(entry_id: str) -> Optional[dict[str, Any]]:
    """
    Fetch a single JournalEntry by UUID.

    Args:
        entry_id: Weaviate UUID string.

    Returns:
        Entry dict or None if not found.
    """
    client = _get_client()
    with client:
        collection = client.collections.get(JOURNAL_CLASS)
        try:
            obj = collection.data.get_by_id(uuid=entry_id)
        except Exception:
            return None

        if obj is None:
            return None

        item = dict(obj.properties)
        item["entry_id"] = str(obj.uuid)
        return item


async def update_entry(entry_id: str, raw_text: str) -> bool:
    """Update the raw_text of a JournalEntry. Returns True if updated."""
    client = _get_client()
    with client:
        collection = client.collections.get(JOURNAL_CLASS)
        try:
            collection.data.update(uuid=entry_id, properties={"raw_text": raw_text})
            logger.info(f"Updated Weaviate entry {entry_id}.")
            return True
        except Exception as e:
            logger.warning(f"update_entry failed for {entry_id}: {e}")
            return False


async def delete_entry(entry_id: str) -> bool:
    """
    Delete a JournalEntry from Weaviate by UUID.

    Returns True if deleted, False if not found.
    """
    client = _get_client()
    with client:
        collection = client.collections.get(JOURNAL_CLASS)
        try:
            collection.data.delete_by_id(uuid=entry_id)
            logger.info(f"Deleted Weaviate entry {entry_id}.")
            return True
        except Exception as e:
            logger.warning(f"delete_entry failed for {entry_id}: {e}")
            return False


async def list_entries(limit: int = 20) -> list[dict[str, Any]]:
    """
    Return recent JournalEntry objects.

    Args:
        limit: Maximum number of entries.

    Returns:
        List of entry dicts.
    """
    client = _get_client()
    with client:
        collection = client.collections.get(JOURNAL_CLASS)
        response = collection.query.fetch_objects(limit=limit)
        results = []
        for obj in response.objects:
            item = dict(obj.properties)
            item["entry_id"] = str(obj.uuid)
            results.append(item)
        return results
