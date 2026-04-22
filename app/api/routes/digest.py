"""
Weekly Digest — GET /api/digest/weekly

Assembles the user-facing weekly insights page: the most recent
`theme_rollups` row, habit streak info, and a light mood signal from
`sentence_tags`. Also exposes an admin-triggered rollup endpoint.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text

from app.api.deps import get_current_user
from app.db.models import Entry, Habit, SentenceTag, ThemeRollup
from app.db.session import get_session

logger = logging.getLogger(__name__)

router = APIRouter()

_POSITIVE = {"gratitude", "joy", "achievement", "progress", "hope"}
_NEGATIVE = {"anxiety", "stress", "anger", "sadness", "frustration"}


@router.get("/weekly", summary="Assemble the weekly insights digest")
async def weekly_digest(user_id: str = Depends(get_current_user)) -> dict:
    """Return the latest theme rollup + habit streaks + mood signal + top entries."""
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    async with get_session() as session:
        # --- Latest rollup ---
        rollup_row = (await session.execute(
            select(ThemeRollup)
            .where(ThemeRollup.user_id == user_id)
            .order_by(ThemeRollup.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()

        rollup: dict | None = None
        if rollup_row is not None:
            rollup = {
                "id":          str(rollup_row.id),
                "week_start":  rollup_row.week_start.isoformat() if rollup_row.week_start else None,
                "themes":      rollup_row.themes or [],
                "entry_count": rollup_row.entry_count or 0,
                "created_at":  rollup_row.created_at.isoformat() if rollup_row.created_at else None,
            }

        # --- Habit streaks (snapshot) ---
        habit_rows = (await session.execute(
            select(Habit)
            .where(Habit.user_id == user_id)
            .order_by(Habit.streak_days.desc().nullslast())
            .limit(10)
        )).scalars().all()
        habits = [
            {
                "name":           h.name,
                "category":       h.category,
                "cadence":        h.cadence,
                "streak_days":    h.streak_days or 0,
                "last_logged_at": h.last_logged_at.isoformat() if h.last_logged_at else None,
            }
            for h in habit_rows
        ]

        # --- Mood signal: ratio of positive vs negative category tags this week ---
        tag_rows = (await session.execute(
            text("""
                SELECT UNNEST(st.categories) AS cat, COUNT(*) AS cnt
                  FROM sentence_tags st
                  JOIN entries e ON e.id = st.entry_id
                 WHERE e.user_id = :user_id AND e.created_at >= :since
              GROUP BY UNNEST(st.categories)
            """),
            {"user_id": user_id, "since": week_ago},
        )).mappings().all()

        positives = sum(r["cnt"] for r in tag_rows if r["cat"] in _POSITIVE)
        negatives = sum(r["cnt"] for r in tag_rows if r["cat"] in _NEGATIVE)
        total = positives + negatives
        mood = {
            "positive": positives,
            "negative": negatives,
            "score": round((positives - negatives) / total, 3) if total else None,
        }

        # --- Top 3 entries by raw_text length over the last week ---
        entry_rows = (await session.execute(
            select(Entry)
            .where(Entry.user_id == user_id, Entry.created_at >= week_ago)
            .order_by(func.char_length(Entry.raw_text).desc())
            .limit(3)
        )).scalars().all()
        top_entries = [
            {
                "id":         str(e.id),
                "summary":    e.summary or (e.raw_text or "")[:200],
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entry_rows
        ]

        entry_count = (await session.execute(
            select(func.count()).select_from(Entry)
            .where(Entry.user_id == user_id, Entry.created_at >= week_ago)
        )).scalar() or 0

    return {
        "generated_at": now.isoformat(),
        "week_start":   week_ago.isoformat(),
        "entry_count":  entry_count,
        "rollup":       rollup,
        "habits":       habits,
        "mood":         mood,
        "top_entries":  top_entries,
    }


@router.post(
    "/weekly/run",
    summary="Trigger the weekly theme rollup for the current user",
)
async def trigger_weekly_rollup_for_self(
    user_id: str = Depends(get_current_user),
) -> dict:
    """Manual trigger — kicks the summarizer for the authenticated user only."""
    from app.agents.theme_summarizer import run_weekly_rollup
    try:
        result = await run_weekly_rollup(user_id)
    except Exception as exc:
        logger.error(f"[digest] weekly rollup failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "ok", "result": result}
