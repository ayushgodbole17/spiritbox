"""
CRUD helpers for PostgreSQL — wraps the SQLAlchemy ORM models.

All functions accept/return plain dicts so callers don't need to import
ORM classes directly.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, delete as sa_delete
from sqlalchemy.orm import selectinload

from app.db.models import Entry, Event, EvalRun, SentenceTag
from app.db.session import get_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

async def save_entry(
    entry_id: str,
    user_id: str,
    raw_text: str,
    summary: str,
    categories: list[dict],   # [{sentence, categories}] from classifier
    model_used: dict,
    cache_hits: dict,
) -> str:
    """
    Persist a journal entry and its sentence tags to PostgreSQL.

    Returns the entry UUID string.
    """
    # Determine model_tier label for the row
    models = [v for v in model_used.values() if v and v != "cache"]
    model_tier = models[0] if models else None
    any_cache_hit = any(v is True for v in cache_hits.values())

    async with get_session() as session:
        entry = Entry(
            id=uuid.UUID(entry_id),
            user_id=user_id,
            raw_text=raw_text,
            summary=summary,
            model_tier=model_tier,
            cache_hit=any_cache_hit,
            created_at=datetime.now(timezone.utc),
        )
        session.add(entry)

        for row in categories:
            if not isinstance(row, dict):
                continue
            sentence = row.get("sentence", "")
            cats = row.get("categories", [])
            if sentence:
                session.add(SentenceTag(
                    entry_id=uuid.UUID(entry_id),
                    sentence=sentence,
                    categories=cats,
                ))

        await session.commit()
        logger.debug(f"[crud] saved entry {entry_id} to PostgreSQL")
        return entry_id


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

async def list_entries(limit: int = 20) -> list[dict[str, Any]]:
    """Return recent entries newest-first with their sentence tags."""
    async with get_session() as session:
        result = await session.execute(
            select(Entry)
            .options(selectinload(Entry.sentence_tags))
            .order_by(Entry.created_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
        return [_entry_to_dict(e) for e in rows]


# ---------------------------------------------------------------------------
# Get one
# ---------------------------------------------------------------------------

async def get_entry(entry_id: str) -> dict[str, Any] | None:
    async with get_session() as session:
        result = await session.execute(
            select(Entry)
            .options(selectinload(Entry.sentence_tags))
            .where(Entry.id == uuid.UUID(entry_id))
        )
        entry = result.scalar_one_or_none()
        if entry is None:
            return None
        return _entry_to_dict(entry)


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

async def update_entry(entry_id: str, raw_text: str) -> bool:
    async with get_session() as session:
        result = await session.execute(
            select(Entry).where(Entry.id == uuid.UUID(entry_id))
        )
        entry = result.scalar_one_or_none()
        if entry is None:
            return False
        entry.raw_text = raw_text
        await session.commit()
        return True


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

async def delete_entry(entry_id: str) -> bool:
    async with get_session() as session:
        result = await session.execute(
            select(Entry).where(Entry.id == uuid.UUID(entry_id))
        )
        entry = result.scalar_one_or_none()
        if entry is None:
            return False
        await session.delete(entry)
        await session.commit()
        return True


# ---------------------------------------------------------------------------
# Events (reminders) — PostgreSQL as authoritative source
# ---------------------------------------------------------------------------

async def save_event(
    entry_id: str,
    description: str,
    event_time: datetime,
    reminder_time: datetime,
    scheduler_job: str | None = None,
) -> str:
    """Persist a reminder event to PostgreSQL. Returns the event UUID string."""
    event_uuid = uuid.uuid4()
    async with get_session() as session:
        session.add(Event(
            id=event_uuid,
            entry_id=uuid.UUID(entry_id) if entry_id else None,
            description=description,
            event_time=event_time,
            reminder_time=reminder_time,
            scheduler_job=scheduler_job,
            reminded=False,
        ))
        await session.commit()
        logger.debug(f"[crud] saved event {event_uuid} to PostgreSQL")
        return str(event_uuid)


async def list_upcoming_events(limit: int = 10) -> list[dict[str, Any]]:
    """Return upcoming events not yet reminded, sorted by reminder_time ascending."""
    now = datetime.now(timezone.utc)
    async with get_session() as session:
        result = await session.execute(
            select(Event)
            .where(Event.reminded == False)  # noqa: E712
            .where(Event.reminder_time >= now)
            .order_by(Event.reminder_time.asc())
            .limit(limit)
        )
        return [_event_to_dict(e) for e in result.scalars().all()]


# ---------------------------------------------------------------------------
# Eval runs
# ---------------------------------------------------------------------------

async def save_eval_run(
    classifier_precision: float,
    entity_f1: float,
    passed: bool,
    prompt_version: str | None = None,
) -> str:
    """Persist an eval run result to PostgreSQL. Returns the run UUID string."""
    run_id = uuid.uuid4()
    async with get_session() as session:
        session.add(EvalRun(
            id=run_id,
            classifier_precision=classifier_precision,
            entity_f1=entity_f1,
            passed=passed,
            prompt_version=prompt_version,
            run_at=datetime.now(timezone.utc),
        ))
        await session.commit()
        logger.debug(f"[crud] saved eval run {run_id} to PostgreSQL")
        return str(run_id)


# ---------------------------------------------------------------------------
# Serialise
# ---------------------------------------------------------------------------

def _entry_to_dict(entry: Entry) -> dict[str, Any]:
    tags = getattr(entry, "sentence_tags", []) or []
    # Ordered dedup: preserve insertion order, not a set
    seen: set[str] = set()
    categories_flat: list[str] = []
    for t in tags:
        for cat in (t.categories or []):
            if cat not in seen:
                categories_flat.append(cat)
                seen.add(cat)
    sentence_tags_list = [
        {"sentence": t.sentence, "categories": list(t.categories or [])}
        for t in tags
    ]
    return {
        "entry_id":      str(entry.id),
        "user_id":       entry.user_id,
        "raw_text":      entry.raw_text or "",
        "summary":       entry.summary or "",
        "categories":    categories_flat,
        "sentence_tags": sentence_tags_list,
        "model_tier":    entry.model_tier,
        "cache_hit":     entry.cache_hit,
        "created_at":    entry.created_at.isoformat() if entry.created_at else None,
        "entry_date":    entry.created_at.isoformat() if entry.created_at else None,
    }


def _event_to_dict(event: Event) -> dict[str, Any]:
    return {
        "event_id":      str(event.id),
        "entry_id":      str(event.entry_id) if event.entry_id else None,
        "description":   event.description,
        "event_time":    event.event_time.isoformat() if event.event_time else None,
        "reminder_time": event.reminder_time.isoformat() if event.reminder_time else None,
        "scheduler_job": event.scheduler_job,
        "reminded":      event.reminded,
    }
