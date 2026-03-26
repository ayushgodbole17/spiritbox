"""
Tests for Phase 3: agent wiring — router tier selection and cache integration.

Verifies that:
  - classifier/summarizer use TIER_1 (gpt-4o-mini)
  - entity_extractor/intent_detector use TIER_2 (gpt-4o)
  - model_used and cache_hits are written to state
  - a second identical call hits the cache and skips the LLM
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_cache():
    import app.llm.cache as c
    c._cache.clear()
    yield
    c._cache.clear()


@pytest.fixture(autouse=True)
def noop_langfuse(monkeypatch):
    """Disable LangFuse tracing so @observe() doesn't interfere."""
    import langfuse
    monkeypatch.setattr(langfuse, "observe", lambda *a, **kw: (a[0] if a and callable(a[0]) else lambda fn: fn))


def _router_mock(content: str, model_name: str):
    """Patch chat_completion to return (mock_response, model_name)."""
    choice = MagicMock()
    choice.message.content = content
    resp = MagicMock()
    resp.choices = [choice]
    return AsyncMock(return_value=(resp, model_name))


def _embed_mock(vector=None):
    vec = vector or [1.0, 0.0, 0.0]
    return patch("app.llm.cache._embed", new=AsyncMock(return_value=vec))


def _base_state(text="I went for a run today."):
    return {
        "raw_text": text,
        "entities": {},
        "categories": [],
        "events": [],
        "summary": "",
        "entry_id": "test-id",
        "model_used": {},
        "cache_hits": {},
    }


# ---------------------------------------------------------------------------
# Classifier — Tier 1
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classifier_uses_tier1():
    payload = json.dumps({"classifications": [
        {"sentence": "I went for a run today.", "categories": ["fitness"]},
    ]})
    mock_cc = _router_mock(payload, "gpt-4o-mini")

    with patch("app.agents.classifier.chat_completion", mock_cc), _embed_mock():
        from app.agents.classifier import classify_sentences
        result = await classify_sentences(_base_state())

    mock_cc.assert_awaited_once()
    assert mock_cc.call_args.kwargs.get("tier") == "tier1" or mock_cc.call_args.args[0] == "tier1"
    assert result["model_used"]["classifier"] == "gpt-4o-mini"
    assert result["cache_hits"]["classifier"] is False


@pytest.mark.asyncio
async def test_classifier_cache_hit_skips_llm():
    payload = json.dumps({"classifications": [
        {"sentence": "I went for a run today.", "categories": ["fitness"]},
    ]})
    mock_cc = _router_mock(payload, "gpt-4o-mini")

    text = "I went for a run today."
    with patch("app.agents.classifier.chat_completion", mock_cc), _embed_mock():
        from app.agents.classifier import classify_sentences
        # First call — populates cache
        await classify_sentences(_base_state(text))
        # Second call — should hit cache
        result = await classify_sentences(_base_state(text))

    # LLM should only have been called once
    assert mock_cc.await_count == 1
    assert result["model_used"]["classifier"] == "cache"
    assert result["cache_hits"]["classifier"] is True


# ---------------------------------------------------------------------------
# Summarizer — Tier 1
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_summarizer_uses_tier1():
    mock_cc = _router_mock("A short summary.", "gpt-4o-mini")

    with patch("app.agents.summarizer.chat_completion", mock_cc), _embed_mock():
        from app.agents.summarizer import summarize_entry
        result = await summarize_entry(_base_state())

    mock_cc.assert_awaited_once()
    tier_arg = mock_cc.call_args.args[0] if mock_cc.call_args.args else mock_cc.call_args.kwargs.get("tier")
    assert tier_arg == "tier1"
    assert result["model_used"]["summarizer"] == "gpt-4o-mini"
    assert result["cache_hits"]["summarizer"] is False


# ---------------------------------------------------------------------------
# Entity Extractor — Tier 2
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_entity_extractor_uses_tier2():
    payload = json.dumps({"people": [], "places": [], "dates": [], "events": [], "amounts": [], "organizations": []})
    mock_cc = _router_mock(payload, "gpt-4o")

    with patch("app.agents.entity_extractor.chat_completion", mock_cc), _embed_mock():
        from app.agents.entity_extractor import extract_entities
        result = await extract_entities(_base_state())

    mock_cc.assert_awaited_once()
    tier_arg = mock_cc.call_args.args[0] if mock_cc.call_args.args else mock_cc.call_args.kwargs.get("tier")
    assert tier_arg == "tier2"
    assert result["model_used"]["entity_extractor"] == "gpt-4o"
    assert result["cache_hits"]["entity_extractor"] is False


# ---------------------------------------------------------------------------
# Intent Detector — Tier 2
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_intent_detector_uses_tier2():
    payload = json.dumps({"reminders": []})
    mock_cc = _router_mock(payload, "gpt-4o")

    state = {**_base_state(), "entities": {"events": []}}

    with patch("app.agents.intent_detector.chat_completion", mock_cc), \
         patch("app.db.crud.save_event", new=AsyncMock(return_value="pg-evt-id")), \
         patch("app.events.firestore.save_event", new=AsyncMock(return_value="fs-evt-id")), \
         patch("app.scheduler.create_job.create_reminder_job", new=AsyncMock()), \
         _embed_mock():
        from app.agents.intent_detector import detect_intents
        result = await detect_intents(state)

    mock_cc.assert_awaited_once()
    tier_arg = mock_cc.call_args.args[0] if mock_cc.call_args.args else mock_cc.call_args.kwargs.get("tier")
    assert tier_arg == "tier2"
    assert result["model_used"]["intent_detector"] == "gpt-4o"
    assert result["cache_hits"]["intent_detector"] is False
