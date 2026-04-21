import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.db.crud import list_upcoming_events

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", summary="List upcoming reminders")
async def get_reminders(
    limit: int = Query(10, ge=1, le=50, description="Maximum number of upcoming reminders"),
    user_id: str = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """
    Returns upcoming events for the authenticated user that have not yet been reminded.
    Sourced from PostgreSQL and sorted by reminder_time ascending.
    """
    try:
        return await list_upcoming_events(user_id=user_id, limit=limit)
    except Exception as e:
        logger.error(f"Failed to list reminders: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list reminders: {e}")
