"""
Per-request token usage and cost tracking.

Uses a context variable to accumulate token counts across all LLM and
embedding calls within a single request.  Call ``get_usage()`` at the end
of the request to retrieve the totals.

Pricing is based on the published OpenAI rates as of April 2026.
"""
from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Pricing per 1M tokens (USD)
_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o":              {"input": 2.50, "output": 10.00},
    "gpt-4o-mini":         {"input": 0.15, "output": 0.60},
    "text-embedding-3-small": {"input": 0.02, "output": 0.00},
}


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    embedding_tokens: int = 0
    estimated_cost_usd: float = 0.0
    breakdown: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "embedding_tokens": self.embedding_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
        }


_usage_var: ContextVar[TokenUsage | None] = ContextVar("token_usage", default=None)


def _ensure() -> TokenUsage:
    usage = _usage_var.get()
    if usage is None:
        usage = TokenUsage()
        _usage_var.set(usage)
    return usage


def record_usage(model: str, prompt_tokens: int, completion_tokens: int) -> None:
    """Record a chat completion call's token usage."""
    usage = _ensure()
    usage.prompt_tokens += prompt_tokens
    usage.completion_tokens += completion_tokens

    pricing = _PRICING.get(model, _PRICING.get("gpt-4o"))
    cost = (prompt_tokens * pricing["input"] + completion_tokens * pricing["output"]) / 1_000_000
    usage.estimated_cost_usd += cost

    usage.breakdown.append({
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_usd": round(cost, 6),
    })


def record_embedding_usage(model: str, total_tokens: int) -> None:
    """Record an embedding call's token usage."""
    usage = _ensure()
    usage.embedding_tokens += total_tokens

    pricing = _PRICING.get(model, {"input": 0.02, "output": 0.0})
    cost = total_tokens * pricing["input"] / 1_000_000
    usage.estimated_cost_usd += cost


def get_usage() -> TokenUsage:
    """Return accumulated usage for the current request context."""
    return _ensure()


def reset_usage() -> None:
    """Reset usage for a new request context."""
    _usage_var.set(None)
