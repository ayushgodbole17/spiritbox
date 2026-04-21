"""
Retries and circuit breakers for external-service calls.

- `openai_retry`: exponential backoff decorator for OpenAI calls.
- `CircuitBreaker`: half-open breaker — after N consecutive failures, subsequent
  calls short-circuit for a cool-down window; a single probe decides whether to
  close the breaker again.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Awaitable, Callable

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random_exponential,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OpenAI retry decorator
# ---------------------------------------------------------------------------

def _openai_retry_exceptions():
    """Lazy import — keeps the module importable if openai is absent."""
    import openai
    return (
        openai.RateLimitError,
        openai.APITimeoutError,
        openai.APIConnectionError,
        openai.InternalServerError,
    )


def openai_retry(max_attempts: int = 5):
    """
    Decorator: retry an async OpenAI call with exponential backoff + jitter.

    Only retries on transient errors (rate limit, timeout, connection, 5xx).
    Non-transient errors (bad request, auth, etc.) propagate immediately.
    """
    def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(max_attempts),
                wait=wait_random_exponential(multiplier=0.5, max=8),
                retry=retry_if_exception_type(_openai_retry_exceptions()),
                reraise=True,
            ):
                with attempt:
                    return await fn(*args, **kwargs)
        return wrapper
    return decorator


def sendgrid_retry(max_attempts: int = 3):
    """Retry SendGrid calls on transient HTTP errors. SendGrid SDK is sync."""
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            import httpx
            last_exc: Exception | None = None
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except (httpx.HTTPError, ConnectionError, TimeoutError) as exc:
                    last_exc = exc
                    wait = min(8.0, 0.5 * (2 ** attempt))
                    logger.warning(
                        f"[sendgrid_retry] attempt {attempt + 1}/{max_attempts} failed: {exc!r}; "
                        f"sleeping {wait:.1f}s"
                    )
                    time.sleep(wait)
            assert last_exc is not None
            raise last_exc
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

class CircuitOpenError(RuntimeError):
    """Raised when a call is rejected because the breaker is open."""


@dataclass
class CircuitBreaker:
    """
    Simple half-open circuit breaker.

    State machine:
      CLOSED  — calls pass through, failures counted.
      OPEN    — `fail_threshold` consecutive failures trip open; calls raise
                CircuitOpenError until `cooldown_seconds` elapse.
      HALF-OPEN — first call after cooldown acts as a probe. Success → CLOSED,
                failure → OPEN again.
    """

    name: str
    fail_threshold: int = 5
    cooldown_seconds: float = 30.0

    _failures: int = field(default=0, init=False)
    _opened_at: float | None = field(default=None, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def call(self, fn: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> Any:
        async with self._lock:
            if self._opened_at is not None:
                if (time.monotonic() - self._opened_at) < self.cooldown_seconds:
                    raise CircuitOpenError(
                        f"circuit '{self.name}' is open; retry in "
                        f"{self.cooldown_seconds - (time.monotonic() - self._opened_at):.1f}s"
                    )
                logger.info(f"[breaker:{self.name}] cool-down elapsed → HALF-OPEN probe")
                self._opened_at = None  # half-open: allow one probe

        try:
            result = await fn(*args, **kwargs)
        except Exception:
            async with self._lock:
                self._failures += 1
                if self._failures >= self.fail_threshold:
                    self._opened_at = time.monotonic()
                    logger.warning(
                        f"[breaker:{self.name}] OPEN after {self._failures} consecutive failures"
                    )
            raise
        else:
            async with self._lock:
                if self._failures:
                    logger.info(f"[breaker:{self.name}] CLOSED (reset after {self._failures} fails)")
                self._failures = 0
            return result

    def status(self) -> dict:
        if self._opened_at is None:
            return {"name": self.name, "state": "closed", "failures": self._failures}
        remaining = max(0.0, self.cooldown_seconds - (time.monotonic() - self._opened_at))
        return {
            "name": self.name,
            "state": "open",
            "failures": self._failures,
            "cooldown_remaining_s": round(remaining, 1),
        }


# ---------------------------------------------------------------------------
# Singleton breakers per upstream
# ---------------------------------------------------------------------------

openai_breaker = CircuitBreaker(name="openai", fail_threshold=5, cooldown_seconds=30.0)
whisper_breaker = CircuitBreaker(name="whisper", fail_threshold=3, cooldown_seconds=60.0)
sendgrid_breaker = CircuitBreaker(name="sendgrid", fail_threshold=3, cooldown_seconds=60.0)


def breaker_status() -> list[dict]:
    return [openai_breaker.status(), whisper_breaker.status(), sendgrid_breaker.status()]
