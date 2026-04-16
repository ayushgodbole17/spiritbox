"""
Admin dashboard API — protected by HTTP Basic Auth.

Endpoints:
  GET  /admin/evals          — latest eval results from evals/results_latest.json
  POST /admin/evals/run      — trigger a live eval run (background task)
  GET  /admin/metrics        — recent LangFuse traces + aggregate stats
  GET  /admin/cache          — semantic cache stats
  GET  /admin/status         — combined system status summary
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import func, select

from app.config import settings

router = APIRouter()
security = HTTPBasic()

RESULTS_PATH    = Path(__file__).parent.parent.parent.parent / "evals" / "results_latest.json"
CHANGELOG_PATH  = Path(__file__).parent.parent.parent.parent / "CHANGELOG.json"


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

def require_admin(credentials: HTTPBasicCredentials = Depends(security)):
    ok_user = secrets.compare_digest(credentials.username.encode(), settings.ADMIN_USERNAME.encode())
    ok_pass = secrets.compare_digest(credentials.password.encode(), settings.ADMIN_PASSWORD.encode())
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# ---------------------------------------------------------------------------
# Evals
# ---------------------------------------------------------------------------

@router.get("/evals")
def get_evals(_: str = Depends(require_admin)) -> dict:
    """Return the latest eval results, or a placeholder if not yet run."""
    if not RESULTS_PATH.exists():
        return {"status": "not_run", "message": "Run `python evals/run_evals.py` to generate results."}
    with open(RESULTS_PATH) as f:
        return json.load(f)


def _run_evals_task():
    """Background task: run the eval script in-process."""
    import asyncio
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
    from evals.run_evals import run
    asyncio.run(run())


@router.post("/evals/run", status_code=202)
def trigger_evals(
    background_tasks: BackgroundTasks,
    _: str = Depends(require_admin),
) -> dict:
    """Trigger an eval run in the background. Poll GET /admin/evals for results."""
    background_tasks.add_task(_run_evals_task)
    return {"status": "started", "message": "Eval run started. Poll /admin/evals for results."}


# ---------------------------------------------------------------------------
# LangFuse metrics
# ---------------------------------------------------------------------------

@router.get("/metrics")
def get_metrics(limit: int = 50, _: str = Depends(require_admin)) -> dict:
    """
    Fetch recent traces from LangFuse and return aggregate stats.

    Returns per-trace summaries and rollup metrics (total traces, avg latency,
    model usage breakdown, error rate).
    """
    if not settings.LANGFUSE_SECRET_KEY or not settings.LANGFUSE_PUBLIC_KEY:
        return {"status": "unavailable", "message": "LangFuse keys not configured."}

    try:
        from langfuse import Langfuse
        client = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST,
        )

        traces_response = client.fetch_traces(limit=limit)
        traces = traces_response.data if hasattr(traces_response, "data") else []

        trace_list = []
        total_latency_ms = 0
        error_count = 0
        model_counts: dict[str, int] = {}

        for t in traces:
            latency = None
            if hasattr(t, "latency") and t.latency is not None:
                latency = t.latency
                total_latency_ms += latency

            level = getattr(t, "level", None) or ""
            is_error = str(level).lower() in ("error", "warning")
            if is_error:
                error_count += 1

            # Tally model usage from metadata if present
            metadata = getattr(t, "metadata", {}) or {}
            for model in (metadata.get("model_used", {}) or {}).values():
                if model and model != "cache":
                    model_counts[model] = model_counts.get(model, 0) + 1

            trace_list.append({
                "id":         getattr(t, "id", ""),
                "name":       getattr(t, "name", ""),
                "timestamp":  str(getattr(t, "timestamp", "")),
                "latency_ms": latency,
                "level":      level,
                "input":      str(getattr(t, "input", ""))[:120] if getattr(t, "input", None) else None,
            })

        n = len(trace_list)
        return {
            "status": "ok",
            "langfuse_host": settings.LANGFUSE_HOST,
            "summary": {
                "total_traces":    n,
                "avg_latency_ms":  round(total_latency_ms / n, 1) if n else None,
                "error_count":     error_count,
                "error_rate":      round(error_count / n, 4) if n else 0,
                "model_usage":     model_counts,
            },
            "traces": trace_list,
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# Cache stats
# ---------------------------------------------------------------------------

@router.get("/cache")
def get_cache(_: str = Depends(require_admin)) -> dict:
    """Return current semantic cache stats."""
    from app.llm.cache import cache_stats
    return {"status": "ok", **cache_stats()}


# ---------------------------------------------------------------------------
# Combined status
# ---------------------------------------------------------------------------

@router.get("/releases")
def get_releases(_: str = Depends(require_admin)) -> list:
    """Return the CHANGELOG.json release history."""
    if not CHANGELOG_PATH.exists():
        return []
    with open(CHANGELOG_PATH) as f:
        return json.load(f)


@router.post("/releases")
def add_release(release: dict, _: str = Depends(require_admin)) -> dict:
    """
    Append a new release entry to CHANGELOG.json.

    Body: { version, date, type, title, changes: [{type, text}] }
    """
    releases = []
    if CHANGELOG_PATH.exists():
        with open(CHANGELOG_PATH) as f:
            releases = json.load(f)
    releases.insert(0, release)
    with open(CHANGELOG_PATH, "w") as f:
        json.dump(releases, f, indent=2)
    return release


@router.get("/analytics")
async def get_analytics(_: str = Depends(require_admin)) -> dict:
    """Return aggregate analytics from PostgreSQL: entry volumes, category distribution, model tiers, latest eval."""
    from app.db.models import Entry, SentenceTag, EvalRun
    from app.db.session import get_session

    try:
        async with get_session() as session:
            now = datetime.now(timezone.utc)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            week_start  = today_start - timedelta(days=today_start.weekday())
            month_ago   = now - timedelta(days=30)

            # --- Overview counts ---
            total_entries = (await session.execute(select(func.count()).select_from(Entry))).scalar() or 0
            entries_today = (await session.execute(
                select(func.count()).select_from(Entry).where(Entry.created_at >= today_start)
            )).scalar() or 0
            entries_week = (await session.execute(
                select(func.count()).select_from(Entry).where(Entry.created_at >= week_start)
            )).scalar() or 0

            cache_hits = (await session.execute(
                select(func.count()).select_from(Entry).where(Entry.cache_hit == True)  # noqa: E712
            )).scalar() or 0
            cache_hit_rate = round(cache_hits / total_entries, 4) if total_entries else 0.0

            tier1_calls = (await session.execute(
                select(func.count()).select_from(Entry).where(Entry.model_tier == "gpt-4o-mini")
            )).scalar() or 0
            tier2_calls = (await session.execute(
                select(func.count()).select_from(Entry).where(Entry.model_tier == "gpt-4o")
            )).scalar() or 0

            # --- Volume by day (last 30 days) ---
            vol_rows = (await session.execute(
                select(func.date(Entry.created_at).label("day"), func.count().label("cnt"))
                .where(Entry.created_at >= month_ago)
                .group_by(func.date(Entry.created_at))
                .order_by(func.date(Entry.created_at))
            )).all()
            volume_by_day = [{"date": str(r.day), "count": r.cnt} for r in vol_rows]

            # --- Model tier distribution ---
            tier_rows = (await session.execute(
                select(Entry.model_tier, func.count().label("cnt"))
                .group_by(Entry.model_tier)
            )).all()
            model_tier_dist: dict[str, int] = {}
            for r in tier_rows:
                label = r.model_tier or "unknown"
                model_tier_dist[label] = model_tier_dist.get(label, 0) + (r.cnt or 0)

            # --- Category distribution (unnest SentenceTag.categories array) ---
            cat_rows = (await session.execute(
                select(
                    func.unnest(SentenceTag.categories).label("cat"),
                    func.count().label("cnt"),
                )
                .group_by(func.unnest(SentenceTag.categories))
                .order_by(func.count().desc())
                .limit(10)
            )).all()
            total_cat = sum(r.cnt for r in cat_rows) or 1
            category_distribution = [
                {"category": r.cat, "count": r.cnt, "pct": round(r.cnt / total_cat * 100, 1)}
                for r in cat_rows
            ]

            # --- Latest eval run ---
            eval_row = (await session.execute(
                select(EvalRun).order_by(EvalRun.run_at.desc()).limit(1)
            )).scalar_one_or_none()
            recent_eval = None
            if eval_row:
                recent_eval = {
                    "classifier_precision": eval_row.classifier_precision,
                    "entity_f1":            eval_row.entity_f1,
                    "passed":               eval_row.passed,
                    "run_at":               eval_row.run_at.isoformat() if eval_row.run_at else None,
                }

            return {
                "overview": {
                    "total_entries":     total_entries,
                    "entries_today":     entries_today,
                    "entries_this_week": entries_week,
                    "cache_hit_rate":    cache_hit_rate,
                    "tier1_calls":       tier1_calls,
                    "tier2_calls":       tier2_calls,
                },
                "volume_by_day":           volume_by_day,
                "category_distribution":   category_distribution,
                "model_tier_distribution": model_tier_dist,
                "recent_eval":             recent_eval,
            }
    except Exception as exc:
        return {"error": str(exc)}


@router.post("/backfill-embeddings")
async def backfill_embeddings(_: str = Depends(require_admin)) -> dict:
    """
    Backfill entry_embeddings from the entries table.

    Reads all entries from PostgreSQL that don't yet have a corresponding
    row in entry_embeddings and creates embeddings for them via pgvector.
    Runs synchronously and returns the count when done.
    """
    from app.memory.vector_store import backfill_from_entries
    count = await backfill_from_entries()
    return {"status": "done", "backfilled": count}


@router.get("/costs")
async def get_costs(_: str = Depends(require_admin)) -> dict:
    """Aggregate token usage and estimated cost from recent entries."""
    from app.db.models import Entry
    from app.db.session import get_session

    try:
        async with get_session() as session:
            now = datetime.now(timezone.utc)
            month_ago = now - timedelta(days=30)

            rows = (await session.execute(
                select(
                    func.count().label("total_entries"),
                    func.coalesce(func.sum(Entry.prompt_tokens), 0).label("total_prompt"),
                    func.coalesce(func.sum(Entry.completion_tokens), 0).label("total_completion"),
                    func.coalesce(func.sum(Entry.embedding_tokens), 0).label("total_embedding"),
                    func.coalesce(func.sum(Entry.estimated_cost_usd), 0.0).label("total_cost"),
                )
                .where(Entry.created_at >= month_ago)
            )).one()

            total = rows.total_entries or 1
            return {
                "period": "last_30_days",
                "total_entries": rows.total_entries,
                "total_prompt_tokens": rows.total_prompt,
                "total_completion_tokens": rows.total_completion,
                "total_embedding_tokens": rows.total_embedding,
                "total_cost_usd": round(float(rows.total_cost), 4),
                "avg_cost_per_entry_usd": round(float(rows.total_cost) / total, 6),
            }
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/upcoming-reminders")
async def upcoming_reminders(
    days: int = 7,
    _: str = Depends(require_admin),
) -> dict:
    """
    List events with reminder_time in the next `days` days, so you can sanity-check
    the intent detector's scheduling output.
    """
    from app.db.models import Event
    from app.db.session import get_session

    now = datetime.now(timezone.utc)
    window_end = now + timedelta(days=days)

    async with get_session() as session:
        rows = (await session.execute(
            select(Event)
            .where(Event.reminder_time >= now)
            .where(Event.reminder_time <= window_end)
            .order_by(Event.reminder_time.asc())
        )).scalars().all()

    return {
        "window_days": days,
        "count": len(rows),
        "reminders": [
            {
                "event_id":      str(r.id),
                "description":   r.description,
                "event_time":    r.event_time.isoformat() if r.event_time else None,
                "reminder_time": r.reminder_time.isoformat() if r.reminder_time else None,
                "reminded":      r.reminded,
            }
            for r in rows
        ],
    }


@router.get("/rag-diagnostics")
async def rag_diagnostics(
    query: str = "test",
    _: str = Depends(require_admin),
) -> dict:
    """
    RAG pipeline health probe: counts, fts/index presence, sample search.
    """
    from sqlalchemy import text
    from app.db.session import get_session
    from app.memory.vector_store import hybrid_search, semantic_search, keyword_search

    out: dict[str, Any] = {"query": query}

    async with get_session() as session:
        out["entries_count"] = (
            await session.execute(text("SELECT COUNT(*) FROM entries"))
        ).scalar()
        try:
            out["entry_embeddings_count"] = (
                await session.execute(text("SELECT COUNT(*) FROM entry_embeddings"))
            ).scalar()
        except Exception as exc:
            out["entry_embeddings_count"] = f"error: {exc}"

        out["fts_column_exists"] = bool((await session.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name='entry_embeddings' AND column_name='fts'
        """))).scalar())
        out["gin_index_exists"] = bool((await session.execute(text("""
            SELECT 1 FROM pg_indexes
            WHERE tablename='entry_embeddings' AND indexname='entry_embeddings_fts_idx'
        """))).scalar())
        out["ivfflat_index_exists"] = bool((await session.execute(text("""
            SELECT 1 FROM pg_indexes
            WHERE tablename='entry_embeddings' AND indexname='entry_embeddings_ivfflat_idx'
        """))).scalar())

    async def _probe(fn, label):
        try:
            rows = await fn(query, limit=3)
            return {"ok": True, "count": len(rows), "sample_ids": [r.get("entry_id") for r in rows]}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    out["semantic_search"] = await _probe(semantic_search, "semantic")
    out["keyword_search"] = await _probe(keyword_search, "keyword")
    out["hybrid_search"] = await _probe(hybrid_search, "hybrid")

    return out


@router.get("/status")
def get_status(_: str = Depends(require_admin)) -> dict:
    """Combined system health: evals, cache, LangFuse availability."""
    from app.llm.cache import cache_stats

    evals: dict[str, Any] = {}
    if RESULTS_PATH.exists():
        with open(RESULTS_PATH) as f:
            r = json.load(f)
        evals = {
            "classifier_precision": r.get("classifier_precision"),
            "entity_f1":            r.get("entity_f1"),
            "passed":               r.get("passed", {}),
        }
    else:
        evals = {"status": "not_run"}

    lf_ok = bool(settings.LANGFUSE_SECRET_KEY and settings.LANGFUSE_PUBLIC_KEY)

    return {
        "evals":    evals,
        "cache":    cache_stats(),
        "langfuse": {"configured": lf_ok, "host": settings.LANGFUSE_HOST},
    }
