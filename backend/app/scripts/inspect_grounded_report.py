"""
Inspect the grounded competitive intelligence pipeline using a frozen fixture.

The script focuses on the most useful information for evaluating:

- source acquisition;
- document chunking;
- semantic retrieval;
- grounded report generation;
- citation validity;
- evidence utilization;
- citation correctness;
- citation coverage.

The full grounded context and successful claim-level evaluations are intentionally
not printed to keep terminal output concise.

No Tavily Search or Tavily Extract request is performed.

Real OpenAI API calls are still performed for:

- embeddings;
- report generation;
- citation correctness evaluation;
- citation requirement evaluation.

Run from:

    C:\\Auron\\backend

With:

    python -m app.scripts.inspect_grounded_report
"""

import os
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv

from app.modules.competitive_intelligence.context_builder import (
    build_research_context,
)
from app.modules.competitive_intelligence.document_processing import (
    chunk_document,
)
from app.modules.competitive_intelligence.evaluation import (
    build_evidence_lookup,
    build_source_lookup,
    evaluate_citation_requirement,
    evaluate_citations,
    evaluate_cited_claim,
    extract_citation_ids,
    extract_cited_claims,
    extract_report_claims,
    summarize_citation_correctness,
)
from app.modules.competitive_intelligence.report_generation import (
    generate_grounded_report,
)
from app.modules.competitive_intelligence.vector_store import (
    create_vector_store,
    index_chunks,
    retrieve_evidence,
)
from app.scripts.search_fixture import load_search_fixture

RESEARCH_QUESTION = "Who are Microsoft's main competitors in the technology sector?"

FIXTURE_FILENAME = "microsoft_competitors.json"

TOP_K = 5
RETRIEVAL_PREVIEW_CHARS = 180


def print_section(title: str) -> None:
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)


