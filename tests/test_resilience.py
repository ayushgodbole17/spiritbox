"""
Tests for resilience primitives: openai_retry and CircuitBreaker.
"""
import asyncio

import pytest

from app.llm.resilience import CircuitBreaker, CircuitOpenError, openai_retry


# ---------------------------------------------------------------------------
# openai_retry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_openai_retry_succeeds_after_transient_errors(monkeypatch):
    """Transient RateLimitError should retry and eventually succeed."""
    import openai

    calls = {"n": 0}

    class FakeResp:
        request = None

    @openai_retry(max_attempts=3)
    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise openai.APITimeoutError(request=FakeResp())
        return "ok"

    assert await flaky() == "ok"
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_openai_retry_does_not_retry_non_transient(monkeypatch):
    """Non-transient errors should propagate on the first failure."""

    calls = {"n": 0}

    @openai_retry(max_attempts=5)
    async def always_bad():
        calls["n"] += 1
        raise ValueError("bad request")

    with pytest.raises(ValueError):
        await always_bad()
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_breaker_opens_after_threshold():
    breaker = CircuitBreaker(name="test", fail_threshold=3, cooldown_seconds=10)

    async def boom():
        raise RuntimeError("nope")

    for _ in range(3):
        with pytest.raises(RuntimeError):
            await breaker.call(boom)

    # 4th call must short-circuit
    with pytest.raises(CircuitOpenError):
        await breaker.call(boom)


@pytest.mark.asyncio
async def test_breaker_half_open_probe_closes_on_success():
    breaker = CircuitBreaker(name="test", fail_threshold=2, cooldown_seconds=0.1)

    async def boom():
        raise RuntimeError("nope")

    async def ok():
        return "good"

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await breaker.call(boom)

    # Breaker is open — probe rejected
    with pytest.raises(CircuitOpenError):
        await breaker.call(ok)

    await asyncio.sleep(0.15)  # cooldown elapses

    # Half-open probe succeeds → closed
    assert await breaker.call(ok) == "good"
    assert breaker.status()["state"] == "closed"
