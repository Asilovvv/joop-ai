"""Model prices for cost reporting (USD per million tokens).

Source: https://platform.claude.com/docs/en/models/haiku-5-5/overview
(checked 29 Oct 2026). Rates are for prompts up to 100,000 tokens, which
covers every Joop AI request. Thinking tokens are billed as output tokens.
Update this table when prices change.
"""

from __future__ import annotations

from typing import Optional

PRICES_PER_MTOK = {
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_write": 0.125, "cache_read": 0.01},
}

USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def empty_usage() -> dict:
    return {f: 0 for f in USAGE_FIELDS}


def add_usage(total: dict, response_usage) -> None:
    """Add an SDK `usage` object (or None) into a running total."""
    if response_usage is None:
        return
    for f in USAGE_FIELDS:
        total[f] += int(getattr(response_usage, f, 0) or 0)


def cost_usd(usage: dict, model: str) -> Optional[float]:
    """Cost of the given usage, or None if the model's price is unknown."""
    p = PRICES_PER_MTOK.get(model)
    if p is None:
        return None
    return (
        usage.get("input_tokens", 0) * p["input"]
        + usage.get("output_tokens", 0) * p["output"]
        + usage.get("cache_creation_input_tokens", 0) * p["cache_write"]
        + usage.get("cache_read_input_tokens", 0) * p["cache_read"]
    ) / 1_000_000
