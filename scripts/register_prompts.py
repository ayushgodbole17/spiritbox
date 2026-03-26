"""
One-time script to register all Spiritbox prompts in LangFuse.

Run once (or whenever you want to push an updated prompt version):

    python scripts/register_prompts.py

Each prompt is registered as a 'chat' type with the system and user messages.
After registration you can edit, version, and roll back prompts in the
LangFuse UI without touching code.

The agents fetch these at runtime via app/prompts/loader.py and fall back
to the local Python strings if LangFuse is unreachable.
"""
import sys
import os

# Allow running from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app.config import settings
from langfuse import Langfuse

from app.prompts.classify        import SYSTEM as CLASSIFY_SYSTEM,       USER_TEMPLATE as CLASSIFY_USER
from app.prompts.extract_entities import SYSTEM as ENTITY_SYSTEM,         USER_TEMPLATE as ENTITY_USER
from app.prompts.detect_intent   import SYSTEM as INTENT_SYSTEM,          USER_TEMPLATE as INTENT_USER
from app.prompts.summarize       import SYSTEM as SUMMARIZE_SYSTEM,       USER_TEMPLATE as SUMMARIZE_USER


PROMPTS = [
    {
        "name":      "spiritbox.classify.v1",
        "system":    CLASSIFY_SYSTEM,
        "user":      CLASSIFY_USER,
        "variables": ["transcript"],
        "tags":      ["classifier", "phase-2"],
        "message":   "Initial classifier prompt — sentence-level life-domain categories.",
    },
    {
        "name":      "spiritbox.extract_entities.v1",
        "system":    ENTITY_SYSTEM,
        "user":      ENTITY_USER,
        "variables": ["transcript"],
        "tags":      ["entity-extractor", "phase-2"],
        "message":   "Initial entity extraction prompt — people, dates, amounts, events.",
    },
    {
        "name":      "spiritbox.detect_intent.v1",
        "system":    INTENT_SYSTEM,
        "user":      INTENT_USER,
        "variables": ["current_datetime", "timezone", "entities_json"],
        "tags":      ["intent-detector", "phase-2"],
        "message":   "Initial intent detection prompt — schedulable reminders.",
    },
    {
        "name":      "spiritbox.summarize.v1",
        "system":    SUMMARIZE_SYSTEM,
        "user":      SUMMARIZE_USER,
        "variables": ["transcript"],
        "tags":      ["summarizer", "phase-2"],
        "message":   "Initial summarizer prompt — 2-3 sentence journal digest.",
    },
]


def to_langfuse_template(text: str, variables: list[str]) -> str:
    """
    Convert {variable} → {{variable}} for LangFuse's template engine.
    LangFuse uses {{variable}} for substitution; single braces (e.g. in JSON
    examples inside the prompt) are left as-is and treated as literals.
    """
    for var in variables:
        text = text.replace("{" + var + "}", "{{" + var + "}}")
    return text


def main():
    if not settings.LANGFUSE_SECRET_KEY or not settings.LANGFUSE_PUBLIC_KEY:
        print("ERROR: LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must be set in .env")
        sys.exit(1)

    client = Langfuse(
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
        host=settings.LANGFUSE_HOST,
    )

    for p in PROMPTS:
        vars_ = p["variables"]
        prompt_messages = [
            {"role": "system", "content": to_langfuse_template(p["system"], vars_)},
            {"role": "user",   "content": to_langfuse_template(p["user"],   vars_)},
        ]
        client.create_prompt(
            name=p["name"],
            prompt=prompt_messages,
            type="chat",
            labels=["production"],
            tags=p["tags"],
            commit_message=p["message"],
        )
        print(f"  ✓  {p['name']}")

    client.flush()
    print("\nAll prompts registered. View them at https://cloud.langfuse.com → Prompts.")


if __name__ == "__main__":
    main()
