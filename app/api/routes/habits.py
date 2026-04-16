"""
Habits read-only API — lists tracked habits + recent logs per user.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.deps import get_current_user
from app.db.models import Habit, HabitLog
from app.db.session import get_session

router = APIRouter()


def _serialize_habit(h: Habit) -> dict:
    return {
        "id": str(h.id),
        "name": h.name,
        "category": h.category,
        "cadence": h.cadence,
        "streak_days": h.streak_days or 0,
        "last_logged_at": h.last_logged_at.isoformat() if h.last_logged_at else None,
        "created_at": h.created_at.isoformat() if h.created_at else None,
    }


@router.get("", summary="List the user's tracked habits")
async def list_habits(user_id: str = Depends(get_current_user)) -> dict:
    async with get_session() as session:
        rows = await session.execute(
            select(Habit).where(Habit.user_id == user_id).order_by(Habit.last_logged_at.desc().nullslast())
        )
        habits = [_serialize_habit(h) for h in rows.scalars().all()]
    return {"habits": habits, "count": len(habits)}


@router.get("/{habit_id}", summary="Habit detail + recent logs")
async def habit_detail(habit_id: str, user_id: str = Depends(get_current_user)) -> dict:
    async with get_session() as session:
        row = await session.execute(
            select(Habit).where(Habit.id == habit_id, Habit.user_id == user_id)
        )
        habit = row.scalar_one_or_none()
        if habit is None:
            raise HTTPException(status_code=404, detail="habit not found")

        log_rows = await session.execute(
            select(HabitLog).where(HabitLog.habit_id == habit.id)
            .order_by(HabitLog.logged_at.desc()).limit(30)
        )
        logs = [
            {
                "id": str(l.id),
                "entry_id": str(l.entry_id) if l.entry_id else None,
                "logged_at": l.logged_at.isoformat() if l.logged_at else None,
            }
            for l in log_rows.scalars().all()
        ]

    return {"habit": _serialize_habit(habit), "logs": logs}
