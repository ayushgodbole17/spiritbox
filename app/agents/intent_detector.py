"""
Intent Detector Agent — Phase 2.

Uses GPT-4o to determine which extracted entities (especially events with
datetimes) should trigger reminder emails.

After detecting events this agent:
  1. Saves each event to Firestore via app/events/firestore.save_event()
  2. Creates a Cloud Scheduler job via app/scheduler/create_job.create_reminder_job()
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from langfuse import observe
from pydantic import ValidationError

from app.agents.graph import EntryState
from app.agents.reminder_timing import compute_reminder_time
from app.agents.schemas import ReminderResult
from app.config import settings
from app.llm.guardrails import validate_llm_output
from app.llm.router import chat_completion, TIER_2
from app.llm.cache import get_cached, set_cached
from app.prompts.detect_intent import SYSTEM as INTENT_SYSTEM, USER_TEMPLATE as INTENT_USER
from app.prompts.loader import get_messages

logger = logging.getLogger(__name__)


def _parse_iso8601(dt_string: str) -> Optional[datetime]:
    """
    Attempt to parse an ISO8601 datetime string.

    Returns a UTC-aware datetime, or None if unparseable.
    """
    if not dt_string:
        return None
    # Try Python's fromisoformat (handles offsets in 3.11+)
    try:
        dt = datetime.fromisoformat(dt_string)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass
    # Fallback: strip trailing Z and try again
    try:
        dt = datetime.fromisoformat(dt_string.rstrip("Z"))
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    return None


@observe()
async def detect_intents(state: EntryState) -> EntryState:
    """
    Detect schedulable events from the extracted entities and create reminders.

    Calls GPT-4o with the entities JSON, parses the reminder list, saves each
    event to Firestore, and schedules a Cloud Scheduler job for each reminder.

    Args:
        state: Current EntryState with 'entities' populated.

    Returns:
        Updated EntryState with 'events' merged with detected reminders.
    """
    from app.events.firestore import save_event
    from app.scheduler.create_job import create_reminder_job

    _NAMESPACE = "intent_detector"
    current_datetime = datetime.now(timezone.utc).isoformat()
    entities_json = json.dumps(state.get("entities", {}), ensure_ascii=False)
    cache_key = entities_json  # cache on entities, not raw text

    # --- Cache lookup ---
    cached_reminders = await get_cached(cache_key, namespace=_NAMESPACE)

    if cached_reminders is not None:
        logger.debug("[intent_detector] cache hit")
        reminders = cached_reminders
        model_name = "cache"
        prompt_version = "cache"
        cache_hit = True
    else:
        try:
            messages, prompt_version = get_messages(
                name="spiritbox.detect_intent.v1",
                fallback=[
                    {"role": "system", "content": INTENT_SYSTEM},
                    {"role": "user",   "content": INTENT_USER},
                ],
                variables={
                    "current_datetime": current_datetime,
                    "timezone":         settings.USER_TIMEZONE,
                    "entities_json":    entities_json,
                },
            )
            response, model_name = await chat_completion(
                tier=TIER_2,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0,
            )
            raw = response.choices[0].message.content or "{}"

            # Normalise: wrap bare arrays in {"reminders": [...]}
            try:
                pre = json.loads(raw)
            except json.JSONDecodeError:
                pre = {}
            if isinstance(pre, list):
                raw = json.dumps({"reminders": pre})

            validated = await validate_llm_output(raw, ReminderResult)
            reminders = [r.model_dump() for r in validated.reminders]

            await set_cached(cache_key, reminders, namespace=_NAMESPACE)
            cache_hit = False

        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning(f"[intent_detector] output validation failed: {exc}. No reminders scheduled.")
            reminders = []
            model_name = "error"
            prompt_version = "error"
            cache_hit = False
        except Exception as exc:
            logger.error(f"[intent_detector] unexpected error: {exc}", exc_info=True)
            reminders = []
            model_name = "error"
            prompt_version = "error"
            cache_hit = False

    processed_events = []
    for reminder in reminders:
        if not isinstance(reminder, dict):
            continue

        event_time_str = reminder.get("event_time", "")
        reminder_time_str = reminder.get("reminder_time", "")
        granularity = reminder.get("granularity", "time")
        description = reminder.get("event_description", "")
        channel = reminder.get("channel", "email")

        event_time, reminder_time = compute_reminder_time(
            event_time_str=event_time_str,
            proposed_reminder_str=reminder_time_str,
            granularity=granularity,
            timezone_name=settings.USER_TIMEZONE,
        )

        if event_time is None or reminder_time is None:
            logger.warning(
                f"[intent_detector] Skipping reminder (unparseable or in past): {reminder}"
            )
            continue

        reminder_time_str = reminder_time.isoformat()
        event_time_str = event_time.isoformat()

        # Persist to PostgreSQL (authoritative source for reminders)
        pg_event_id: str | None = None
        try:
            from app.db.crud import save_event as pg_save_event
            pg_event_id = await pg_save_event(
                entry_id=state.get("entry_id", ""),
                description=description,
                event_time=event_time,
                reminder_time=reminder_time,
            )
            logger.info(f"[intent_detector] Saved event to PostgreSQL: {pg_event_id}")
        except Exception as exc:
            logger.warning(f"[intent_detector] PostgreSQL event save failed: {exc}")
            pg_event_id = uuid.uuid4().hex[:8]

        # Persist to Firestore (best-effort — Cloud Function webhook may depend on it)
        firestore_id: str | None = None
        try:
            event_doc = {
                "description": description,
                "event_time": event_time,
                "reminder_time": reminder_time,
                "user_email": settings.USER_EMAIL,
                "channel": channel,
            }
            firestore_id = await save_event(event_doc)
        except Exception as exc:
            logger.debug(f"[intent_detector] Firestore save skipped: {exc}")

        # Schedule reminder job (best-effort)
        job_name = f"reminder-{pg_event_id}"
        try:
            await create_reminder_job(
                job_name=job_name,
                schedule_time=reminder_time,
                payload={
                    "event_description": description,
                    "event_time": event_time_str,
                    "user_email": settings.USER_EMAIL,
                    "pg_event_id": pg_event_id,
                    "firestore_id": firestore_id,
                },
            )
        except Exception as exc:
            logger.warning(f"[intent_detector] Scheduler job creation failed: {exc}")

        processed_events.append({
            "event_description": description,
            "event_time": event_time_str,
            "reminder_time": reminder_time_str,
            "channel": channel,
            "pg_event_id": pg_event_id,
            "firestore_id": firestore_id,
            "job_name": job_name,
        })

    # Merge with entity-extracted events from earlier in the pipeline
    merged_events = list(state.get("events", [])) + processed_events
    logger.debug(
        f"[intent_detector] {len(processed_events)} reminders scheduled; "
        f"{len(merged_events)} total events."
    )
    return {
        **state,
        "events": merged_events,
        "model_used": {**state.get("model_used", {}), _NAMESPACE: model_name},
        "cache_hits": {**state.get("cache_hits", {}), _NAMESPACE: cache_hit},
        "prompt_versions": {**state.get("prompt_versions", {}), _NAMESPACE: prompt_version},
    }


@observe()
async def detect(text: str) -> list:
    """
    Backward-compatible wrapper: detect intents from a raw text string.

    Returns a list of processed event dicts, or an empty list on failure.
    Note: this wrapper does NOT have access to pre-extracted entities, so it
    passes an empty entities dict to the LLM — use detect_intents(state)
    directly for the full pipeline.
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
    result = await detect_intents(state)
    # Return only the newly detected events (not pre-existing ones)
    return result["events"]
