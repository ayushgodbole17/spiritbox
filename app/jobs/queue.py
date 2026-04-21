"""
Lightweight job queue for async ingest work.

Current implementation: asyncio.create_task — the coroutine runs in the
same Cloud Run container after the HTTP response is sent. This works
because Cloud Run keeps the container alive until it scales to zero, and
the transcription pipeline is bounded by the 25 MB audio cap (< 90 s).

A Cloud Tasks adapter can replace `enqueue` later without touching callers:
serialize job_id + kind, `POST /internal/jobs/run` with OIDC auth, and let
Cloud Tasks handle retries. Kept behind this interface intentionally.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task] = set()


def enqueue(coro_factory: Callable[[], Awaitable[None]], *, name: str) -> None:
    """
    Fire-and-forget a coroutine produced by `coro_factory`.

    We hold a strong reference in `_background_tasks` so the task isn't
    garbage-collected mid-flight (asyncio only keeps weakrefs).
    """
    try:
        task = asyncio.create_task(coro_factory(), name=name)
    except RuntimeError as exc:
        logger.error(f"[jobs] enqueue({name}) failed — no running loop: {exc!r}")
        raise

    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    task.add_done_callback(_log_task_failure)


def _log_task_failure(task: asyncio.Task) -> None:
    if task.cancelled():
        logger.info(f"[jobs] task {task.get_name()} cancelled")
        return
    exc = task.exception()
    if exc is not None:
        logger.error(f"[jobs] task {task.get_name()} crashed: {exc!r}", exc_info=exc)


def pending_count() -> int:
    """For debugging / /admin diagnostics."""
    return len(_background_tasks)
