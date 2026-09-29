"""Validated persistence models for the Competitive Intelligence V2 benchmark."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.modules.competitive_intelligence.evidence import RetrievedEvidence, SourceDocument


class BenchmarkCaseDefinition(BaseModel):
    case_id: str = Field(pattern=r"^[a-z0-9_]+$")
    research_question: str = Field(min_length=1)


class BenchmarkManifest(BaseModel):
    schema_version: str
    benchmark_id: str
    benchmark_version: str
    status: Literal["draft", "frozen"]
    description: str
    cases: list[BenchmarkCaseDefinition]
    relevance_scale: dict[str, str]
    ks: list[int]
    broad_relevance_threshold: int
    strict_relevance_threshold: int
    metric_definitions: dict[str, str]
    aggregation_policy: dict[str, str]
    search_configuration: dict[str, Any]
    document_acquisition_configuration: dict[str, Any]
    normalization_configuration: dict[str, Any]
    normalization_version: str
    chunk_size_tokens: int
    chunk_overlap_tokens: int
    resolved_tokenizer: str
    embedding_configuration: dict[str, Any]
    vector_store_configuration: dict[str, Any]
    top_k: int
    report_configuration: dict[str, Any]
    evaluation_configuration: dict[str, Any]
    prompt_sha256: dict[str, str]
    environment: dict[str, Any]
    git: dict[str, Any]
    created_at: datetime
    frozen_at: datetime | None = None


class BenchmarkSearchFixture(BaseModel):
    schema_version: str
    case_id: str
    research_question: str
    acquisition_configuration: dict[str, Any]
    documents: list[SourceDocument]
    captured_at: datetime
    migration_source: str | None = None

    @model_validator(mode="after")
    def validate_documents(self) -> BenchmarkSearchFixture:
        if not self.documents:
            raise ValueError("Search fixture must contain at least one document.")
        source_ids = [document.source_id for document in self.documents]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Search fixture contains duplicate source IDs.")
        for document in self.documents:
            if document.research_query != self.research_question:
                raise ValueError("SourceDocument research_query does not match the case question.")
        return self


class RetrievalCandidate(BaseModel):
    chunk_id: str
    source_id: str
    source_rank: int | None
    url: str
    domain: str
    title: str
    chunk_index: int
    token_count: int
    text: str


class RetrievalCandidatesFixture(BaseModel):
    schema_version: str
    case_id: str
    research_question: str
    normalization_version: str
    chunk_size_tokens: int
    chunk_overlap_tokens: int
    resolved_tokenizer: str
    chunking_configuration_sha256: str
    candidate_set_sha256: str
    candidates: list[RetrievalCandidate]
    created_at: datetime

    @model_validator(mode="after")
    def validate_candidates(self) -> RetrievalCandidatesFixture:
        if not self.candidates:
            raise ValueError("Candidate fixture must contain at least one chunk.")
        chunk_ids = [candidate.chunk_id for candidate in self.candidates]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("Candidate fixture contains duplicate chunk IDs.")
        return self


class GroundTruthLabel(BaseModel):
    chunk_id: str
    relevance: int | None = Field(default=None, ge=0, le=2)
    suggested_relevance: int | None = Field(default=None, ge=0, le=2)
    review_flag: str | None = None


class RetrievalGroundTruthFixture(BaseModel):
    schema_version: str
    case_id: str
    research_question: str
    candidate_set_sha256: str
    chunking_configuration_sha256: str
    annotation_guideline_version: str
    annotated_at: datetime | None = None
    annotation_method: str
    notes: str | None = None
    labels: list[GroundTruthLabel]

    @model_validator(mode="after")
    def validate_unique_labels(self) -> RetrievalGroundTruthFixture:
        chunk_ids = [label.chunk_id for label in self.labels]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("Ground truth contains duplicate chunk IDs.")
        return self


class BenchmarkEvidenceItem(BaseModel):
    evidence_id: str = Field(pattern=r"^E\d+$")
    evidence: RetrievedEvidence
    source: SourceDocument

    @model_validator(mode="after")
    def validate_relationship(self) -> BenchmarkEvidenceItem:
        if self.evidence.source_id != self.source.source_id:
            raise ValueError("Evidence source_id does not match its SourceDocument.")
        return self


class BenchmarkEvaluationFixture(BaseModel):
    schema_version: str
    case_id: str
    research_question: str
    candidate_set_sha256: str
    chunking_configuration_sha256: str
    isolated_collection_name: str
    embedding_configuration: dict[str, Any]
    observed_embedding_dimension: int | None
    vector_store_configuration: dict[str, Any]
    report_configuration: dict[str, Any]
    report_prompt_sha256: str
    ground_truth_status: Literal["validated", "draft"]
    report: str
    evidence: list[BenchmarkEvidenceItem]
    captured_at: datetime
    migration_source: str | None = None

    @model_validator(mode="after")
    def validate_evidence(self) -> BenchmarkEvaluationFixture:
        if not self.report.strip():
            raise ValueError("Evaluation fixture report cannot be empty.")
        if not self.evidence:
            raise ValueError("Evaluation fixture must contain retrieved evidence.")
        evidence_ids = [item.evidence_id for item in self.evidence]
        expected_ids = [f"E{index}" for index in range(1, len(self.evidence) + 1)]
        if evidence_ids != expected_ids:
            raise ValueError("Evidence IDs must be sequential and ordered.")
        ranks = [item.evidence.rank for item in self.evidence]
        if ranks != list(range(1, len(self.evidence) + 1)):
            raise ValueError("Retrieval ranks must be contiguous and ordered.")
        chunk_ids = [item.evidence.chunk_id for item in self.evidence]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("Evaluation fixture contains duplicate ranked chunks.")
        return self
