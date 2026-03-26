"""
LangFuse prompt loader.

Fetches prompts from LangFuse at runtime so they can be edited in the
LangFuse UI without touching code or redeploying.

Falls back to the local Python string if:
  - LangFuse keys are not configured
  - LangFuse is unreachable
  - The named prompt doesn't exist yet

Usage:
    from app.prompts.loader import get_messages

    messages = get_messages(
        name="spiritbox.classify.v1",
        fallback=[
            {"role": "system", "content": SYSTEM},
            {"role": "user",   "content": USER_TEMPLATE},
        ],
        variables={"transcript": raw_text},
    )
"""
import logging
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _client():
    """Lazy singleton LangFuse client. Returns None if keys are not set."""
    from app.config import settings
    if not settings.LANGFUSE_SECRET_KEY or not settings.LANGFUSE_PUBLIC_KEY:
        logger.debug("LangFuse keys not set — prompt loader will use local fallbacks.")
        return None
    try:
        from langfuse import Langfuse
        return Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST,
        )
    except Exception as e:
        logger.warning(f"LangFuse client init failed: {e}. Using local fallbacks.")
        return None


def _compile_fallback(fallback: list[dict], variables: dict[str, Any]) -> list[dict]:
    """Render {variable} placeholders in fallback messages."""
    result = []
    for msg in fallback:
        content = msg["content"]
        for k, v in variables.items():
            content = content.replace("{" + k + "}", str(v))
        result.append({"role": msg["role"], "content": content})
    return result


def get_messages(
    name: str,
    fallback: list[dict],
    variables: dict[str, Any] | None = None,
) -> tuple[list[dict], str]:
    """
    Fetch a chat prompt from LangFuse and compile it with variables.
    Falls back to local strings on any failure.

    Respects the PROMPT_VARIANT setting for A/B routing:
      - "production"  → stable prompts
      - "staging"     → experimental prompts being tested
      - "latest"      → most recently saved version
      - "local"       → always use local fallback strings (skip LangFuse)

    Args:
        name:      LangFuse prompt name, e.g. "spiritbox.classify.v1"
        fallback:  List of {role, content} dicts used if LangFuse is unavailable.
                   Variable placeholders use {variable_name} syntax.
        variables: Dict of variables to substitute into the prompt.

    Returns:
        Tuple of (messages, version_string) where:
          messages       — list of {role, content} dicts for the OpenAI API
          version_string — e.g. "spiritbox.classify.v1@v3" or "local"
    """
    from app.config import settings

    variables = variables or {}
    variant = settings.PROMPT_VARIANT

    client = _client()
    if client is not None and variant != "local":
        try:
            prompt = client.get_prompt(name, type="chat", label=variant)
            compiled = prompt.compile(**variables)
            version = f"{name}@v{prompt.version}"
            messages = [{"role": m["role"], "content": m["content"]} for m in compiled]
            return messages, version
        except Exception as e:
            logger.warning(f"LangFuse prompt fetch failed for '{name}' (label={variant}): {e}. Using local fallback.")
    return _compile_fallback(fallback, variables), "local"
