"""
End-to-end ingest pipeline tests — Phase 2.

All external services (Weaviate, OpenAI LLM calls, Firestore, Cloud Scheduler,
LangFuse) are mocked so the tests run without any live infrastructure.

Tests verify:
  1. run_entry_pipeline() returns a correctly-shaped dict.
  2. The FastAPI /ingest/text endpoint returns HTTP 200 with the right schema.
  3. The full agent graph executes without errors when all agents are mocked.
"""
import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAMPLE_TEXT = (
    "I have a dentist appointment tomorrow at 10am. "
    "Feeling a bit anxious. Also paid my rent today, 22000 rupees."
)

# Canned LLM responses for each agent
_ENTITY_RESPONSE = json.dumps({
    "events": [{"description": "dentist appointment", "datetime": "tomorrow at 10am"}],
    "amounts": [{"description": "rent payment", "amount": 22000, "currency": "INR"}],
})

_CLASSIFY_RESPONSE = json.dumps({
    "classifications": [
        {"sentence": "I have a dentist appointment tomorrow at 10am.", "categories": ["health"]},
        {"sentence": "Feeling a bit anxious.", "categories": ["mental_health"]},
        {"sentence": "Also paid my rent today, 22000 rupees.", "categories": ["finances"]},
    ]
})

_INTENT_RESPONSE = json.dumps({"reminders": []})  # no schedulable reminders (datetimes not ISO)

