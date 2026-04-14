"""
Request correlation ID middleware.

Generates a unique X-Request-ID for every incoming request and makes it
available to the entire call chain via a context variable.  A logging
filter automatically injects the ID into every log record so structured
logs can be grouped by request.
"""
from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        req_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        token = correlation_id.set(req_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = req_id
            return response
        finally:
            correlation_id.reset(token)


class CorrelationIdFilter(logging.Filter):
    """Injects correlation_id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id.get("-")  # type: ignore[attr-defined]
        return True
