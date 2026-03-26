"""
Tests for the Classifier agent — Phase 2.

All OpenAI calls are mocked so the tests run without live API access.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.prompts.classify import CLASSIFY_PROMPT, CLASSIFY_FLAT_PROMPT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_CATEGORIES = {
    "health", "mental_health", "finances", "work", "music",
    "relationships", "travel", "food", "fitness", "learning",
    "hobbies", "family", "other",
}

SAMPLE_TEXT = (
    "I have a dentist appointment tomorrow at 10am. "
    "Feeling a bit anxious about it. "
    "Also paid my rent today, 22000 rupees."
)


def _make_openai_response(content: str):
    """Build a minimal mock that looks like an OpenAI ChatCompletion response."""
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_async_client(content: str):
    """Patch AsyncOpenAI so .chat.completions.create returns a canned response."""
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
async def test_classify_returns_list_of_dicts():
    """A valid journal entry should produce a list of {sentence, categories} dicts."""
    llm_payload = json.dumps({
        "classifications": [
            {"sentence": "I have a dentist appointment tomorrow at 10am.", "categories": ["health"]},
            {"sentence": "Feeling a bit anxious about it.", "categories": ["mental_health"]},
            {"sentence": "Also paid my rent today, 22000 rupees.", "categories": ["finances"]},
        ]
    })
    mock_client, _ = _make_async_client(llm_payload)

    with patch("app.llm.router.AsyncOpenAI", return_value=mock_client):
        from app.agents.classifier import classify
        result = await classify(SAMPLE_TEXT)

    assert isinstance(result, list)
    assert len(result) == 3
    for item in result:
        assert "sentence" in item
        assert "categories" in item
        assert isinstance(item["categories"], list)


@pytest.mark.asyncio
async def test_classify_categories_are_valid_strings():
    """Each categories value must be a list of strings from the valid category set."""
    llm_payload = json.dumps({
        "classifications": [
            {"sentence": "Went for a run.", "categories": ["fitness", "health"]},
            {"sentence": "Met my boss.", "categories": ["work"]},
        ]
    })
    mock_client, _ = _make_async_client(llm_payload)

    with patch("app.llm.router.AsyncOpenAI", return_value=mock_client):
        from app.agents.classifier import classify
        result = await classify("Went for a run. Met my boss.")

    for item in result:
        for cat in item["categories"]:
            assert cat in VALID_CATEGORIES, f"Unexpected category: {cat!r}"


@pytest.mark.asyncio
async def test_classify_filters_invalid_categories():
    """Categories outside the valid set must be dropped; fallback to 'other'."""
    llm_payload = json.dumps({
        "classifications": [
            {"sentence": "Something weird.", "categories": ["invalidcat", "health"]},
        ]
    })
    mock_client, _ = _make_async_client(llm_payload)

    with patch("app.llm.router.AsyncOpenAI", return_value=mock_client):
        from app.agents.classifier import classify
        result = await classify("Something weird.")

    assert len(result) == 1
    # "health" is valid and should survive; "invalidcat" should be dropped
    assert "health" in result[0]["categories"]
    assert "invalidcat" not in result[0]["categories"]


@pytest.mark.asyncio
async def test_classify_all_invalid_categories_fallback_to_other():
    """If all returned categories are invalid, the item should fall back to ['other']."""
    llm_payload = json.dumps({
        "classifications": [
            {"sentence": "Unknown.", "categories": ["notreal", "alsofake"]},
        ]
    })
    mock_client, _ = _make_async_client(llm_payload)

    with patch("app.llm.router.AsyncOpenAI", return_value=mock_client):
        from app.agents.classifier import classify
        result = await classify("Unknown.")

    assert result[0]["categories"] == ["other"]


@pytest.mark.asyncio
async def test_classify_json_parse_error_returns_empty_list():
    """JSON parse errors must be handled gracefully — return empty list, no exception."""
    mock_client, _ = _make_async_client("THIS IS NOT JSON }{][")

    with patch("app.llm.router.AsyncOpenAI", return_value=mock_client):
        from app.agents.classifier import classify
        result = await classify(SAMPLE_TEXT)

    assert result == []


@pytest.mark.asyncio
async def test_classify_empty_classifications_key():
    """If LLM returns an empty classifications array the result is an empty list."""
    mock_client, _ = _make_async_client('{"classifications": []}')

    with patch("app.llm.router.AsyncOpenAI", return_value=mock_client):
        from app.agents.classifier import classify
        result = await classify("Empty entry.")

    assert result == []


@pytest.mark.asyncio
async def test_classify_accepts_bare_array_response():
    """LLM may return a bare JSON array instead of a wrapped object — both are valid."""
    llm_payload = json.dumps([
        {"sentence": "I ran 5km.", "categories": ["fitness"]},
    ])
    mock_client, _ = _make_async_client(llm_payload)

    with patch("app.llm.router.AsyncOpenAI", return_value=mock_client):
        from app.agents.classifier import classify
        result = await classify("I ran 5km.")

    assert len(result) == 1
    assert result[0]["categories"] == ["fitness"]


@pytest.mark.asyncio
async def test_classify_openai_error_returns_empty_list():
    """If the OpenAI call raises an exception, classify() must return [] not raise."""
    mock_create = AsyncMock(side_effect=Exception("API error"))
    mock_completions = MagicMock()
    mock_completions.create = mock_create
    mock_chat = MagicMock()
    mock_chat.completions = mock_completions
    mock_client = MagicMock()
    mock_client.chat = mock_chat

    with patch("app.llm.router.AsyncOpenAI", return_value=mock_client):
        from app.agents.classifier import classify
        result = await classify(SAMPLE_TEXT)

    assert result == []


# ---------------------------------------------------------------------------
# Prompt template tests (no LLM needed)
# ---------------------------------------------------------------------------

def test_classify_prompt_has_text_placeholder():
    assert "{text}" in CLASSIFY_PROMPT


def test_classify_flat_prompt_has_text_placeholder():
    assert "{text}" in CLASSIFY_FLAT_PROMPT


def test_classify_prompt_renders():
    rendered = CLASSIFY_PROMPT.format(text="I had a great workout today.")
    assert "I had a great workout today." in rendered


def test_classify_prompt_mentions_all_categories():
    for cat in ("health", "mental_health", "finances", "work", "music"):
        assert cat in CLASSIFY_PROMPT
