"""Versioned deployment pricing, independent of pipeline logic. All amounts are USD."""

import json
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, Field

from .telemetry_schemas import CostSummary, ProviderCall


class TokenPrice(BaseModel):
    input_per_million: Decimal = Field(ge=0)
    cached_input_per_million: Decimal | None = Field(default=None, ge=0)
    output_per_million: Decimal | None = Field(default=None, ge=0)


class PricingCatalog(BaseModel):
    version: str = Field(min_length=1)
    models: dict[str, TokenPrice] = Field(default_factory=dict)
    tavily_credit_usd: Decimal | None = Field(default=None, ge=0)


def load_pricing(path: Path | None) -> PricingCatalog:
    # No guessed prices: a deployment must choose and version its provider rate card.
    if path is None:
        return PricingCatalog(version="unconfigured")
    return PricingCatalog.model_validate(json.loads(path.read_text(encoding="utf-8")))


def estimate_call(call: ProviderCall, pricing: PricingCatalog) -> Decimal | None:
    if call.provider == "tavily":
        if call.usage_credits is None or pricing.tavily_credit_usd is None:
            return None
        return call.usage_credits * pricing.tavily_credit_usd
    price = pricing.models.get(f"{call.provider}:{call.model}")
    if price is None or call.input_tokens is None:
        return None
    if call.operation in {"document_embedding", "query_embedding"}:
        return Decimal(call.input_tokens) * price.input_per_million / Decimal(1_000_000)
    if call.output_tokens is None or price.output_per_million is None:
        return None
    # Unknown cached usage/rate cannot safely be treated as zero.
    if call.cached_input_tokens is None:
        return None
    cached = call.cached_input_tokens
    if cached > call.input_tokens or (cached and price.cached_input_per_million is None):
        return None
    input_cost = Decimal(call.input_tokens - cached) * price.input_per_million
    cached_cost = Decimal(cached) * (price.cached_input_per_million or Decimal(0))
    output_cost = Decimal(call.output_tokens) * price.output_per_million
    return (input_cost + cached_cost + output_cost) / Decimal(1_000_000)


def estimate_run(calls: list[ProviderCall], pricing: PricingCatalog) -> CostSummary:
    for call in calls:
        call.estimated_cost_usd = estimate_call(call, pricing)
    known = [call.estimated_cost_usd for call in calls if call.estimated_cost_usd is not None]
    missing = len(calls) - len(known)
    subtotal = sum(known, Decimal(0)) if known else None
    return CostSummary(
        pricing_version=pricing.version,
        status="estimated" if calls and not missing else "partial" if known else "unavailable",
        estimated_total=subtotal if not missing else None,
        known_subtotal=subtotal,
        unavailable_calls=missing,
    )
