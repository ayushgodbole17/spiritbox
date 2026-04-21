from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
from functools import lru_cache


class Settings(BaseSettings):
    # OpenAI / Anthropic
    OPENAI_API_KEY: str = Field(..., description="OpenAI API key")
    ANTHROPIC_API_KEY: Optional[str] = Field(None, description="Anthropic API key (optional)")

    # LangFuse observability
    LANGFUSE_PUBLIC_KEY: str = Field("", description="LangFuse public key")
    LANGFUSE_SECRET_KEY: str = Field("", description="LangFuse secret key")
    LANGFUSE_HOST: str = Field("https://cloud.langfuse.com", description="LangFuse host")

    # PostgreSQL (Cloud SQL)
    DATABASE_URL: str = Field("postgresql+asyncpg://user:pass@localhost:5432/spiritbox", description="Async PostgreSQL connection string")

    # Model routing
    LLM_TIER_1: str = Field("gpt-4o-mini", description="Cheap/fast model tier (classifier, summarizer)")
    LLM_TIER_2: str = Field("gpt-4o", description="Accurate/expensive model tier (entity extractor, intent detector)")

    # Prompt variant / A-B routing
    # Set to "production" for stable prompts, "staging" for experimental.
    # LangFuse will serve the prompt with this label; "local" skips LangFuse entirely.
    PROMPT_VARIANT: str = Field("production", description="LangFuse prompt label to use (production | staging | latest)")

    # Semantic cache
    CACHE_SIMILARITY_THRESHOLD: float = Field(0.95, description="Cosine similarity threshold for cache hit")
    CACHE_MAX_SIZE: int = Field(500, description="Max number of entries in semantic cache")

    # Admin dashboard — password is required; no default to prevent accidental prod exposure
    ADMIN_USERNAME: str = Field("admin", description="Admin dashboard username")
    ADMIN_PASSWORD: str = Field(..., description="Admin dashboard password (required, no default)")

    # CORS — comma-separated list of allowed origins. Wildcard is not allowed when credentials are on.
    CORS_ORIGINS: str = Field(
        "http://localhost:5173,http://localhost:3000",
        description="Comma-separated list of allowed CORS origins",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    # Eval gate thresholds
    EVAL_CLASSIFIER_THRESHOLD: float = Field(0.80, description="Min classifier precision to pass CI gate")
    EVAL_ENTITY_F1_THRESHOLD: float = Field(0.75, description="Min entity extractor F1 to pass CI gate")

    # Google OAuth2
    GOOGLE_CLIENT_ID: str = Field("", description="Google OAuth2 client ID")
    GOOGLE_CLIENT_SECRET: str = Field("", description="Google OAuth2 client secret")
    JWT_SECRET: str = Field("change-me-in-production", description="Secret key for signing JWTs")
    JWT_ALGORITHM: str = Field("HS256", description="JWT signing algorithm")
    JWT_EXPIRE_DAYS: int = Field(30, description="JWT expiry in days")
    FRONTEND_URL: str = Field("http://localhost:5173", description="Frontend URL for OAuth redirect")

    # Firestore (kept for legacy reminder support during migration)
    FIRESTORE_COLLECTION_EVENTS: str = Field("events", description="Firestore collection name for events")

    # GCP
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = Field(None, description="Path to GCP service account JSON")
    GCP_PROJECT_ID: Optional[str] = Field(None, description="GCP project ID")
    GCP_REGION: str = Field("asia-south1", description="GCP region")
    CLOUD_FUNCTION_URL: Optional[str] = Field(None, description="Cloud Function URL for reminder sending")

    # SendGrid / Email
    SENDGRID_API_KEY: Optional[str] = Field(None, description="SendGrid API key")
    REMINDER_FROM_EMAIL: str = Field("noreply@spiritbox.app", description="From address for reminder emails")

    # User preferences
    USER_EMAIL: str = Field("user@example.com", description="User's email address")
    USER_TIMEZONE: str = Field("Asia/Kolkata", description="User's timezone")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore",
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
