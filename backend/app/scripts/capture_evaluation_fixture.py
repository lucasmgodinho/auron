"""
Capture a frozen grounded report evaluation fixture.

Flow:

Frozen SourceDocument[]
→ document processing
→ chunking
→ embeddings
→ Chroma indexing
→ semantic retrieval
→ grounded context
→ report generation
→ evaluation fixture

The resulting fixture freezes:

- the research question;
- the generated report;
- the exact E1, E2, ... evidence mapping;
- RetrievedEvidence objects;
- associated SourceDocuments.

This script does NOT run evaluation metrics or judges.

Real OpenAI API calls are performed for:

- embeddings;
- report generation.

No Tavily Search or Tavily Extract request is performed.

Run from:

    C:\\Auron\\backend

With:

    python -m app.scripts.capture_evaluation_fixture
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from app.modules.competitive_intelligence.context_builder import (
    build_research_context,
)
from app.modules.competitive_intelligence.document_processing import (
    chunk_document,
)
from app.modules.competitive_intelligence.report_generation import (
    generate_grounded_report,
)
from app.modules.competitive_intelligence.vector_store import (
    create_vector_store,
    index_chunks,
    retrieve_evidence,
)
from app.scripts.evaluation_fixture import (
    build_evaluation_fixture,
    save_evaluation_fixture,
)
from app.scripts.search_fixture import (
    load_search_fixture,
)

RESEARCH_QUESTION = "Who are Microsoft's main competitors in the technology sector?"

SEARCH_FIXTURE_FILENAME = "microsoft_competitors.json"

EVALUATION_FIXTURE_FILENAME = "microsoft_competitors_evaluation.json"

TOP_K = 5


def load_environment() -> None:
    project_root = Path(__file__).resolve().parents[3]

    env_file = project_root / ".env"

    if not env_file.exists():
        raise RuntimeError(f".env file was not found at: {env_file}")

    load_dotenv(env_file)

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY was not found.")


def main() -> None:
    load_environment()

    print("=" * 80)
    print("EVALUATION FIXTURE CAPTURE")
    print("=" * 80)

    print()
    print(f"Question: {RESEARCH_QUESTION}")

    print()
    print("Loading frozen search fixture...")

    search_fixture = load_search_fixture(
        filename=SEARCH_FIXTURE_FILENAME,
        expected_question=RESEARCH_QUESTION,
    )

    documents = list(search_fixture.documents)

    if not documents:
        raise RuntimeError("The search fixture contains no documents.")

    print(f"Loaded {len(documents)} SourceDocuments.")

    print()
    print("Processing and chunking documents...")

    chunks = []

    for document in documents:
        chunks.extend(chunk_document(document))

    if not chunks:
        raise RuntimeError("No evidence chunks were generated.")

    print(f"Generated {len(chunks)} chunks.")

    print()
    print("Creating vector store and indexing chunks...")

    vector_store = create_vector_store()

    index_chunks(
        vector_store,
        chunks,
    )

    print(f"Indexed {len(chunks)} chunks.")

    print()
    print(f"Retrieving top {TOP_K} evidence chunks...")

    retrieved = retrieve_evidence(
        vector_store,
        RESEARCH_QUESTION,
        top_k=TOP_K,
    )

    if not retrieved:
        raise RuntimeError("No evidence was retrieved.")

    print(f"Retrieved {len(retrieved)} evidence chunks.")

    for index, evidence in enumerate(
        retrieved,
        start=1,
    ):
        print(
            f"  E{index} "
            f"| rank={evidence.rank} "
            f"| distance={evidence.distance:.4f} "
            f"| chunk={evidence.chunk_id}"
        )

    print()
    print("Building grounded research context...")

    context = build_research_context(
        retrieved,
        documents,
    )

    if not context.strip():
        raise RuntimeError("Grounded research context is empty.")

    print()
    print("Generating grounded report...")

    report = generate_grounded_report(
        RESEARCH_QUESTION,
        context,
    )

    if not report.strip():
        raise RuntimeError("Grounded report is empty.")

    print("Grounded report generated.")

    print()
    print("Building evaluation fixture...")

    fixture = build_evaluation_fixture(
        research_question=RESEARCH_QUESTION,
        report=report,
        retrieved=retrieved,
        sources=documents,
    )

    fixture_path = save_evaluation_fixture(
        fixture=fixture,
        filename=(EVALUATION_FIXTURE_FILENAME),
    )

    print()
    print("-" * 80)
    print("EVALUATION FIXTURE SAVED")
    print("-" * 80)

    print()
    print(f"Evidence items: {len(fixture.evidence)}")

    print(f"Report characters: {len(fixture.report)}")

    print(f"Captured at: {fixture.captured_at.isoformat()}")

    print(f"Fixture: {fixture_path}")

    print()
    print(
        "This fixture is now frozen. "
        "Do not recapture it automatically "
        "while comparing evaluator changes."
    )


if __name__ == "__main__":
    main()
