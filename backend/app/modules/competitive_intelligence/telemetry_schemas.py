from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class StageSummary(BaseModel):
    name: str
    calls: int = 0
    duration_ms: float = 0
    failures: int = 0
    error_type: str | None = None


class ProviderCall(BaseModel):
    provider: str
    operation: str
    model: str | None = None
    duration_ms: float = 0
    status: Literal["succeeded", "failed"] = "succeeded"
    error_type: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    retry_count: int | None = None
    batch_count: int | None = None
    embedded_units: int | None = None
    search_depth: str | None = None
    search_mode: str | None = None
    extract_depth: str | None = None
    query_count: int | None = None
    candidates: int | None = None
    documents_selected: int | None = None
    extraction_urls: list[str] = Field(default_factory=list)
    successful_extractions: int | None = None
    failed_extractions: int | None = None
    usage_credits: Decimal | None = None
    estimated_cost_usd: Decimal | None = None


class RunStatistics(BaseModel):
    research_questions: int | None = None
    searches_executed: int = 0
    search_failures: int = 0
    source_candidates: int = 0
    sources_before_deduplication: int | None = None
    unique_sources: int | None = None
    documents_selected: int = 0
    chunks_generated: int | None = None
    chunks_indexed: int = 0
    embedding_index_batches: int = 0
    embedding_provider_batches: int = 0
    embedded_units: int = 0
    retrieval_queries: int = 0
    top_k: int | None = None
    evidence_retrieved: int | None = None
    distinct_evidence_sources: int | None = None
    context_characters: int | None = None


class EvidenceStatistic(BaseModel):
    evidence_id: str
    source_key: str
    chunk_id: str
    distance: float
    retrieval_rank: int


class TokenSummary(BaseModel):
    known_input_tokens: int = 0
    known_output_tokens: int = 0
    known_cached_input_tokens: int = 0
    calls_with_unknown_usage: int = 0


class CostSummary(BaseModel):
    pricing_version: str
    currency: Literal["USD"] = "USD"
    is_estimate: Literal[True] = True
    status: Literal["estimated", "partial", "unavailable"]
    estimated_total: Decimal | None
    known_subtotal: Decimal | None
    unavailable_calls: int


class RunTelemetry(BaseModel):
    schema_version: Literal["1"] = "1"
    analysis_run_id: UUID
    pipeline_version: str
    trace_id: str | None = None
    status: Literal["completed", "failed", "cancelled"]
    error_type: str | None = None
    total_duration_ms: float
    stages: list[StageSummary]
    models: list[str]
    provider_calls: list[ProviderCall]
    tokens: TokenSummary
    cost: CostSummary
    statistics: RunStatistics
    evidence: list[EvidenceStatistic]
