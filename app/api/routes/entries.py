import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


class UpdateEntryRequest(BaseModel):
    raw_text: str


class SearchResponse(BaseModel):
    results: list[dict[str, Any]]
    query: str


@router.get("", summary="List recent journal entries")
async def get_entries(
    limit: int = Query(20, ge=1, le=100),
    user_id: str = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Returns recent journal entries for the authenticated user, newest first."""
    try:
        from app.db.crud import list_entries
        return await list_entries(user_id=user_id, limit=limit)
    except Exception as e:
        logger.error(f"Failed to list entries: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list entries: {e}")


@router.get("/search", summary="Search over journal entries")
async def search_entries(
    q: str = Query(..., description="Natural language search query"),
    limit: int = Query(5, ge=1, le=20),
    mode: str = Query("hybrid", description="Search mode: semantic, keyword, or hybrid"),
    user_id: str = Depends(get_current_user),
) -> SearchResponse:
    """Search the authenticated user's entries via semantic, keyword, or hybrid (RRF) search."""
    try:
        if mode == "keyword":
            from app.memory.vector_store import keyword_search
            results = await keyword_search(query=q, limit=limit, user_id=user_id)
        elif mode == "semantic":
            from app.memory.vector_store import semantic_search
            results = await semantic_search(query=q, limit=limit, user_id=user_id)
        else:
            from app.memory.vector_store import hybrid_search
            results = await hybrid_search(query=q, limit=limit, user_id=user_id)
        return SearchResponse(results=results, query=q)
    except Exception as e:
        logger.error(f"Search failed (mode={mode}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Search failed: {e}")


@router.get("/{entry_id}", summary="Get a single journal entry by ID")
async def get_entry_by_id(
    entry_id: str,
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        from app.db.crud import get_entry
        entry = await get_entry(entry_id, user_id=user_id)
    except Exception as e:
        logger.error(f"Failed to fetch entry {entry_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Fetch failed: {e}")
    if not entry:
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found")
    return entry


@router.patch("/{entry_id}", summary="Update a journal entry's text")
async def update_entry_by_id(
    entry_id: str,
    body: UpdateEntryRequest,
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        from app.db.crud import update_entry as pg_update
        from app.memory.vector_store import update_entry as vs_update
        found = await pg_update(entry_id, user_id=user_id, raw_text=body.raw_text)
        if not found:
            raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found")
        try:
            await vs_update(entry_id, body.raw_text)
        except Exception as e:
            logger.warning(f"pgvector update failed for {entry_id} (non-fatal): {e}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update entry {entry_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Update failed: {e}")
    return {"entry_id": entry_id, "raw_text": body.raw_text}


@router.delete("/{entry_id}", status_code=204, summary="Delete a journal entry")
async def delete_entry_by_id(
    entry_id: str,
    user_id: str = Depends(get_current_user),
) -> None:
    try:
        from app.db.crud import delete_entry as pg_delete
        from app.memory.vector_store import delete_entry as vs_delete
        found = await pg_delete(entry_id, user_id=user_id)
        if not found:
            raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found")
        try:
            await vs_delete(entry_id)
        except Exception as e:
            logger.warning(f"pgvector delete failed for {entry_id} (non-fatal): {e}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete entry {entry_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Delete failed: {e}")
