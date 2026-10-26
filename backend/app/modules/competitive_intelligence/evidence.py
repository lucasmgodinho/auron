from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class SourceProvenance(BaseModel):
    """Metadata of each discovery, including aliases collapsed by deduplication."""

    source_id: str
    provider_result_id: str | None = None
    research_query: str
    title: str
    url: HttpUrl
    domain: str
    provider_score: float | None = None
    provider_rank: int | None = None

    content_source: (
        Literal[
            "search_raw",
            "extract_raw",
            "search_content",
        ]
        | None
    ) = None

    published_date: datetime | None = None
    retrieved_at: datetime


class SourceDocument(SourceProvenance):
    content: str
    raw_content: str | None = None
    provenance: list[SourceProvenance] = Field(default_factory=list)


class EvidenceChunk(BaseModel):
    chunk_id: str
    source_id: str
    research_query: str

    text: str

    chunk_index: int
    token_count: int


class RetrievedEvidence(BaseModel):
    chunk_id: str
    source_id: str
    text: str
    query: str

    distance: float
    rank: int
    source: SourceDocument | None = None