_SUMMARY_RESPONSE = MagicMock()
_SUMMARY_RESPONSE.choices = [MagicMock()]
_SUMMARY_RESPONSE.choices[0].message.content = (
    "The writer has a dentist appointment tomorrow and is feeling anxious about it. "
    "They also paid their monthly rent of 22,000 rupees today."
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_langfuse(monkeypatch):
    """Prevent LangFuse from making real HTTP calls during tests."""
    import langfuse
    from unittest.mock import MagicMock

    def noop_observe(*args, **kwargs):
        def decorator(fn):
            return fn
        if args and callable(args[0]):
            return args[0]
        return decorator

    monkeypatch.setattr(langfuse, "observe", noop_observe)
    mock_client = MagicMock()
    monkeypatch.setattr(langfuse, "get_client", lambda: mock_client)


def _make_openai_response(content: str):
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


def _build_mock_openai_client(responses: list[str]):
    """
    Returns a mock AsyncOpenAI client where successive .chat.completions.create()
    calls return responses from the provided list (cycling through them).
    """
    call_count = {"n": 0}
    responses_list = responses

    async def mock_create(*args, **kwargs):
        idx = call_count["n"] % len(responses_list)
        call_count["n"] += 1
        return _make_openai_response(responses_list[idx])

    mock_completions = MagicMock()
    mock_completions.create = mock_create
    mock_chat = MagicMock()
    mock_chat.completions = mock_completions
    mock_client = MagicMock()
    mock_client.chat = mock_chat
    return mock_client


@pytest.fixture
def mock_all_openai():
    """
    Patch AsyncOpenAI globally so every agent gets a mock client.
    Responses cycle through entity → classify → intent → summarize order.
    """
    client = _build_mock_openai_client([
        _ENTITY_RESPONSE,
        _CLASSIFY_RESPONSE,
        _INTENT_RESPONSE,
        (
            "The writer has a dentist appointment tomorrow and is anxious about it. "
            "They also paid their monthly rent today."
        ),
    ])
    # Patch in all agent modules
    patches = [
        patch("app.llm.router.AsyncOpenAI", return_value=client),
    ]
    for p in patches:
        p.start()
    yield client
    for p in patches:
        p.stop()


@pytest.fixture
def mock_weaviate_upsert():
    fake_id = str(uuid.uuid4())
    with patch("app.memory.vector_store.upsert_entry", new_callable=AsyncMock, return_value=fake_id) as m:
        yield m, fake_id


@pytest.fixture
def mock_weaviate_list():
    with patch("app.memory.vector_store.list_entries", new_callable=AsyncMock, return_value=[]) as m:
        yield m


@pytest.fixture
def mock_weaviate_init():
    with patch("app.memory.vector_store.init_schema", new_callable=AsyncMock) as m:
        yield m


# ---------------------------------------------------------------------------
# Unit tests: agent pipeline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_returns_required_keys(mock_all_openai, mock_weaviate_upsert):
    """run_entry_pipeline() must return a dict with all required keys."""
    from app.agents.graph import run_entry_pipeline

    result = await run_entry_pipeline(SAMPLE_TEXT)

    assert isinstance(result, dict)
    for key in ("entry_id", "entities", "categories", "events", "summary"):
        assert key in result, f"Missing key: {key}"


@pytest.mark.asyncio
async def test_pipeline_entry_id_is_uuid(mock_all_openai, mock_weaviate_upsert):
    """entry_id must be a valid UUID v4 string."""
    from app.agents.graph import run_entry_pipeline

    result = await run_entry_pipeline(SAMPLE_TEXT)
    parsed = uuid.UUID(result["entry_id"], version=4)
    assert str(parsed) == result["entry_id"]


@pytest.mark.asyncio
async def test_pipeline_entities_is_dict(mock_all_openai, mock_weaviate_upsert):
    """entities must be a dict."""
    from app.agents.graph import run_entry_pipeline

    result = await run_entry_pipeline(SAMPLE_TEXT)
    assert isinstance(result["entities"], dict)


@pytest.mark.asyncio
async def test_pipeline_categories_is_list(mock_all_openai, mock_weaviate_upsert):
    """categories must be a list."""
    from app.agents.graph import run_entry_pipeline

    result = await run_entry_pipeline(SAMPLE_TEXT)
    assert isinstance(result["categories"], list)


@pytest.mark.asyncio
async def test_pipeline_events_is_list(mock_all_openai, mock_weaviate_upsert):
    """events must be a list."""
    from app.agents.graph import run_entry_pipeline

    result = await run_entry_pipeline(SAMPLE_TEXT)
    assert isinstance(result["events"], list)


@pytest.mark.asyncio
async def test_pipeline_summary_is_str(mock_all_openai, mock_weaviate_upsert):
    """summary must be a string."""
    from app.agents.graph import run_entry_pipeline

    result = await run_entry_pipeline(SAMPLE_TEXT)
    assert isinstance(result["summary"], str)


@pytest.mark.asyncio
async def test_pipeline_summary_non_empty_when_llm_responds(mock_all_openai, mock_weaviate_upsert):
    """When the LLM returns a summary, the result summary must be non-empty."""
    from app.agents.graph import run_entry_pipeline

    result = await run_entry_pipeline(SAMPLE_TEXT)
    assert len(result["summary"]) > 0


@pytest.mark.asyncio
async def test_pipeline_multiple_calls_produce_unique_ids(mock_all_openai, mock_weaviate_upsert):
    """Each pipeline invocation must produce a unique entry_id."""
    from app.agents.graph import run_entry_pipeline

    results = await asyncio.gather(
        run_entry_pipeline("Entry one."),
        run_entry_pipeline("Entry two."),
        run_entry_pipeline("Entry three."),
    )
    ids = [r["entry_id"] for r in results]
    assert len(set(ids)) == 3, "All entry IDs must be unique"


@pytest.mark.asyncio
async def test_pipeline_handles_empty_text(mock_all_openai, mock_weaviate_upsert):
    """Pipeline must not raise on empty input."""
    from app.agents.graph import run_entry_pipeline

    result = await run_entry_pipeline("")
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_pipeline_calls_weaviate_upsert(mock_all_openai, mock_weaviate_upsert):
    """run_entry_pipeline() must call upsert_entry exactly once per invocation."""
    from app.agents.graph import run_entry_pipeline

    mock_upsert, _ = mock_weaviate_upsert
    await run_entry_pipeline(SAMPLE_TEXT)
    mock_upsert.assert_called_once()


@pytest.mark.asyncio
async def test_pipeline_continues_if_weaviate_fails(mock_all_openai):
    """Pipeline must not raise if Weaviate upsert fails (best-effort)."""
    from app.agents.graph import run_entry_pipeline

    with patch(
        "app.memory.vector_store.upsert_entry",
        new_callable=AsyncMock,
        side_effect=Exception("Weaviate down"),
    ):
        result = await run_entry_pipeline(SAMPLE_TEXT)

    assert isinstance(result, dict)
    assert "entry_id" in result


# ---------------------------------------------------------------------------
# Integration tests: FastAPI /ingest/text endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_text_endpoint_success(
    mock_langfuse, mock_all_openai, mock_weaviate_upsert, mock_weaviate_init
):
    """POST /ingest/text must return 200 with IngestResponse schema."""
    from app.main import app

    _, fake_id = mock_weaviate_upsert

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/ingest/text",
            json={"text": SAMPLE_TEXT, "user_id": "test_user"},
        )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    body = response.json()
    assert "entry_id" in body
    assert "summary" in body
    assert "categories" in body
    assert "entities" in body
    assert "events" in body
    assert isinstance(body["categories"], list)
    assert isinstance(body["entities"], dict)
    assert isinstance(body["events"], list)


@pytest.mark.asyncio
async def test_ingest_text_endpoint_uses_upsert(
    mock_langfuse, mock_all_openai, mock_weaviate_upsert, mock_weaviate_init
):
    """POST /ingest/text must call upsert_entry exactly once."""
    from app.main import app

    mock_upsert, _ = mock_weaviate_upsert

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/ingest/text", json={"text": SAMPLE_TEXT})

    mock_upsert.assert_called_once()


@pytest.mark.asyncio
async def test_health_endpoint(mock_weaviate_init):
    """GET /health must return {"status": "ok"}."""
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_ingest_text_empty_body_rejected(mock_langfuse, mock_weaviate_init):
    """POST /ingest/text with missing 'text' field must return 422."""
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/ingest/text", json={"user_id": "test_user"})

    assert response.status_code == 422