def compact_text(
    text: str,
    *,
    max_length: int,
) -> str:
    normalized = " ".join(text.split())

    if len(normalized) <= max_length:
        return normalized

    return normalized[: max_length - 3] + "..."


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

    print_section("GROUNDED REPORT INSPECTION")

    print(f"Question: {RESEARCH_QUESTION}")

    fixture = load_search_fixture(
        filename=FIXTURE_FILENAME,
        expected_question=RESEARCH_QUESTION,
    )

    documents = list(fixture.documents)

    if not documents:
        raise RuntimeError("The search fixture contains no documents.")

    # ------------------------------------------------------------------
    # Sources
    # ------------------------------------------------------------------

    print_section("1. SELECTED SOURCES")

    provenance_counts = Counter(document.content_source for document in documents)

    print(f"Documents: {len(documents)}")

    print("Provenance: " + ", ".join(f"{key}={value}" for key, value in provenance_counts.items()))

    for document in documents:
        raw_chars = len(document.raw_content) if document.raw_content else 0

        print(
            f"- rank={document.provider_rank} "
            f"score={document.provider_score:.4f} "
            f"source={document.content_source} "
            f"raw_chars={raw_chars} "
            f"| {document.title}"
        )

    # ------------------------------------------------------------------
    # Chunking
    # ------------------------------------------------------------------

    chunks = []

    for document in documents:
        chunks.extend(chunk_document(document))

    if not chunks:
        raise RuntimeError("No evidence chunks were generated.")

    chunks_by_source = defaultdict(list)

    for chunk in chunks:
        chunks_by_source[chunk.source_id].append(chunk)

    source_by_id = {document.source_id: document for document in documents}

    print_section("2. CHUNKING")

    print(f"Total chunks: {len(chunks)}")

    for source_id, source_chunks in chunks_by_source.items():
        source = source_by_id[source_id]

        total_tokens = sum(chunk.token_count for chunk in source_chunks)

        print(
            f"- source_rank={source.provider_rank} "
            f"chunks={len(source_chunks)} "
            f"tokens={total_tokens} "
            f"| {source.title}"
        )

    # ------------------------------------------------------------------
    # Vector store and retrieval
    # ------------------------------------------------------------------

    vector_store = create_vector_store()

    index_chunks(
        vector_store,
        chunks,
    )

    retrieved = retrieve_evidence(
        vector_store,
        RESEARCH_QUESTION,
        top_k=TOP_K,
    )

    if not retrieved:
        raise RuntimeError("No evidence was retrieved.")

    chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}

    print_section("3. RETRIEVAL")

    print(f"Indexed chunks: {len(chunks)}")

    print(f"Retrieved: {len(retrieved)}")

    for evidence_index, evidence in enumerate(
        retrieved,
        start=1,
    ):
        source = source_by_id[evidence.source_id]

        chunk = chunk_by_id[evidence.chunk_id]

        preview = compact_text(
            evidence.text,
            max_length=RETRIEVAL_PREVIEW_CHARS,
        )

        print()
        print(
            f"E{evidence_index} "
            f"| retrieval_rank={evidence.rank} "
            f"| distance={evidence.distance:.4f} "
            f"| source_rank={source.provider_rank} "
            f"| source={source.content_source} "
            f"| chunk={chunk.chunk_index}"
        )

        print(f"  {source.title}")

        print(f"  {preview}")

    # ------------------------------------------------------------------
    # Grounded report
    # ------------------------------------------------------------------

    context = build_research_context(
        retrieved,
        documents,
    )

    if not context.strip():
        raise RuntimeError("Grounded research context is empty.")

    report = generate_grounded_report(
        RESEARCH_QUESTION,
        context,
    )

    if not report.strip():
        raise RuntimeError("Grounded report is empty.")

    print_section("4. GENERATED REPORT")

    print(report)

    # ------------------------------------------------------------------
    # Deterministic citation metrics
    # ------------------------------------------------------------------

    available_evidence_ids = {
        f"E{index}"
        for index in range(
            1,
            len(retrieved) + 1,
        )
    }

    cited_claims = extract_cited_claims(report)

    cited_evidence_ids = {
        citation_id for claim in cited_claims for citation_id in claim.citation_ids
    }

    citation_metrics = evaluate_citations(
        available_evidence_ids=(available_evidence_ids),
        cited_evidence_ids=(cited_evidence_ids),
    )

    unknown_evidence_ids = cited_evidence_ids - available_evidence_ids

    unused_evidence_ids = available_evidence_ids - cited_evidence_ids

    print_section("5. CITATION METRICS")

    print(f"Cited claims: {len(cited_claims)}")

    print(f"Citation validity: {citation_metrics.citation_validity:.2%}")

    print(f"Evidence utilization: {citation_metrics.evidence_utilization:.2%}")

    print(f"Unused evidence: {sorted(unused_evidence_ids)}")

    if unknown_evidence_ids:
        print(f"Unknown citations: {sorted(unknown_evidence_ids)}")

    # ------------------------------------------------------------------
    # Citation correctness
    # ------------------------------------------------------------------

    print_section("6. CITATION CORRECTNESS")

    evidence_lookup = build_evidence_lookup(retrieved)

    source_lookup = build_source_lookup(documents)

    correctness_assessments = []

    for index, claim in enumerate(
        cited_claims,
        start=1,
    ):
        print(f"Evaluating correctness {index}/{len(cited_claims)}...")

        assessment = evaluate_cited_claim(
            claim=claim,
            evidence_lookup=(evidence_lookup),
            source_lookup=(source_lookup),
        )

        correctness_assessments.append(assessment)

    correctness_summary = summarize_citation_correctness(correctness_assessments)

    print()
    print(
        f"Supported: "
        f"{correctness_summary.supported}/"
        f"{correctness_summary.total_claims} "
        f"({correctness_summary.supported_rate:.2%})"
    )

    print(
        f"Partially supported: "
        f"{correctness_summary.partially_supported}/"
        f"{correctness_summary.total_claims} "
        f"({correctness_summary.partially_supported_rate:.2%})"
    )

    print(
        f"Unsupported: "
        f"{correctness_summary.unsupported}/"
        f"{correctness_summary.total_claims} "
        f"({correctness_summary.unsupported_rate:.2%})"
    )

    problematic_assessments = [
        assessment for assessment in correctness_assessments if assessment.verdict != "supported"
    ]

    if problematic_assessments:
        print()
        print("Claims requiring review:")

        for assessment in problematic_assessments:
            supported_components = sum(component.supported for component in assessment.components)

            total_components = len(assessment.components)

            print()

            print(
                f"[{assessment.verdict} | "
                f"{supported_components}/{total_components} "
                f"components supported] "
                f"{assessment.claim}"
            )

            unsupported_components = [
                component for component in assessment.components if not component.supported
            ]

            for component in unsupported_components:
                print(f"  - Unsupported: {component.component}")

                print(f"    Reason: {component.explanation}")

    # ------------------------------------------------------------------
    # Citation coverage
    # ------------------------------------------------------------------

    print_section("7. CITATION COVERAGE")

    report_claims = extract_report_claims(report)

    citation_required_claims = 0
    cited_required_claims = 0

    uncited_required = []
    cited_but_not_required = []

    for index, claim in enumerate(
        report_claims,
        start=1,
    ):
        print(f"Evaluating requirement {index}/{len(report_claims)}...")

        requirement = evaluate_citation_requirement(claim)

        citation_ids = extract_citation_ids(claim)

        has_citation = bool(citation_ids)

        if requirement.requires_citation:
            citation_required_claims += 1

            if has_citation:
                cited_required_claims += 1
            else:
                uncited_required.append(
                    (
                        claim,
                        requirement.explanation,
                    )
                )

        elif has_citation:
            cited_but_not_required.append(
                (
                    claim,
                    requirement.explanation,
                )
            )

    uncited_required_claims = citation_required_claims - cited_required_claims

    citation_coverage = (
        cited_required_claims / citation_required_claims if citation_required_claims else 1.0
    )

    print()
    print(f"Extracted claims: {len(report_claims)}")

    print(f"Citation-required claims: {citation_required_claims}")

    print(f"Cited required claims: {cited_required_claims}")

    print(f"Uncited required claims: {uncited_required_claims}")

    print(f"Citation coverage: {citation_coverage:.2%}")

    if uncited_required:
        print()
        print("Missing citations:")

        for claim, explanation in uncited_required:
            print()
            print(f"- {claim}")

            print(f"  Reason: {explanation}")

    if cited_but_not_required:
        print()
        print("Diagnostic: cited claims classified as not requiring citations:")

        for claim, explanation in cited_but_not_required:
            print()
            print(f"- {claim}")

            print(f"  Reason: {explanation}")

    # ------------------------------------------------------------------
    # Final summary
    # ------------------------------------------------------------------

    print_section("8. EVALUATION SUMMARY")

    print(f"Sources: {len(documents)}")

    print(f"Chunks: {len(chunks)}")

    print(f"Retrieved evidence: {len(retrieved)}")

    print(f"Citation validity: {citation_metrics.citation_validity:.2%}")

    print(f"Evidence utilization: {citation_metrics.evidence_utilization:.2%}")

    print(f"Fully supported claims: {correctness_summary.supported_rate:.2%}")

    print(f"Partially supported claims: {correctness_summary.partially_supported_rate:.2%}")

    print(f"Unsupported claims: {correctness_summary.unsupported_rate:.2%}")

    print(f"Component support rate: {correctness_summary.component_support_rate:.2%}")

    print(f"Citation coverage: {citation_coverage:.2%}")


if __name__ == "__main__":
    main()
