"""Published per-token prices, for the models this project has actually been run on.

Only rates copied from a provider's own price page belong here, each with its
source and the date it was read. A model that is not listed is priced as
``None`` -- unknown -- never as zero and never by analogy with another model.

Prices are US dollars per million tokens. Where a provider has peak and
off-peak rates the peak rate is used, so a reported cost is an upper bound.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input_per_m: float  # prompt tokens not served from the provider's cache
    output_per_m: float
    cached_input_per_m: float | None = None  # None: cached tokens cost the full input rate
    source: str = ""


# https://api-docs.deepseek.com/quick_start/pricing/ (read 2026-11-20), peak rates.
_DEEPSEEK = "DeepSeek API pricing page, 2026-11-20, peak rates"

PRICES: dict[str, Price] = {
    "deepseek-flash": Price(0.30, 1.20, 0.006, _DEEPSEEK),
    "deepseek-v4-flash": Price(0.30, 1.20, 0.006, _DEEPSEEK),  # retired alias, billed as Flash
    "deepseek-v4-pro": Price(1.32, 3.96, 0.044, _DEEPSEEK),
}


def price_for(model: str) -> Price | None:
    """The listed price for ``model``, or ``None`` when it is not listed."""
    return PRICES.get(model.strip().lower())


def cost_of(
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    cached_input_tokens: int | None = None,
) -> float | None:
    """Dollar cost of one call, or ``None`` when the model or its usage is unknown."""
    price = price_for(model)
    if price is None or input_tokens is None or output_tokens is None:
        return None
    cached = max(0, min(cached_input_tokens or 0, input_tokens))
    cached_rate = price.input_per_m if price.cached_input_per_m is None else price.cached_input_per_m
    return (
        (input_tokens - cached) * price.input_per_m
        + cached * cached_rate
        + output_tokens * price.output_per_m
    ) / 1_000_000
