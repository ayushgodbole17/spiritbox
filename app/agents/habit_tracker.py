"""
Habit Tracker Agent — Phase 9.

Receives a journal entry + the user's existing habits, calls the LLM to
identify matches and new candidates, then:
  - inserts new habits (deduped by name, case-insensitive, per user)
  - writes a HabitLog for each matched habit tied to this entry
  - updates streak_days based on cadence window (daily=1d, weekly=7d,
    occasional=30d). If last_logged_at is within the window, increment;
    otherwise reset to 1.

Kept best-effort: any failure logs and returns state unchanged so the pipeline
never fails because of habits.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from langfuse import observe
from pydantic import ValidationError
from sqlalchemy import select

from app.agents.graph import EntryState
from app.agents.schemas import HabitExtractionResult
from app.db.models import Habit, HabitLog
from app.db.session import get_session
from app.llm.guardrails import validate_llm_output
from app.llm.router import chat_completion, TIER_1
from app.prompts.habit_tracker import SYSTEM as HABIT_SYSTEM, USER_TEMPLATE as HABIT_USER

logger = logging.getLogger(__name__)

_CADENCE_WINDOW = {
    "daily": timedelta(days=2),       # 2-day grace for daily habits
    "weekly": timedelta(days=10),     # 10-day grace for weekly
    "occasional": timedelta(days=45), # 45-day grace for occasional
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _window(cadence: str) -> timedelta:
    return _CADENCE_WINDOW.get((cadence or "occasional").lower(), _CADENCE_WINDOW["occasional"])


async def _fetch_user_habits(user_id: str) -> list[Habit]:
    async with get_session() as session:
        rows = await session.execute(select(Habit).where(Habit.user_id == user_id))
        return list(rows.scalars().all())


@observe()
async def track_habits(state: EntryState) -> EntryState:
    """
    Pipeline node: extract habit activity from the entry and persist it.

    Always returns state (best-effort). Adds `habits` = {matched, new} to state
    for observability.
    """
    raw_text = state["raw_text"]
    user_id = state.get("user_id") or "default"
    entry_id = state.get("entry_id") or ""

    try:
        habits = await _fetch_user_habits(user_id)
    except Exception as exc:
        logger.warning(f"[habit_tracker] fetch habits failed: {exc}")
        return {**state, "habits": {"matched": [], "new": []}}

    existing_desc = (
        json.dumps([
            {"id": str(h.id), "name": h.name, "category": h.category, "cadence": h.cadence}
            for h in habits
        ])
        if habits else "[]"
    )

    try:
        messages = [
            {"role": "system", "content": HABIT_SYSTEM},
            {"role": "user", "content": HABIT_USER.format(
                transcript=raw_text, existing_habits=existing_desc
            )},
        ]
        response, _model = await chat_completion(
            tier=TIER_1,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw = response.choices[0].message.content or "{}"
        result = await validate_llm_output(raw, HabitExtractionResult)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning(f"[habit_tracker] output validation failed: {exc}. Skipping.")
        return {**state, "habits": {"matched": [], "new": []}}
    except Exception as exc:
        logger.warning(f"[habit_tracker] LLM call failed: {exc!r}. Skipping.")
        return {**state, "habits": {"matched": [], "new": []}}

    matched_ids: list[str] = []
    new_names: list[str] = []

    try:
        async with get_session() as session:
            # Re-fetch inside the write transaction so we can update streaks
            habit_by_id: dict[str, Habit] = {}
            rows = await session.execute(select(Habit).where(Habit.user_id == user_id))
            for h in rows.scalars().all():
                habit_by_id[str(h.id)] = h

            existing_names_lc = {h.name.lower(): h for h in habit_by_id.values()}
            now = _now()

            # --- Update existing matched habits ---
            for hid in result.matched:
                habit = habit_by_id.get(hid)
                if habit is None:
                    continue
                within = (
                    habit.last_logged_at is not None
                    and now - habit.last_logged_at <= _window(habit.cadence or "occasional")
                )
                habit.streak_days = (habit.streak_days or 0) + 1 if within else 1
                habit.last_logged_at = now
                log = HabitLog(
                    id=uuid.uuid4(),
                    habit_id=habit.id,
                    entry_id=uuid.UUID(entry_id) if entry_id else None,
                    logged_at=now,
                )
                session.add(log)
                matched_ids.append(str(habit.id))

            # --- Insert new candidates (dedupe by lowercase name) ---
            for cand in result.new_candidates:
                key = cand.name.strip().lower()
                if not key or key in existing_names_lc:
                    continue
                new_habit = Habit(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    name=cand.name.strip(),
                    category=cand.category,
                    cadence=cand.cadence,
                    streak_days=1,
                    last_logged_at=now,
                )
                session.add(new_habit)
                existing_names_lc[key] = new_habit
                new_names.append(new_habit.name)
                session.add(HabitLog(
                    id=uuid.uuid4(),
                    habit_id=new_habit.id,
                    entry_id=uuid.UUID(entry_id) if entry_id else None,
                    logged_at=now,
                ))

            await session.commit()
    except Exception as exc:
        logger.warning(f"[habit_tracker] persist failed: {exc!r}")
        return {**state, "habits": {"matched": [], "new": []}}

    logger.info(f"[habit_tracker] matched={len(matched_ids)} new={len(new_names)} user={user_id}")
    return {**state, "habits": {"matched": matched_ids, "new": new_names}}
