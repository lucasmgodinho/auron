"""
Utilities for loading and validating retrieval ground truth fixtures.

Ground truth files contain human-reviewed relevance labels for every
candidate chunk generated for a research question.

Relevance scale:

0 = irrelevant
1 = partially relevant
2 = highly relevant

These fixtures are intended for deterministic offline retrieval evaluation.
They are tied to the chunking configuration used when the fixture was created.
"""

import json
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class RetrievalRelevanceLabel(BaseModel):
    """Human-reviewed relevance label for a single chunk."""

    chunk_id: str = Field(min_length=1)
    relevance: int = Field(ge=0, le=2)


class RetrievalGroundTruth(BaseModel):
    """Ground truth relevance labels for one research question."""

    research_question: str = Field(min_length=1)
    labels: list[RetrievalRelevanceLabel]

    @model_validator(mode="after")
    def validate_labels(self) -> RetrievalGroundTruth:
        if not self.labels:
            raise ValueError("Ground truth must contain at least one relevance label.")

        chunk_ids = [label.chunk_id for label in self.labels]

        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("Ground truth contains duplicate chunk IDs.")

        return self


def load_retrieval_ground_truth(
    filename: str,
    *,
    expected_question: str | None = None,
) -> RetrievalGroundTruth:
    """
    Load and validate a retrieval ground truth fixture.

    Args:
        filename:
            Fixture filename stored inside app/scripts/fixtures.

        expected_question:
            Optional research question used to verify that the loaded fixture
            belongs to the expected benchmark case.

    Returns:
        Validated RetrievalGroundTruth instance.

    Raises:
        FileNotFoundError:
            If the fixture does not exist.

        ValueError:
            If the research question does not match expected_question.

        ValidationError:
            If the JSON structure does not satisfy the Pydantic models.
    """

    path = FIXTURES_DIR / filename

    if not path.exists():
        raise FileNotFoundError(f"Retrieval ground truth fixture not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    ground_truth = RetrievalGroundTruth.model_validate(data)

    if expected_question is not None and ground_truth.research_question != expected_question:
        raise ValueError(
            "Ground truth research question does not match the expected question. "
            f"Expected: {expected_question!r}. "
            f"Received: {ground_truth.research_question!r}."
        )

    return ground_truth


def build_relevance_lookup(
    ground_truth: RetrievalGroundTruth,
) -> dict[str, int]:
    """
    Convert ground truth labels into a chunk ID -> relevance lookup.

    This representation is consumed directly by retrieval evaluation metrics.
    """

    return {label.chunk_id: label.relevance for label in ground_truth.labels}
