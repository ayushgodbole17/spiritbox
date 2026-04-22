import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pythonjsonlogger.json import JsonFormatter

from app.config import settings
from app.api.routes import ingest, entries, reminders, chat, admin, auth, habits, digest
from app.memory.vector_store import init_schema, backfill_from_entries
from app.middleware.correlation import CorrelationIdMiddleware, CorrelationIdFilter
from app.middleware.rate_limit import RateLimitMiddleware


# --- Secret redaction for logs ---
# Masks the most common leakage patterns before records hit stdout.
_SECRET_PATTERNS = [
    re.compile(r"sk-(?:proj-|ant-|lf-)?[A-Za-z0-9_\-]{16,}"),          # OpenAI / Anthropic / LangFuse keys
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.=]{16,}", re.IGNORECASE),     # Bearer tokens
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # JWTs
    re.compile(r"SG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}"),       # SendGrid keys
]


class SecretRedactionFilter(logging.Filter):
    """Redacts API keys, Bearer tokens and JWTs from log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        for pat in _SECRET_PATTERNS:
            msg = pat.sub("[REDACTED]", msg)
        record.msg = msg
        record.args = None
        return True


# --- Structured JSON logging with correlation ID ---
_handler = logging.StreamHandler()
_handler.setFormatter(JsonFormatter(
    fmt="%(asctime)s %(levelname)s %(name)s %(correlation_id)s %(message)s",
    rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
))
_handler.addFilter(CorrelationIdFilter())
_handler.addFilter(SecretRedactionFilter())
logging.root.handlers = [_handler]
logging.root.setLevel(logging.INFO)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — runs startup and shutdown logic."""
    logger.info("Starting Spiritbox...")
    try:
        await init_schema()
        logger.info("pgvector schema initialized successfully.")
    except Exception as e:
        logger.warning(f"pgvector schema initialization failed (non-fatal): {e}")
    try:
        from app.db.session import create_tables
        await create_tables()
        logger.info("PostgreSQL tables ready.")
    except Exception as e:
        logger.warning(f"PostgreSQL table creation failed (non-fatal): {e}")
    # Backfill any entries missing from entry_embeddings (e.g. after Weaviate migration)
    try:
        count = await backfill_from_entries()
        if count:
            logger.info(f"Backfilled {count} entries into pgvector.")
    except Exception as e:
        logger.warning(f"Embedding backfill failed (non-fatal): {e}")

    # Rewrite legacy user_id='default' rows onto the real user. Pre-Phase-A,
    # ingests silently landed on 'default' when auth was missing; post-Phase-A
    # those rows became invisible to the authenticated user. Safe no-op on a
    # multi-user DB (runs only when there's exactly one real user).
    try:
        from sqlalchemy import text as _sql_text
        from app.db.session import engine

        async with engine.begin() as conn:
            row = (await conn.execute(_sql_text("SELECT COUNT(*) FROM users"))).scalar()
            if row == 1:
                total = 0
                for table in ("entries", "entry_embeddings", "habits"):
                    r = await conn.execute(_sql_text(f"""
                        UPDATE {table}
                           SET user_id = (SELECT id::text FROM users LIMIT 1)
                         WHERE user_id = 'default'
                    """))
                    total += r.rowcount or 0
                if total:
                    logger.info(f"Rewrote {total} legacy user_id='default' rows onto the real user.")
            else:
                logger.info(f"Skipping default-user backfill (user count = {row}).")
    except Exception as e:
        logger.warning(f"Default-user backfill failed (non-fatal): {e}")

    yield
    logger.info("Spiritbox shutting down.")


app = FastAPI(
    title="Spiritbox",
    description="Production-grade personal AI agent for journaling and life management.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(ingest.router, prefix="/ingest", tags=["Ingest"])
app.include_router(entries.router, prefix="/entries", tags=["Entries"])
app.include_router(reminders.router, prefix="/reminders", tags=["Reminders"])
app.include_router(chat.router, prefix="/chat", tags=["Chat"])
app.include_router(habits.router, prefix="/api/habits", tags=["Habits"])
app.include_router(digest.router, prefix="/api/digest", tags=["Digest"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])


@app.get("/health", tags=["Health"])
async def health_check():
    """Liveness probe — also reports semantic cache stats."""
    from app.llm.cache import cache_stats
    return {"status": "ok", "cache": cache_stats()}


# Cache a successful /ready result so probes don't hammer OpenAI with embeddings.
_READY_CACHE: dict = {"ok_until": 0.0}


@app.get("/ready", tags=["Health"])
async def readiness_check():
    """
    Readiness probe — verifies DB and OpenAI are reachable.

    Returns 503 if either dependency is unhealthy. The OpenAI probe result is
    cached for 30 seconds to avoid unnecessary embedding calls.
    """
    import asyncio
    import json
    import time

    from fastapi import Response
    from sqlalchemy import text as _sql_text

    from app.db.session import engine
    from app.llm.resilience import breaker_status

    checks: dict[str, dict] = {}

    try:
        async with asyncio.timeout(1.0):
            async with engine.connect() as conn:
                await conn.execute(_sql_text("SELECT 1"))
        checks["db"] = {"status": "ok"}
    except Exception as exc:
        checks["db"] = {"status": "fail", "error": str(exc)[:200]}

    now = time.monotonic()
    if now < _READY_CACHE["ok_until"]:
        checks["openai"] = {"status": "ok", "cached": True}
    else:
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            async with asyncio.timeout(3.0):
                await client.embeddings.create(
                    model="text-embedding-3-small",
                    input="ping",
                )
            _READY_CACHE["ok_until"] = now + 30.0
            checks["openai"] = {"status": "ok", "cached": False}
        except Exception as exc:
            checks["openai"] = {"status": "fail", "error": str(exc)[:200]}

    ok = all(c["status"] == "ok" for c in checks.values())
    body = {"status": "ready" if ok else "not_ready", "checks": checks, "breakers": breaker_status()}
    if not ok:
        return Response(content=json.dumps(body), status_code=503, media_type="application/json")
    return body
