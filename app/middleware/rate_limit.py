"""
Sliding-window rate limiter middleware.

Keyed by authenticated user_id (from JWT) or client IP.
Returns 429 Too Many Requests with a Retry-After header when exceeded.

Default limits:
  - /ingest:  10 requests / minute
  - /chat:    30 requests / minute
  - other:    60 requests / minute
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


@dataclass
class _Bucket:
    timestamps: list[float] = field(default_factory=list)

    def count_in_window(self, now: float, window: float) -> int:
        cutoff = now - window
        self.timestamps = [t for t in self.timestamps if t > cutoff]
        return len(self.timestamps)

    def add(self, now: float) -> None:
        self.timestamps.append(now)


# Route prefix -> (max_requests, window_seconds)
_LIMITS: dict[str, tuple[int, int]] = {
    "/ingest": (10, 60),
    "/chat":   (30, 60),
}
_DEFAULT_LIMIT = (60, 60)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._buckets: dict[str, _Bucket] = defaultdict(_Bucket)

    async def dispatch(self, request: Request, call_next):
        # Identify caller: JWT user_id > forwarded IP > client IP
        key = self._get_key(request)
        max_requests, window = self._get_limit(request.url.path)
        bucket_key = f"{key}:{request.url.path.split('/')[1]}"

        now = time.monotonic()
        bucket = self._buckets[bucket_key]
        count = bucket.count_in_window(now, window)

        if count >= max_requests:
            retry_after = int(window - (now - bucket.timestamps[0])) + 1
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded", "retry_after": retry_after},
                headers={"Retry-After": str(retry_after)},
            )

        bucket.add(now)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Remaining"] = str(max(0, max_requests - count - 1))
        return response

    @staticmethod
    def _get_key(request: Request) -> str:
        # Check for user_id set by auth middleware / JWT decode
        user_id = request.state.__dict__.get("user_id") if hasattr(request, "state") else None
        if user_id:
            return f"user:{user_id}"
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return f"ip:{forwarded.split(',')[0].strip()}"
        client = request.client
        return f"ip:{client.host}" if client else "ip:unknown"

    @staticmethod
    def _get_limit(path: str) -> tuple[int, int]:
        for prefix, limit in _LIMITS.items():
            if path.startswith(prefix):
                return limit
        return _DEFAULT_LIMIT
