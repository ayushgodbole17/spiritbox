"""
Latency metric recording + percentile helpers.

Writes one row per handled request into `request_metrics`. The aggregation
helpers are called by /admin/analytics to surface p50 / p95 on the dashboard.

We swallow DB failures silently on the write path — a metric write must
never fail a request.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.db.models import RequestMetric
from app.db.session import get_session

logger = logging.getLogger(__name__)


async def record_latency(
    endpoint: str,
    duration_ms: int,
    user_id: str | None = None,
    status: str = "ok",
) -> None:
    """Persist a single latency sample. Never raises."""
    try:
        async with get_session() as session:
            session.add(RequestMetric(
                id=uuid.uuid4(),
                endpoint=endpoint,
                user_id=user_id,
                duration_ms=duration_ms,
                status=status,
            ))
            await session.commit()
    except Exception as exc:
        logger.warning(f"[metrics] record_latency failed (non-fatal): {exc!r}")


class Timer:
    """`async with Timer() as t: ...` then `t.elapsed_ms`."""

    def __init__(self) -> None:
        self._start = 0.0
        self.elapsed_ms = 0

    async def __aenter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.elapsed_ms = int((time.perf_counter() - self._start) * 1000)


async def percentiles(
    endpoint: str | None = None,
    minutes: int = 60,
) -> dict:
    """
    Return p50 / p95 / count over the last `minutes`. Uses Postgres'
    `percentile_cont` via SQLAlchemy func so we don't pull rows to the client.
    """
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    try:
        async with get_session() as session:
            stmt = select(
                func.count().label("n"),
                func.percentile_cont(0.5)
                    .within_group(RequestMetric.duration_ms.asc()).label("p50"),
                func.percentile_cont(0.95)
                    .within_group(RequestMetric.duration_ms.asc()).label("p95"),
            ).where(RequestMetric.created_at >= since)
            if endpoint:
                stmt = stmt.where(RequestMetric.endpoint == endpoint)
            row = (await session.execute(stmt)).one()
            return {
                "count": int(row.n or 0),
                "p50_ms": int(row.p50) if row.p50 is not None else None,
                "p95_ms": int(row.p95) if row.p95 is not None else None,
            }
    except Exception as exc:
        logger.warning(f"[metrics] percentiles failed: {exc!r}")
        return {"count": 0, "p50_ms": None, "p95_ms": None}
