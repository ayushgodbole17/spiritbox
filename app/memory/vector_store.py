"""
pgvector-based vector store — replaces Weaviate.

Uses the existing Cloud SQL PostgreSQL instance with the pgvector extension.
Embeddings are generated via OpenAI text-embedding-3-small (1536 dims).

Same public interface as the old Weaviate module:
  - init_schema()         — enables pgvector extension + creates table
  - upsert_entry(entry)   — embed + insert/update
  - semantic_search(...)  — cosine similarity search
  - get_entry(entry_id)   — fetch by UUID
  - update_entry(...)     — update raw_text
  - delete_entry(...)     — delete by UUID
  - list_entries(limit)   — paginated listing
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text

from app.config import settings
from app.db.session import engine, get_session

logger = logging.getLogger(__name__)

_EMBED_MODEL = "text-embedding-3-small"
_EMBED_DIMS  = 1536


# ---------------------------------------------------------------------------
# Embedding helper
# ---------------------------------------------------------------------------

async def _embed(text_input: str) -> list[float]:
    """Generate an embedding vector using OpenAI."""
    from openai import AsyncOpenAI
    from app.llm.token_tracker import record_embedding_usage
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    resp = await client.embeddings.create(model=_EMBED_MODEL, input=text_input[:8000])
    if resp.usage:
        record_embedding_usage(_EMBED_MODEL, resp.usage.total_tokens)
    return resp.data[0].embedding


# ---------------------------------------------------------------------------
# Schema init
# ---------------------------------------------------------------------------

async def init_schema() -> None:
    """
    Enable pgvector extension and create entry_embeddings table if absent.
    Each DDL runs in its own transaction so one failure doesn't roll back
    previously-successful statements.
    """
    steps = [
        ("vector extension", "CREATE EXTENSION IF NOT EXISTS vector"),
        ("entry_embeddings table", f"""
            CREATE TABLE IF NOT EXISTS entry_embeddings (
                entry_id    UUID PRIMARY KEY,
                user_id     TEXT NOT NULL DEFAULT 'default',
                raw_text    TEXT,
                summary     TEXT,
                categories  TEXT[],
                sentence_tags TEXT,
                entry_date  TIMESTAMPTZ DEFAULT NOW(),
                embedding   vector({_EMBED_DIMS})
            )
        """),
        ("ivfflat index", """
            CREATE INDEX IF NOT EXISTS entry_embeddings_ivfflat_idx
            ON entry_embeddings
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
        """),
        ("fts generated column", """
            ALTER TABLE entry_embeddings
            ADD COLUMN IF NOT EXISTS fts tsvector
            GENERATED ALWAYS AS (
                to_tsvector('english', coalesce(raw_text, '') || ' ' || coalesce(summary, ''))
            ) STORED
        """),
        ("fts GIN index", """
            CREATE INDEX IF NOT EXISTS entry_embeddings_fts_idx
            ON entry_embeddings USING gin (fts)
        """),
    ]
    for label, ddl in steps:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(ddl))
            logger.info(f"pgvector init: {label} ok")
        except Exception as exc:
            logger.warning(f"pgvector init: {label} failed (continuing): {exc}")


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

async def upsert_entry(entry: dict) -> str:
    """
    Embed the entry text and upsert into entry_embeddings.
    Returns the entry_id UUID string.
    """
    entry_id = entry.get("entry_id") or str(uuid.uuid4())
    raw_text  = entry.get("raw_text", "")
    summary   = entry.get("summary", "")

    # Embed summary if available, else raw text
    embed_text = summary if summary else raw_text
    try:
        vector = await _embed(embed_text)
    except Exception as exc:
        logger.warning(f"[vector_store] embedding failed: {exc}. Skipping upsert.")
        raise

    categories    = entry.get("categories", [])
    sentence_tags = entry.get("sentence_tags", "")
    if isinstance(sentence_tags, (list, dict)):
        sentence_tags = json.dumps(sentence_tags)
    user_id = entry.get("user_id", "default")

    async with get_session() as session:
        await session.execute(text("""
            INSERT INTO entry_embeddings
                (entry_id, user_id, raw_text, summary, categories, sentence_tags, entry_date, embedding)
            VALUES
                (:entry_id, :user_id, :raw_text, :summary, :categories, :sentence_tags, :entry_date, :embedding)
            ON CONFLICT (entry_id) DO UPDATE SET
                raw_text      = EXCLUDED.raw_text,
                summary       = EXCLUDED.summary,
                categories    = EXCLUDED.categories,
                sentence_tags = EXCLUDED.sentence_tags,
                embedding     = EXCLUDED.embedding
        """), {
            "entry_id":     entry_id,
            "user_id":      user_id,
            "raw_text":     raw_text,
            "summary":      summary,
            "categories":   categories,
            "sentence_tags": sentence_tags,
            "entry_date":   datetime.now(timezone.utc),
            "embedding":    str(vector),
        })
        await session.commit()

    logger.debug(f"[vector_store] upserted {entry_id}")
    return entry_id


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

async def semantic_search(query: str, limit: int = 5, user_id: str | None = None) -> list[dict[str, Any]]:
    """
    Cosine similarity search over entry_embeddings.

    Args:
        query:   Natural language search string.
        limit:   Max results.
        user_id: If set, filter to this user's entries only.

    Returns:
        List of entry dicts with a 'score' field (1 = identical, 0 = unrelated).
    """
    vector = await _embed(query)

    filter_clause = "WHERE user_id = :user_id" if user_id else ""
    params: dict = {"embedding": str(vector), "limit": limit}
    if user_id:
        params["user_id"] = user_id

    async with get_session() as session:
        rows = await session.execute(text(f"""
            SELECT
                entry_id::text,
                user_id,
                raw_text,
                summary,
                categories,
                sentence_tags,
                entry_date,
                1 - (embedding <=> :embedding::vector) AS score
            FROM entry_embeddings
            {filter_clause}
            ORDER BY embedding <=> :embedding::vector
            LIMIT :limit
        """), params)
        results = []
        for row in rows.mappings():
            item = dict(row)
            item["entry_date"] = item["entry_date"].isoformat() if item["entry_date"] else ""
            results.append(item)
        return results


async def keyword_search(query: str, limit: int = 5, user_id: str | None = None) -> list[dict[str, Any]]:
    """
    Full-text keyword search using PostgreSQL tsvector/GIN index.

    Args:
        query:   Natural language search string.
        limit:   Max results.
        user_id: If set, filter to this user's entries only.

    Returns:
        List of entry dicts with a 'score' field (ts_rank).
    """
    filter_clause = "AND user_id = :user_id" if user_id else ""
    params: dict = {"query": query, "limit": limit}
    if user_id:
        params["user_id"] = user_id

    async with get_session() as session:
        rows = await session.execute(text(f"""
            SELECT
                entry_id::text,
                user_id,
                raw_text,
                summary,
                categories,
                sentence_tags,
                entry_date,
                ts_rank(fts, websearch_to_tsquery('english', :query)) AS score
            FROM entry_embeddings
            WHERE fts @@ websearch_to_tsquery('english', :query)
            {filter_clause}
            ORDER BY score DESC
            LIMIT :limit
        """), params)
        results = []
        for row in rows.mappings():
            item = dict(row)
            item["entry_date"] = item["entry_date"].isoformat() if item["entry_date"] else ""
            results.append(item)
        return results


async def hybrid_search(
    query: str,
    limit: int = 5,
    user_id: str | None = None,
    k: int = 60,
) -> list[dict[str, Any]]:
    """
    Hybrid search combining semantic (pgvector cosine) and keyword (tsvector)
    results via Reciprocal Rank Fusion (RRF).

    RRF score = 1/(k + rank_semantic) + 1/(k + rank_keyword)
    where k=60 is the standard smoothing constant (Cormack et al.).

    Args:
        query:   Natural language search string.
        limit:   Max results to return after fusion.
        user_id: If set, filter to this user's entries only.
        k:       RRF smoothing constant.

    Returns:
        List of entry dicts with a fused 'score' field, best first.
    """
    import asyncio

    sem_task = asyncio.create_task(semantic_search(query, limit=limit * 2, user_id=user_id))
    kw_task = asyncio.create_task(keyword_search(query, limit=limit * 2, user_id=user_id))
    sem_raw, kw_raw = await asyncio.gather(sem_task, kw_task, return_exceptions=True)

    if isinstance(sem_raw, Exception):
        logger.warning(f"[hybrid_search] semantic leg failed: {sem_raw}")
        sem_results: list[dict[str, Any]] = []
    else:
        sem_results = sem_raw
    if isinstance(kw_raw, Exception):
        logger.warning(f"[hybrid_search] keyword leg failed: {kw_raw}")
        kw_results: list[dict[str, Any]] = []
    else:
        kw_results = kw_raw

    if not sem_results and not kw_results:
        if isinstance(sem_raw, Exception) and isinstance(kw_raw, Exception):
            raise RuntimeError(f"both search legs failed: semantic={sem_raw}; keyword={kw_raw}")
        logger.info(f"[hybrid_search] zero matches for query={query!r}")
        return []

    logger.info(f"[hybrid_search] semantic={len(sem_results)} keyword={len(kw_results)}")

    # Build RRF scores
    rrf_scores: dict[str, float] = {}
    entry_map: dict[str, dict] = {}

    for rank, entry in enumerate(sem_results):
        eid = entry["entry_id"]
        rrf_scores[eid] = rrf_scores.get(eid, 0) + 1.0 / (k + rank + 1)
        entry_map[eid] = entry

    for rank, entry in enumerate(kw_results):
        eid = entry["entry_id"]
        rrf_scores[eid] = rrf_scores.get(eid, 0) + 1.0 / (k + rank + 1)
        entry_map[eid] = entry

    # Sort by fused score descending
    ranked = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:limit]

    results = []
    for eid, score in ranked:
        entry = entry_map[eid]
        entry["score"] = round(score, 6)
        results.append(entry)

    logger.info(f"[hybrid_search] fused={len(results)}")
    return results


async def get_entry(entry_id: str) -> Optional[dict[str, Any]]:
    """Fetch a single entry by UUID. Returns None if not found."""
    async with get_session() as session:
        rows = await session.execute(text("""
            SELECT entry_id::text, user_id, raw_text, summary, categories,
                   sentence_tags, entry_date
            FROM entry_embeddings WHERE entry_id = :entry_id
        """), {"entry_id": entry_id})
        row = rows.mappings().first()
        if row is None:
            return None
        item = dict(row)
        item["entry_date"] = item["entry_date"].isoformat() if item["entry_date"] else ""
        return item


async def update_entry(entry_id: str, raw_text: str) -> bool:
    """Update raw_text and re-embed. Returns True if the entry existed."""
    existing = await get_entry(entry_id)
    if existing is None:
        return False
    existing["raw_text"] = raw_text
    await upsert_entry(existing)
    return True


async def delete_entry(entry_id: str) -> bool:
    """Delete an entry by UUID. Returns True if deleted."""
    async with get_session() as session:
        result = await session.execute(text("""
            DELETE FROM entry_embeddings WHERE entry_id = :entry_id
        """), {"entry_id": entry_id})
        await session.commit()
        return result.rowcount > 0


async def list_entries(limit: int = 20) -> list[dict[str, Any]]:
    """Return recent entries newest-first."""
    async with get_session() as session:
        rows = await session.execute(text("""
            SELECT entry_id::text, user_id, raw_text, summary, categories,
                   sentence_tags, entry_date
            FROM entry_embeddings
            ORDER BY entry_date DESC
            LIMIT :limit
        """), {"limit": limit})
        results = []
        for row in rows.mappings():
            item = dict(row)
            item["entry_date"] = item["entry_date"].isoformat() if item["entry_date"] else ""
            results.append(item)
        return results


# ---------------------------------------------------------------------------
# Backfill — populate entry_embeddings from the entries table
# ---------------------------------------------------------------------------

async def backfill_from_entries() -> int:
    """
    Read all entries from PostgreSQL that are missing from entry_embeddings
    and create embeddings for them. Returns the number of entries backfilled.
    """
    from sqlalchemy import text as sa_text

    async with get_session() as session:
        rows = await session.execute(sa_text("""
            SELECT e.id::text AS entry_id, e.user_id, e.raw_text, e.summary
            FROM entries e
            LEFT JOIN entry_embeddings ee ON ee.entry_id = e.id
            WHERE ee.entry_id IS NULL
            ORDER BY e.created_at ASC
        """))
        missing = rows.mappings().all()

    count = 0
    for row in missing:
        try:
            await upsert_entry({
                "entry_id": row["entry_id"],
                "raw_text": row["raw_text"] or "",
                "summary": row["summary"] or "",
                "categories": [],
                "sentence_tags": "[]",
                "user_id": row["user_id"] or "default",
            })
            count += 1
            logger.info(f"[backfill] embedded entry {row['entry_id']}")
        except Exception as exc:
            logger.warning(f"[backfill] failed for {row['entry_id']}: {exc}")

    logger.info(f"[backfill] complete: {count} entries embedded.")
    return count
