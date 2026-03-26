"""
Firestore events store for Spiritbox.

Document structure (per event):
    {
        'description':    str,
        'event_time':     Timestamp,
        'reminder_time':  Timestamp,
        'scheduler_job':  str,
        'user_email':     str,
        'reminded':       bool,
        'created_at':     Timestamp,
    }

All functions are async (using run_in_executor to wrap sync Firestore SDK calls).
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger(__name__)


def _get_db():
    """Return a Firestore client, initializing if needed."""
    from google.cloud import firestore  # type: ignore
    return firestore.Client()


def _collection():
    return _get_db().collection(settings.FIRESTORE_COLLECTION_EVENTS)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

async def save_event(event: dict) -> str:
    """
    Persist a new event document to Firestore.

    Args:
        event: dict containing event fields (see module docstring).
               'created_at' and 'reminded' will be set automatically if absent.

    Returns:
        Firestore document ID of the created event.
    """
    def _save():
        col = _collection()
        event.setdefault("reminded", False)
        event.setdefault("created_at", datetime.now(timezone.utc))
        _, doc_ref = col.add(event)
        return doc_ref.id

    loop = asyncio.get_event_loop()
    doc_id = await loop.run_in_executor(None, _save)
    logger.info(f"Saved event to Firestore: {doc_id}")
    return doc_id


async def get_event(event_id: str) -> Optional[dict[str, Any]]:
    """
    Retrieve a single event document by ID.

    Args:
        event_id: Firestore document ID.

    Returns:
        dict of event fields plus 'id' key, or None if not found.
    """
    def _get():
        doc_ref = _collection().document(event_id)
        doc = doc_ref.get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        data["id"] = doc.id
        return data

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _get)
    return result


async def mark_reminded(event_id: str) -> None:
    """
    Mark an event as having been reminded (sets reminded=True).

    Args:
        event_id: Firestore document ID.
    """
    def _mark():
        _collection().document(event_id).update({"reminded": True})

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _mark)
    logger.info(f"Marked event {event_id} as reminded.")


async def list_upcoming_reminders(limit: int = 10) -> list[dict[str, Any]]:
    """
    Return upcoming events that have not yet been reminded, sorted by reminder_time.

    Args:
        limit: Maximum number of results.

    Returns:
        List of event dicts (each including 'id').
    """
    def _list():
        from google.cloud import firestore  # type: ignore

        now = datetime.now(timezone.utc)
        query = (
            _collection()
            .where("reminded", "==", False)
            .where("reminder_time", ">=", now)
            .order_by("reminder_time", direction=firestore.Query.ASCENDING)
            .limit(limit)
        )
        docs = query.stream()
        results = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            results.append(data)
        return results

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _list)
