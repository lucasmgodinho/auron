"""
Inspect evaluators against a frozen grounded report evaluation fixture.

Flow:

Frozen evaluation fixture
→ citation validity
→ evidence utilization
→ citation correctness
→ citation coverage
→ faithfulness

The fixture already contains:

- the research question;
- the generated report;
- the exact E1, E2, ... evidence mapping;
- retrieved evidence;
- associated source documents.

This script intentionally does NOT perform:

- Tavily Search;
- Tavily Extract;
- document chunking;
- embeddings;
- vector indexing;
- semantic retrieval;
- report generation.

Real OpenAI API calls are performed only by semantic evaluators.

Run from:

    C:\\Auron\\backend

With:

    python -m app.scripts.inspect_evaluation
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from app.modules.competitive_intelligence.evaluation import (
    build_available_evidence_context,
    evaluate_citation_requirement,
    evaluate_citations,
    evaluate_cited_claim,
    evaluate_faithful_claim,
    extract_citation_ids,
    extract_cited_claims,
    extract_report_claims,
    summarize_citation_correctness,
    summarize_faithfulness,
)
from app.scripts.evaluation_fixture import (
    load_evaluation_fixture,
)

EVALUATION_FIXTURE_FILENAME = "microsoft_competitors_evaluation.json"


def print_section(
    title: str,
) -> None:
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)


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

    fixture = load_evaluation_fixture(
        filename=EVALUATION_FIXTURE_FILENAME,
    )

    print_section("FROZEN EVALUATION")

    print(f"Question: {fixture.research_question}")

    print(f"Captured at: {fixture.captured_at.isoformat()}")

    print(f"Evidence items: {len(fixture.evidence)}")

    # ------------------------------------------------------------------
    # Frozen evidence
    # ------------------------------------------------------------------

    print_section("1. FROZEN EVIDENCE")

    evidence_lookup = {item.evidence_id: item.evidence for item in fixture.evidence}

    source_lookup = {item.source.source_id: item.source for item in fixture.evidence}

    for item in fixture.evidence:
        evidence = item.evidence
        source = item.source

        print(
            f"{item.evidence_id} "
            f"| retrieval_rank={evidence.rank} "
            f"| distance={evidence.distance:.4f} "
            f"| source_rank={source.provider_rank} "
            f"| source={source.content_source} "
            f"| {source.title}"
        )

    # ------------------------------------------------------------------
    # Frozen report
    # ------------------------------------------------------------------

    print_section("2. FROZEN REPORT")

    print(fixture.report)

    # ------------------------------------------------------------------
    # Deterministic citation metrics
    # ------------------------------------------------------------------

    cited_claims = extract_cited_claims(fixture.report)

    available_evidence_ids = {item.evidence_id for item in fixture.evidence}

    cited_evidence_ids = {
        citation_id for claim in cited_claims for citation_id in claim.citation_ids
    }

    citation_metrics = evaluate_citations(
        available_evidence_ids=(available_evidence_ids),
        cited_evidence_ids=(cited_evidence_ids),
    )

    unknown_evidence_ids = cited_evidence_ids - available_evidence_ids

    unused_evidence_ids = available_evidence_ids - cited_evidence_ids

    print_section("3. CITATION METRICS")

    print(f"Cited claims: {len(cited_claims)}")

    print(f"Citation validity: {citation_metrics.citation_validity:.2%}")

    print(f"Evidence utilization: {citation_metrics.evidence_utilization:.2%}")

    print(f"Unused evidence: {sorted(unused_evidence_ids)}")

    if unknown_evidence_ids:
        print(f"Unknown citations: {sorted(unknown_evidence_ids)}")

    # ------------------------------------------------------------------
    # Citation correctness
    # ------------------------------------------------------------------

    print_section("4. CITATION CORRECTNESS")

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
        f"Fully supported claims: "
        f"{correctness_summary.supported}/"
        f"{correctness_summary.total_claims} "
        f"({correctness_summary.supported_rate:.2%})"
    )

    print(
        f"Partially supported claims: "
        f"{correctness_summary.partially_supported}/"
        f"{correctness_summary.total_claims} "
        f"({correctness_summary.partially_supported_rate:.2%})"
    )

    print(
        f"Unsupported claims: "
        f"{correctness_summary.unsupported}/"
        f"{correctness_summary.total_claims} "
        f"({correctness_summary.unsupported_rate:.2%})"
    )

    print(
        f"Supported components: "
        f"{correctness_summary.supported_components}/"
        f"{correctness_summary.total_components}"
    )

    print(f"Component support rate: {correctness_summary.component_support_rate:.2%}")

    problematic_correctness = [
        assessment for assessment in correctness_assessments if assessment.verdict != "supported"
    ]

    if problematic_correctness:
        print()
        print("Claims requiring review:")

        for assessment in problematic_correctness:
            supported_components = sum(component.supported for component in assessment.components)

            total_components = len(assessment.components)

            print()

            print(
                f"[{assessment.verdict} | "
                f"{supported_components}/"
                f"{total_components} "
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

    print_section("5. CITATION COVERAGE")

    report_claims = extract_report_claims(fixture.report)

    citation_required_claims = 0
    cited_required_claims = 0

    citation_required_report_claims: list[str] = []

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
            citation_required_report_claims.append(claim)

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
    # Faithfulness
    # ------------------------------------------------------------------

    print_section("6. FAITHFULNESS")

    available_evidence_context = build_available_evidence_context(
        evidence_lookup,
        source_lookup,
    )

    if not available_evidence_context.strip():
        raise RuntimeError("Available evidence context is empty.")

    faithfulness_assessments = []

    for index, claim in enumerate(
        citation_required_report_claims,
        start=1,
    ):
        print(f"Evaluating faithfulness {index}/{len(citation_required_report_claims)}...")

        assessment = evaluate_faithful_claim(
            claim=claim,
            evidence_context=(available_evidence_context),
        )

        faithfulness_assessments.append(assessment)

    faithfulness_summary = summarize_faithfulness(faithfulness_assessments)

    print()

    print(
        f"Faithful claims: "
        f"{faithfulness_summary.faithful}/"
        f"{faithfulness_summary.total_claims} "
        f"({faithfulness_summary.faithful_rate:.2%})"
    )

    print(
        f"Partially faithful claims: "
        f"{faithfulness_summary.partially_faithful}/"
        f"{faithfulness_summary.total_claims} "
        f"({faithfulness_summary.partially_faithful_rate:.2%})"
    )

    print(
        f"Unfaithful claims: "
        f"{faithfulness_summary.unfaithful}/"
        f"{faithfulness_summary.total_claims} "
        f"({faithfulness_summary.unfaithful_rate:.2%})"
    )

    print(
        f"Supported components: "
        f"{faithfulness_summary.supported_components}/"
        f"{faithfulness_summary.total_components}"
    )

    print(f"Faithfulness component support rate: {faithfulness_summary.component_support_rate:.2%}")

    problematic_faithfulness = [
        assessment for assessment in faithfulness_assessments if assessment.verdict != "faithful"
    ]

    if problematic_faithfulness:
        print()
        print("Claims requiring review:")

        for assessment in problematic_faithfulness:
            supported_components = sum(component.supported for component in assessment.components)

            total_components = len(assessment.components)

            print()

            print(
                f"[{assessment.verdict} | "
                f"{supported_components}/"
                f"{total_components} "
                f"components supported] "
                f"{assessment.claim}"
            )

            for component in assessment.components:
                if component.supported:
                    continue

                print(f"  - Unsupported: {component.component}")

                print(f"    Reason: {component.explanation}")

    faithfulness_by_claim = {
        assessment.claim: assessment for assessment in faithfulness_assessments
    }

    correctness_by_claim = {assessment.claim: assessment for assessment in correctness_assessments}

    print_section("7. CROSS-METRIC DIAGNOSTICS")

    for claim, correctness in correctness_by_claim.items():
        faithfulness = faithfulness_by_claim.get(claim)

        if faithfulness is None:
            continue

        if correctness.verdict != "supported" and faithfulness.verdict == "faithful":
            print()
            print("[CITATION / FAITHFULNESS MISMATCH]")

            print(claim)

            print(f"Correctness: {correctness.verdict}")

            print(f"Faithfulness: {faithfulness.verdict}")

            supporting_ids = sorted(
                {
                    evidence_id
                    for component in faithfulness.components
                    for evidence_id in component.supporting_evidence_ids
                }
            )

            print(f"Faithfulness supporting evidence: {supporting_ids}")

            cited_claim_by_text = {claim.claim: claim for claim in cited_claims}
            cited_claim = cited_claim_by_text.get(claim)

            cited_ids = cited_claim.citation_ids if cited_claim else []

            print(f"Cited evidence: {cited_ids}")

    # ------------------------------------------------------------------
    # Final summary
    # ------------------------------------------------------------------

    print_section("8. EVALUATION SUMMARY")

    print(f"Frozen evidence: {len(fixture.evidence)}")

    print()

    print(f"Citation validity: {citation_metrics.citation_validity:.2%}")

    print(f"Evidence utilization: {citation_metrics.evidence_utilization:.2%}")

    print()

    print(f"Fully supported claims: {correctness_summary.supported_rate:.2%}")

    print(f"Partially supported claims: {correctness_summary.partially_supported_rate:.2%}")

    print(f"Unsupported claims: {correctness_summary.unsupported_rate:.2%}")

    print(f"Citation component support rate: {correctness_summary.component_support_rate:.2%}")

    print()

    print(f"Citation coverage: {citation_coverage:.2%}")

    print()

    print(f"Faithful claims: {faithfulness_summary.faithful_rate:.2%}")

    print(f"Partially faithful claims: {faithfulness_summary.partially_faithful_rate:.2%}")

    print(f"Unfaithful claims: {faithfulness_summary.unfaithful_rate:.2%}")

    print(f"Faithfulness component support rate: {faithfulness_summary.component_support_rate:.2%}")


if __name__ == "__main__":
    main()
