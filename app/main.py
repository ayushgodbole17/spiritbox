import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import ingest, entries, reminders, chat, admin
from app.memory.vector_store import init_schema

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — runs startup and shutdown logic."""
    logger.info("Starting Spiritbox...")
    try:
        await init_schema()
        logger.info("Weaviate schema initialized successfully.")
    except Exception as e:
        logger.warning(f"Weaviate schema initialization failed (non-fatal): {e}")
    try:
        from app.db.session import create_tables
        await create_tables()
        logger.info("PostgreSQL tables ready.")
    except Exception as e:
        logger.warning(f"PostgreSQL table creation failed (non-fatal): {e}")
    yield
    logger.info("Spiritbox shutting down.")


app = FastAPI(
    title="Spiritbox",
    description="Production-grade personal AI agent for journaling and life management.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(ingest.router, prefix="/ingest", tags=["Ingest"])
app.include_router(entries.router, prefix="/entries", tags=["Entries"])
app.include_router(reminders.router, prefix="/reminders", tags=["Reminders"])
app.include_router(chat.router, prefix="/chat", tags=["Chat"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])


@app.get("/health", tags=["Health"])
async def health_check():
    """Liveness probe — also reports semantic cache stats."""
    from app.llm.cache import cache_stats
    return {"status": "ok", "cache": cache_stats()}
