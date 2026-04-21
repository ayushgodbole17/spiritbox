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

from app.db.models import Entry, Event, EvalRun, IngestJob, ReminderDeadLetter, SentenceTag
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
    token_usage: dict | None = None,
) -> str:
    """
    Persist a journal entry and its sentence tags to PostgreSQL.

    Returns the entry UUID string.
    """
    # Determine model_tier label for the row
    models = [v for v in model_used.values() if v and v != "cache"]
    model_tier = models[0] if models else None
    any_cache_hit = any(v is True for v in cache_hits.values())
    tu = token_usage or {}

    async with get_session() as session:
        entry = Entry(
            id=uuid.UUID(entry_id),
            user_id=user_id,
            raw_text=raw_text,
            summary=summary,
            model_tier=model_tier,
            cache_hit=any_cache_hit,
            prompt_tokens=tu.get("prompt_tokens", 0),
            completion_tokens=tu.get("completion_tokens", 0),
            embedding_tokens=tu.get("embedding_tokens", 0),
            estimated_cost_usd=tu.get("estimated_cost_usd", 0.0),
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

async def list_entries(user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent entries for a user, newest-first, with their sentence tags."""
    async with get_session() as session:
        result = await session.execute(
            select(Entry)
            .options(selectinload(Entry.sentence_tags))
            .where(Entry.user_id == user_id)
            .order_by(Entry.created_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
        return [_entry_to_dict(e) for e in rows]


# ---------------------------------------------------------------------------
# Get one
# ---------------------------------------------------------------------------

async def get_entry(entry_id: str, user_id: str) -> dict[str, Any] | None:
    async with get_session() as session:
        result = await session.execute(
            select(Entry)
            .options(selectinload(Entry.sentence_tags))
            .where(Entry.id == uuid.UUID(entry_id), Entry.user_id == user_id)
        )
        entry = result.scalar_one_or_none()
        if entry is None:
            return None
        return _entry_to_dict(entry)


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

async def update_entry(entry_id: str, user_id: str, raw_text: str) -> bool:
    async with get_session() as session:
        result = await session.execute(
            select(Entry).where(Entry.id == uuid.UUID(entry_id), Entry.user_id == user_id)
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

async def delete_entry(entry_id: str, user_id: str) -> bool:
    async with get_session() as session:
        result = await session.execute(
            select(Entry).where(Entry.id == uuid.UUID(entry_id), Entry.user_id == user_id)
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


async def update_event_scheduler_job(event_id: str, job_name: str) -> None:
    """Persist the Cloud Scheduler job name on an existing event row."""
    async with get_session() as session:
        result = await session.execute(
            select(Event).where(Event.id == uuid.UUID(event_id))
        )
        event = result.scalar_one_or_none()
        if event is None:
            logger.warning(f"[crud] update_event_scheduler_job: event {event_id} not found")
            return
        event.scheduler_job = job_name
        await session.commit()


async def mark_event_reminded(event_id: str) -> bool:
    """Set events.reminded = TRUE. Returns True if the row existed."""
    async with get_session() as session:
        result = await session.execute(
            select(Event).where(Event.id == uuid.UUID(event_id))
        )
        event = result.scalar_one_or_none()
        if event is None:
            return False
        event.reminded = True
        await session.commit()
        return True


async def list_upcoming_events(user_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """Return upcoming events for a user, not yet reminded, sorted by reminder_time ascending."""
    now = datetime.now(timezone.utc)
    async with get_session() as session:
        result = await session.execute(
            select(Event)
            .join(Entry, Event.entry_id == Entry.id)
            .where(Event.reminded == False)  # noqa: E712
            .where(Event.reminder_time >= now)
            .where(Entry.user_id == user_id)
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


# ---------------------------------------------------------------------------
# Ingest job helpers (Phase D)
# ---------------------------------------------------------------------------

async def create_ingest_job(user_id: str, kind: str, filename: str | None) -> str:
    """Insert a fresh ingest_jobs row and return its UUID."""
    job_id = str(uuid.uuid4())
    async with get_session() as session:
        session.add(IngestJob(
            id=uuid.UUID(job_id),
            user_id=user_id,
            kind=kind,
            status="queued",
            filename=filename,
        ))
        await session.commit()
    return job_id


async def update_ingest_job(
    job_id: str,
    *,
    status: str | None = None,
    entry_id: str | None = None,
    error: str | None = None,
    result_json: str | None = None,
) -> None:
    async with get_session() as session:
        job = await session.get(IngestJob, uuid.UUID(job_id))
        if job is None:
            logger.warning(f"[crud] update_ingest_job: {job_id} not found")
            return
        if status is not None:
            job.status = status
        if entry_id is not None:
            job.entry_id = uuid.UUID(entry_id)
        if error is not None:
            job.error = error[:2000]
        if result_json is not None:
            job.result_json = result_json
        job.updated_at = datetime.now(timezone.utc)
        await session.commit()


async def get_ingest_job(job_id: str, user_id: str) -> dict | None:
    async with get_session() as session:
        job = await session.get(IngestJob, uuid.UUID(job_id))
        if job is None or job.user_id != user_id:
            return None
        return {
            "job_id":      str(job.id),
            "user_id":     job.user_id,
            "kind":        job.kind,
            "status":      job.status,
            "filename":    job.filename,
            "entry_id":    str(job.entry_id) if job.entry_id else None,
            "result_json": job.result_json,
            "error":       job.error,
            "created_at":  job.created_at.isoformat() if job.created_at else None,
            "updated_at":  job.updated_at.isoformat() if job.updated_at else None,
        }


# ---------------------------------------------------------------------------
# Reminder DLQ helpers (Phase D)
# ---------------------------------------------------------------------------

async def record_reminder_failure(
    event_id: str,
    user_email: str | None,
    description: str | None,
    event_time_iso: str | None,
    error: str,
) -> str:
    """Record a failed reminder into the DLQ. Returns the DLQ row id."""
    evt_dt: datetime | None = None
    if event_time_iso:
        try:
            evt_dt = datetime.fromisoformat(event_time_iso.replace("Z", "+00:00"))
        except ValueError:
            evt_dt = None

    dlq_id = str(uuid.uuid4())
    async with get_session() as session:
        session.add(ReminderDeadLetter(
            id=uuid.UUID(dlq_id),
            event_id=uuid.UUID(event_id) if event_id else None,
            user_email=user_email,
            description=description,
            event_time=evt_dt,
            error=error[:2000],
        ))
        await session.commit()
    return dlq_id


async def list_reminder_dlq(resolved: bool = False, limit: int = 100) -> list[dict]:
    async with get_session() as session:
        stmt = (
            select(ReminderDeadLetter)
            .where(ReminderDeadLetter.resolved == resolved)
            .order_by(ReminderDeadLetter.created_at.desc())
            .limit(limit)
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [
            {
                "id":              str(r.id),
                "event_id":        str(r.event_id) if r.event_id else None,
                "user_email":      r.user_email,
                "description":     r.description,
                "event_time":      r.event_time.isoformat() if r.event_time else None,
                "error":           r.error,
                "retry_count":     r.retry_count,
                "resolved":        r.resolved,
                "created_at":      r.created_at.isoformat() if r.created_at else None,
                "last_retried_at": r.last_retried_at.isoformat() if r.last_retried_at else None,
            }
            for r in rows
        ]


async def mark_dlq_retried(dlq_id: str, *, resolved: bool) -> dict | None:
    async with get_session() as session:
        row = await session.get(ReminderDeadLetter, uuid.UUID(dlq_id))
        if row is None:
            return None
        row.retry_count = (row.retry_count or 0) + 1
        row.last_retried_at = datetime.now(timezone.utc)
        if resolved:
            row.resolved = True
        await session.commit()
        return {
            "id":          str(row.id),
            "retry_count": row.retry_count,
            "resolved":    row.resolved,
        }
