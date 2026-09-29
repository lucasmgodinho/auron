"""
Utilities for storing and loading frozen SourceDocument fixtures used by
Competitive Intelligence development and evaluation scripts.

A search fixture represents the normalized boundary between the external search
provider and the internal AI pipeline:

Research question
→ SourceDocument[]

The fixture intentionally does not store downstream artifacts such as:

- EvidenceChunk objects;
- embeddings;
- vector store state;
- RetrievedEvidence objects;
- grounded context;
- generated reports;
- evaluation results.

Keeping the fixture at the SourceDocument boundary allows downstream pipeline
components to be modified and compared while preserving exactly the same search
input.

This provides reproducible experiments without repeatedly consuming Tavily
credits or allowing live search results to change between evaluation runs.

Fixtures are intended only for development and evaluation.

Production requests must continue retrieving fresh information through the
configured search provider.
"""

from pathlib import Path

from pydantic import BaseModel

from app.modules.competitive_intelligence.evidence import (
    SourceDocument,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class SearchFixture(BaseModel):
    research_question: str
    documents: list[SourceDocument]


def save_search_fixture(
    filename: str,
    research_question: str,
    documents: list[SourceDocument],
) -> Path:
    FIXTURES_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    fixture = SearchFixture(
        research_question=research_question,
        documents=documents,
    )

    path = FIXTURES_DIR / filename

    path.write_text(
        fixture.model_dump_json(indent=2),
        encoding="utf-8",
    )

    return path


def load_search_fixture(
    filename: str,
    expected_question: str | None = None,
) -> SearchFixture:
    path = FIXTURES_DIR / filename

    if not path.exists():
        raise RuntimeError(f"Search fixture not found: {path}")

    fixture = SearchFixture.model_validate_json(path.read_text(encoding="utf-8"))

    if expected_question is not None and fixture.research_question != expected_question:
        raise ValueError(
            "Fixture research question does not match "
            "the current research question.\n"
            f"Fixture: {fixture.research_question}\n"
            f"Current: {expected_question}"
        )

    return fixture
