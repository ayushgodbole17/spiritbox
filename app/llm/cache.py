"""
Semantic Cache — Phase 3.

In-memory LRU cache keyed on cosine similarity of input embeddings.

Before any LLM call, agents call `get_cached()` with their input text.
If a sufficiently similar previous call exists (cosine ≥ threshold), the
cached response is returned and no LLM call is made.  After a real LLM call,
agents call `set_cached()` to store the result.

In production this would be backed by Redis + a vector index, but for local
development an in-memory OrderedDict (LRU) is used.

Usage:
    from app.llm.cache import get_cached, set_cached

    cached = await get_cached(input_text, namespace="classifier")
    if cached is not None:
        return cached  # skip LLM

    result = await call_llm(...)
    await set_cached(input_text, result, namespace="classifier")
"""
from __future__ import annotations

import asyncio
import logging
import math
from collections import OrderedDict
from typing import Any

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory LRU store: key = (namespace, text) → (embedding, result)
# ---------------------------------------------------------------------------

_cache: OrderedDict[tuple[str, str], tuple[list[float], Any]] = OrderedDict()
_lock = asyncio.Lock()


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def _embed(text: str) -> list[float]:
    client = AsyncOpenAI()
    response = await client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
    )
    return response.data[0].embedding


async def get_cached(text: str, namespace: str = "default") -> Any | None:
    """
    Return the cached result for `text` in `namespace` if a sufficiently
    similar entry exists, otherwise return None.

    Args:
        text:      Input text to look up.
        namespace: Agent name — keeps classifier/entity/summarizer buckets separate.

    Returns:
        Cached result (whatever was stored by set_cached) or None.
    """
    if not _cache:
        return None

    try:
        query_vec = await _embed(text)
    except Exception as exc:
        logger.warning(f"[cache] Embedding failed during lookup: {exc}. Cache miss.")
        return None

    threshold = settings.CACHE_SIMILARITY_THRESHOLD

    async with _lock:
        for (ns, _), (stored_vec, result) in _cache.items():
            if ns != namespace:
                continue
            sim = _cosine(query_vec, stored_vec)
            if sim >= threshold:
                logger.info(
                    f"[cache] HIT namespace={namespace} similarity={sim:.4f}"
                )
                return result

    return None


async def set_cached(text: str, result: Any, namespace: str = "default") -> None:
    """
    Store `result` in the cache under `namespace` keyed by the embedding of `text`.

    Evicts the oldest entry when the cache exceeds CACHE_MAX_SIZE.

    Args:
        text:      Input text that produced `result`.
        result:    The value to cache (any serialisable object).
        namespace: Agent name.
    """
    try:
        vec = await _embed(text)
    except Exception as exc:
        logger.warning(f"[cache] Embedding failed during store: {exc}. Not caching.")
        return

    async with _lock:
        key = (namespace, text)
        if key in _cache:
            _cache.move_to_end(key)
        _cache[key] = (vec, result)
        while len(_cache) > settings.CACHE_MAX_SIZE:
            _cache.popitem(last=False)
            logger.debug("[cache] Evicted oldest entry (max size reached).")

    logger.debug(f"[cache] STORED namespace={namespace}")


def cache_stats() -> dict:
    """Return current cache size and namespace breakdown."""
    ns_counts: dict[str, int] = {}
    for (ns, _) in _cache:
        ns_counts[ns] = ns_counts.get(ns, 0) + 1
    return {"total": len(_cache), "by_namespace": ns_counts}
