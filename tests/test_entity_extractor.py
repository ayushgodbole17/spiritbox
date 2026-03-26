"""
Tests for the Entity Extractor agent — Phase 2.

All OpenAI calls are mocked so the tests run without live API access.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.prompts.extract_entities import ENTITY_EXTRACTION_PROMPT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DENTIST_TEXT = "dentist appointment tomorrow at 10am, paid rent 22000 rupees"

ALLOWED_KEYS = {"people", "places", "dates", "events", "amounts", "organizations"}


def _make_openai_response(content: str):
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_async_client(content: str):
    mock_create = AsyncMock(return_value=_make_openai_response(content))
    mock_completions = MagicMock()
    mock_completions.create = mock_create
    mock_chat = MagicMock()
    mock_chat.completions = mock_completions
    mock_client = MagicMock()
    mock_client.chat = mock_chat
    return mock_client, mock_create


# ---------------------------------------------------------------------------
# LangFuse no-op fixture
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_langfuse(monkeypatch):
    import langfuse

    def noop_observe(*args, **kwargs):
        def decorator(fn):
            return fn
        if args and callable(args[0]):
            return args[0]
        return decorator

    monkeypatch.setattr(langfuse, "observe", noop_observe)


# ---------------------------------------------------------------------------
# Phase 2: real LLM path (mocked OpenAI)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_dentist_and_rent_extracts_events_and_amounts():
    """'dentist appointment tomorrow at 10am, paid rent 22000 rupees' should extract
    at least one event and one amount."""
    llm_payload = json.dumps({
        "events": [
            {"description": "dentist appointment", "datetime": "tomorrow at 10am"}
        ],
        "amounts": [
            {"description": "rent payment", "amount": 22000, "currency": "INR"}
        ],
        "dates": ["tomorrow at 10am"],
    })
    mock_client, _ = _make_async_client(llm_payload)

    with patch("app.llm.router.AsyncOpenAI", return_value=mock_client):
        from app.agents.entity_extractor import extract
        result = await extract(DENTIST_TEXT)

    assert isinstance(result, dict)
    assert "events" in result
    assert len(result["events"]) >= 1
    assert result["events"][0]["description"] == "dentist appointment"

    assert "amounts" in result
    assert len(result["amounts"]) >= 1
    assert result["amounts"][0]["amount"] == 22000
    assert result["amounts"][0]["currency"] == "INR"


@pytest.mark.asyncio
async def test_extract_empty_entities_does_not_error():
    """If LLM returns no entities, extract() must return an empty dict without errors."""
    mock_client, _ = _make_async_client("{}")

    with patch("app.llm.router.AsyncOpenAI", return_value=mock_client):
        from app.agents.entity_extractor import extract
        result = await extract("Had a quiet day at home.")

    assert isinstance(result, dict)
    assert result == {}


@pytest.mark.asyncio
async def test_extract_result_uses_only_allowed_keys():
    """The result dict must contain only known entity type keys."""
    llm_payload = json.dumps({
        "people": ["Alice"],
        "unknownkey": ["should be stripped"],
    })
    mock_client, _ = _make_async_client(llm_payload)

    with patch("app.llm.router.AsyncOpenAI", return_value=mock_client):
        from app.agents.entity_extractor import extract
        result = await extract("Met Alice today.")

    for key in result:
        assert key in ALLOWED_KEYS, f"Unexpected key in result: {key!r}"
    assert "unknownkey" not in result


@pytest.mark.asyncio
async def test_extract_people_list():
    """People should be extracted as a list of strings."""
    llm_payload = json.dumps({"people": ["Bob", "Carol"]})
    mock_client, _ = _make_async_client(llm_payload)

    with patch("app.llm.router.AsyncOpenAI", return_value=mock_client):
        from app.agents.entity_extractor import extract
        result = await extract("Met Bob and Carol for lunch.")

    assert "people" in result
    assert isinstance(result["people"], list)
    assert "Bob" in result["people"]
    assert "Carol" in result["people"]


@pytest.mark.asyncio
async def test_extract_json_parse_error_returns_empty_dict():
    """JSON parse errors must return {} without raising an exception."""
    mock_client, _ = _make_async_client("NOT VALID JSON {{{{")

    with patch("app.llm.router.AsyncOpenAI", return_value=mock_client):
        from app.agents.entity_extractor import extract
        result = await extract(DENTIST_TEXT)

    assert result == {}


@pytest.mark.asyncio
async def test_extract_openai_error_returns_empty_dict():
    """If the OpenAI call raises, extract() must return {} not raise."""
    mock_create = AsyncMock(side_effect=Exception("network error"))
    mock_completions = MagicMock()
    mock_completions.create = mock_create
    mock_chat = MagicMock()
    mock_chat.completions = mock_completions
    mock_client = MagicMock()
    mock_client.chat = mock_chat

    with patch("app.llm.router.AsyncOpenAI", return_value=mock_client):
        from app.agents.entity_extractor import extract
        result = await extract(DENTIST_TEXT)

    assert result == {}


@pytest.mark.asyncio
async def test_extract_malformed_list_fields_are_coerced_to_empty():
    """If the LLM returns a non-list for a list field, it should be coerced to []."""
    llm_payload = json.dumps({
        "people": "Bob",      # should be a list, not a string
        "events": {"bad": "structure"},  # should be a list
    })
    mock_client, _ = _make_async_client(llm_payload)

    with patch("app.llm.router.AsyncOpenAI", return_value=mock_client):
        from app.agents.entity_extractor import extract
        result = await extract("Met Bob.")

    # Should coerce invalid list fields to []
    if "people" in result:
        assert isinstance(result["people"], list)
    if "events" in result:
        assert isinstance(result["events"], list)


# ---------------------------------------------------------------------------
# Prompt template tests (no LLM needed)
# ---------------------------------------------------------------------------

def test_entity_prompt_has_text_placeholder():
    assert "{text}" in ENTITY_EXTRACTION_PROMPT


def test_entity_prompt_renders():
    rendered = ENTITY_EXTRACTION_PROMPT.format(text="I have a meeting tomorrow.")
    assert "I have a meeting tomorrow." in rendered


def test_entity_prompt_mentions_key_types():
    for entity_type in ("people", "places", "events", "amounts"):
        assert entity_type in ENTITY_EXTRACTION_PROMPT
