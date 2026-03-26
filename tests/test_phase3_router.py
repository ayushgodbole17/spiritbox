"""
Tests for Phase 3: Model Router (app/llm/router.py).

All OpenAI calls are mocked — no live API access required.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(content: str, model: str = "gpt-4o-mini"):
    choice = MagicMock()
    choice.message.content = content
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _mock_client(content: str, model: str = "gpt-4o-mini"):
    mock_create = AsyncMock(return_value=_mock_response(content, model))
    client = MagicMock()
    client.chat.completions.create = mock_create
    return client, mock_create


# ---------------------------------------------------------------------------
# Router: tier selection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tier1_uses_mini_model():
    """TIER_1 should call gpt-4o-mini."""
    client, mock_create = _mock_client("hello")
    with patch("app.llm.router.AsyncOpenAI", return_value=client):
        from app.llm.router import chat_completion, TIER_1
        _, model_used = await chat_completion(TIER_1, [{"role": "user", "content": "hi"}])

    call_kwargs = mock_create.call_args
    assert call_kwargs.kwargs["model"] == "gpt-4o-mini"
    assert model_used == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_tier2_uses_gpt4o_model():
    """TIER_2 should call gpt-4o."""
    client, mock_create = _mock_client("hello")
    with patch("app.llm.router.AsyncOpenAI", return_value=client):
        from app.llm.router import chat_completion, TIER_2
        _, model_used = await chat_completion(TIER_2, [{"role": "user", "content": "hi"}])

    call_kwargs = mock_create.call_args
    assert call_kwargs.kwargs["model"] == "gpt-4o"
    assert model_used == "gpt-4o"


# ---------------------------------------------------------------------------
# Router: cascade fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cascade_on_empty_content():
    """If Tier 1 returns empty content, router cascades to gpt-4o."""
    empty_resp = _mock_response("")
    full_resp = _mock_response("fallback answer")

    mock_create = AsyncMock(side_effect=[empty_resp, full_resp])
    client = MagicMock()
    client.chat.completions.create = mock_create

    with patch("app.llm.router.AsyncOpenAI", return_value=client):
        from app.llm.router import chat_completion, TIER_1
        resp, model_used = await chat_completion(TIER_1, [{"role": "user", "content": "hi"}])

    assert mock_create.call_count == 2
    # Second call should be gpt-4o
    second_call_model = mock_create.call_args_list[1].kwargs["model"]
    assert second_call_model == "gpt-4o"
    assert model_used == "gpt-4o"


@pytest.mark.asyncio
async def test_cascade_on_exception():
    """If Tier 1 raises an exception, router cascades to gpt-4o."""
    fallback_resp = _mock_response("fallback answer")

    mock_create = AsyncMock(side_effect=[Exception("rate limit"), fallback_resp])
    client = MagicMock()
    client.chat.completions.create = mock_create

    with patch("app.llm.router.AsyncOpenAI", return_value=client):
        from app.llm.router import chat_completion, TIER_1
        resp, model_used = await chat_completion(TIER_1, [{"role": "user", "content": "hi"}])

    assert mock_create.call_count == 2
    assert model_used == "gpt-4o"
    assert resp.choices[0].message.content == "fallback answer"


@pytest.mark.asyncio
async def test_tier2_no_cascade():
    """TIER_2 calls gpt-4o directly, no cascade needed."""
    client, mock_create = _mock_client("answer")
    with patch("app.llm.router.AsyncOpenAI", return_value=client):
        from app.llm.router import chat_completion, TIER_2
        resp, model_used = await chat_completion(TIER_2, [{"role": "user", "content": "hi"}])

    assert mock_create.call_count == 1
    assert model_used == "gpt-4o"


@pytest.mark.asyncio
async def test_kwargs_forwarded():
    """Extra kwargs (e.g. response_format) must be forwarded to the API call."""
    client, mock_create = _mock_client('{"ok": true}')
    with patch("app.llm.router.AsyncOpenAI", return_value=client):
        from app.llm.router import chat_completion, TIER_1
        await chat_completion(
            TIER_1,
            [{"role": "user", "content": "hi"}],
            response_format={"type": "json_object"},
        )

    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs.get("response_format") == {"type": "json_object"}
