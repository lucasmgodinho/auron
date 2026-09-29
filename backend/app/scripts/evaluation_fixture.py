"""
Utilities for creating, saving, and loading grounded report evaluation fixtures.

An evaluation fixture freezes the inputs required to evaluate a grounded report:

- research question;
- generated report;
- retrieved evidence with stable evidence IDs;
- source documents associated with each retrieved evidence;
- capture timestamp.

The fixture exists to make evaluator experiments reproducible.

It does not perform:

- search;
- document processing;
- embedding generation;
- vector retrieval;
- report generation;
- evaluation.

Those operations belong to other scripts.
"""

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from app.modules.competitive_intelligence.evidence import (
    RetrievedEvidence,
    SourceDocument,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class EvaluationEvidenceFixture(BaseModel):
    """
    Frozen retrieved evidence with its stable report citation ID.

    The evidence_id preserves the exact E1, E2, ... mapping used when the
    grounded report was generated.
    """

    evidence_id: str = Field(pattern=r"^E\d+$")

    evidence: RetrievedEvidence

    source: SourceDocument

    @model_validator(mode="after")
    def validate_source_relationship(
        self,
    ) -> EvaluationEvidenceFixture:
        if self.evidence.source_id != self.source.source_id:
            raise ValueError("RetrievedEvidence source_id does not match SourceDocument source_id.")

        return self


class GroundedReportFixture(BaseModel):
    """
    Frozen inputs for grounded report evaluation.

    This fixture allows citation and faithfulness evaluators to run against
    exactly the same report and retrieved evidence across multiple experiments.
    """

    research_question: str

    report: str

    evidence: list[EvaluationEvidenceFixture]

    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_fixture(
        self,
    ) -> GroundedReportFixture:
        if not self.research_question.strip():
            raise ValueError("Research question cannot be empty.")

        if not self.report.strip():
            raise ValueError("Grounded report cannot be empty.")

        if not self.evidence:
            raise ValueError("Evaluation fixture must contain evidence.")

        evidence_ids = [item.evidence_id for item in self.evidence]

        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("Evaluation fixture contains duplicate evidence IDs.")

        expected_ids = [
            f"E{index}"
            for index in range(
                1,
                len(self.evidence) + 1,
            )
        ]

        if evidence_ids != expected_ids:
            raise ValueError("Evidence IDs must be sequential and ordered as E1, E2, ..., En.")

        return self


def build_evaluation_fixture(
    *,
    research_question: str,
    report: str,
    retrieved: list[RetrievedEvidence],
    sources: list[SourceDocument],
) -> GroundedReportFixture:
    """
    Build an evaluation fixture from a completed grounded report run.

    Evidence IDs are assigned exactly once here based on retrieval order.
    This freezes the E1, E2, ... mapping used by the generated report.
    """

    if not retrieved:
        raise ValueError("Cannot build an evaluation fixture without retrieved evidence.")

    source_by_id = {source.source_id: source for source in sources}

    evidence_items: list[EvaluationEvidenceFixture] = []

    for index, evidence in enumerate(
        retrieved,
        start=1,
    ):
        source = source_by_id.get(evidence.source_id)

        if source is None:
            raise ValueError(f"SourceDocument not found for source_id={evidence.source_id}")

        evidence_items.append(
            EvaluationEvidenceFixture(
                evidence_id=f"E{index}",
                evidence=evidence,
                source=source,
            )
        )

    return GroundedReportFixture(
        research_question=research_question,
        report=report,
        evidence=evidence_items,
    )


def save_evaluation_fixture(
    *,
    fixture: GroundedReportFixture,
    filename: str,
) -> Path:
    """
    Save an evaluation fixture as formatted JSON.

    Existing fixture files are overwritten only when this function is called
    explicitly by a capture script.
    """

    FIXTURES_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    fixture_path = FIXTURES_DIR / filename

    fixture_path.write_text(
        fixture.model_dump_json(indent=2),
        encoding="utf-8",
    )

    return fixture_path


def load_evaluation_fixture(
    *,
    filename: str,
    expected_question: str | None = None,
) -> GroundedReportFixture:
    """
    Load and validate a frozen evaluation fixture.
    """

    fixture_path = FIXTURES_DIR / filename

    if not fixture_path.exists():
        raise FileNotFoundError(f"Evaluation fixture was not found at: {fixture_path}")

    fixture = GroundedReportFixture.model_validate_json(fixture_path.read_text(encoding="utf-8"))

    if expected_question is not None and fixture.research_question != expected_question:
        raise ValueError(
            "Evaluation fixture research question does not match the expected question."
        )

    return fixture
