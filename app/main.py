import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pythonjsonlogger.json import JsonFormatter

from app.api.routes import ingest, entries, reminders, chat, admin, auth, habits
from app.memory.vector_store import init_schema, backfill_from_entries
from app.middleware.correlation import CorrelationIdMiddleware, CorrelationIdFilter
from app.middleware.rate_limit import RateLimitMiddleware

# --- Structured JSON logging with correlation ID ---
_handler = logging.StreamHandler()
_handler.setFormatter(JsonFormatter(
    fmt="%(asctime)s %(levelname)s %(name)s %(correlation_id)s %(message)s",
    rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
))
_handler.addFilter(CorrelationIdFilter())
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
        from app.db.session import create_tables, engine
        await create_tables()
        # create_all() doesn't ALTER existing tables — add missing columns explicitly
        from sqlalchemy import text
        async with engine.begin() as conn:
            for col, typ, default in [
                ("prompt_tokens", "INTEGER", "0"),
                ("completion_tokens", "INTEGER", "0"),
                ("embedding_tokens", "INTEGER", "0"),
                ("estimated_cost_usd", "DOUBLE PRECISION", "0.0"),
            ]:
                await conn.execute(text(
                    f"ALTER TABLE entries ADD COLUMN IF NOT EXISTS {col} {typ} DEFAULT {default}"
                ))
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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(ingest.router, prefix="/ingest", tags=["Ingest"])
app.include_router(entries.router, prefix="/entries", tags=["Entries"])
app.include_router(reminders.router, prefix="/reminders", tags=["Reminders"])
app.include_router(chat.router, prefix="/chat", tags=["Chat"])
app.include_router(habits.router, prefix="/api/habits", tags=["Habits"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])


@app.get("/health", tags=["Health"])
async def health_check():
    """Liveness probe — also reports semantic cache stats."""
    from app.llm.cache import cache_stats
    return {"status": "ok", "cache": cache_stats()}
