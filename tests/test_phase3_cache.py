"""
Tests for Phase 3: Semantic Cache (app/llm/cache.py).

Embedding calls are mocked — no live API access required.
"""
import pytest
from unittest.mock import AsyncMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_embed_mock(vector: list[float]):
    """Return a patch target that makes _embed() return the given vector."""
    return patch("app.llm.cache._embed", new=AsyncMock(return_value=vector))


# ---------------------------------------------------------------------------
# Cache miss / hit
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_cache():
    """Reset the in-memory cache before every test."""
    import app.llm.cache as c
    c._cache.clear()
    yield
    c._cache.clear()


@pytest.mark.asyncio
async def test_cache_miss_returns_none():
    """Empty cache should always be a miss."""
    vec = [1.0, 0.0, 0.0]
    with _make_embed_mock(vec):
        from app.llm.cache import get_cached
        result = await get_cached("hello world", namespace="test")
    assert result is None


@pytest.mark.asyncio
async def test_cache_hit_exact():
    """Storing then retrieving the same text returns the cached result."""
    vec = [1.0, 0.0, 0.0]
    with _make_embed_mock(vec):
        from app.llm.cache import get_cached, set_cached
        await set_cached("hello world", {"answer": 42}, namespace="test")
        result = await get_cached("hello world", namespace="test")
    assert result == {"answer": 42}


@pytest.mark.asyncio
async def test_cache_hit_similar_vector():
    """A very similar vector (cosine ≈ 1.0) should still be a hit."""
    import math
    # Two nearly-identical vectors
    store_vec = [1.0, 0.01, 0.0]
    query_vec = [1.0, 0.01, 0.0]

    from app.llm.cache import get_cached, set_cached, _embed
    with patch("app.llm.cache._embed", new=AsyncMock(side_effect=[store_vec, query_vec])):
        await set_cached("text A", "result A", namespace="test")
        result = await get_cached("text A", namespace="test")

    assert result == "result A"


@pytest.mark.asyncio
async def test_cache_miss_orthogonal_vector():
    """An orthogonal vector (cosine = 0) should be a miss."""
    store_vec = [1.0, 0.0, 0.0]
    query_vec = [0.0, 1.0, 0.0]  # cosine similarity = 0

    from app.llm.cache import get_cached, set_cached
    with patch("app.llm.cache._embed", new=AsyncMock(side_effect=[store_vec, query_vec])):
        await set_cached("text A", "result A", namespace="test")
        result = await get_cached("text B", namespace="test")

    assert result is None


@pytest.mark.asyncio
async def test_namespace_isolation():
    """Entries in different namespaces must not cross-contaminate."""
    vec = [1.0, 0.0, 0.0]
    with _make_embed_mock(vec):
        from app.llm.cache import get_cached, set_cached
        await set_cached("same text", "classifier result", namespace="classifier")
        result = await get_cached("same text", namespace="summarizer")
    assert result is None


@pytest.mark.asyncio
async def test_lru_eviction():
    """Cache should evict the oldest entry when max size is exceeded."""
    from app.config import settings
    original_max = settings.CACHE_MAX_SIZE

    try:
        settings.CACHE_MAX_SIZE = 2  # tiny cache for testing
        vec = [1.0, 0.0, 0.0]
        with _make_embed_mock(vec):
            from app.llm.cache import get_cached, set_cached, _cache
            await set_cached("entry1", "val1", namespace="test")
            await set_cached("entry2", "val2", namespace="test")
            assert len(_cache) == 2

            await set_cached("entry3", "val3", namespace="test")
            assert len(_cache) == 2  # evicted entry1
            # entry1 should be gone
            assert ("test", "entry1") not in _cache
    finally:
        settings.CACHE_MAX_SIZE = original_max


@pytest.mark.asyncio
async def test_cache_stats():
    """cache_stats() should accurately report size and namespace breakdown."""
    vec = [1.0, 0.0, 0.0]
    with _make_embed_mock(vec):
        from app.llm.cache import set_cached, cache_stats
        await set_cached("a", "r1", namespace="classifier")
        await set_cached("b", "r2", namespace="classifier")
        await set_cached("c", "r3", namespace="summarizer")

    stats = cache_stats()
    assert stats["total"] == 3
    assert stats["by_namespace"]["classifier"] == 2
    assert stats["by_namespace"]["summarizer"] == 1


@pytest.mark.asyncio
async def test_embed_failure_on_lookup_is_miss():
    """If the embedding call fails during lookup, treat it as a miss (no crash)."""
    with patch("app.llm.cache._embed", new=AsyncMock(side_effect=Exception("embed down"))):
        from app.llm.cache import get_cached
        result = await get_cached("anything", namespace="test")
    assert result is None


@pytest.mark.asyncio
async def test_embed_failure_on_store_is_silent():
    """If the embedding call fails during store, the function returns silently."""
    with patch("app.llm.cache._embed", new=AsyncMock(side_effect=Exception("embed down"))):
        from app.llm.cache import set_cached, _cache
        await set_cached("anything", "value", namespace="test")
    # Nothing should be stored
    assert len(_cache) == 0
