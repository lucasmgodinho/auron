"""Persist deterministic retrieval metrics and separate LLM-judge observations."""

import argparse
import json
import os
from collections import Counter
from statistics import fmean
from typing import Any

from dotenv import load_dotenv

from app.modules.competitive_intelligence.evaluation import (
    build_available_evidence_context,
    build_evidence_lookup,
    build_source_lookup,
    evaluate_citation_correctness,
    evaluate_citation_requirement,
    evaluate_citations,
    evaluate_faithful_claim,
    extract_citation_ids,
    extract_cited_claims,
    extract_report_claims,
    summarize_citation_correctness,
    summarize_faithfulness,
)
from app.modules.competitive_intelligence.retrieval_evaluation import (
    evaluate_retrieval,
)

from .benchmark_io import (
    BROAD_RELEVANCE_THRESHOLD,
    CASES,
    KS,
    REPOSITORY_ROOT,
    RESULTS_ROOT,
    STRICT_RELEVANCE_THRESHOLD,
    TOP_K,
    candidates_path,
    case_result_dir,
    evaluation_fixture_path,
    freeze_benchmark,
    get_case,
    ground_truth_path,
    load_json_model,
    load_manifest,
    utc_now,
    validate_evaluation_fixture,
    write_checksums,
    write_json_guarded,
    write_text_guarded,
)
from .benchmark_models import (
    BenchmarkEvaluationFixture,
    RetrievalCandidatesFixture,
    RetrievalGroundTruthFixture,
)

EvaluationMode = str


def _load_openai_environment() -> None:
    env_path = REPOSITORY_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for generation evaluation.")


def _metrics_by_k(summary: Any) -> dict[str, dict[str, float]]:
    return {
        str(item.k): {
            "precision": item.precision,
            "recall": item.recall,
            "ndcg": item.ndcg,
        }
        for item in summary.metrics_at_k
    }


def evaluate_retrieval_case(
    fixture: BenchmarkEvaluationFixture,
    candidates: RetrievalCandidatesFixture,
    ground_truth: RetrievalGroundTruthFixture,
) -> dict[str, Any]:
    relevance_lookup = {
        label.chunk_id: label.relevance
        for label in ground_truth.labels
        if label.relevance is not None
    }
    ranked_ids = [item.evidence.chunk_id for item in fixture.evidence]
    broad = evaluate_retrieval(
        ranked_chunk_ids=ranked_ids,
        relevance_lookup=relevance_lookup,
        ks=KS,
        relevance_threshold=BROAD_RELEVANCE_THRESHOLD,
    )
    strict = evaluate_retrieval(
        ranked_chunk_ids=ranked_ids,
        relevance_lookup=relevance_lookup,
        ks=KS,
        relevance_threshold=STRICT_RELEVANCE_THRESHOLD,
    )
    distribution = Counter(relevance_lookup.values())
    source_ids = {candidate.source_id for candidate in candidates.candidates}

    def relevant_ids(threshold: int) -> set[str]:
        return {
            chunk_id
            for chunk_id, relevance in relevance_lookup.items()
            if relevance >= threshold
        }

    broad_relevant = relevant_ids(BROAD_RELEVANCE_THRESHOLD)
    strict_relevant = relevant_ids(STRICT_RELEVANCE_THRESHOLD)
    ranked_set = set(ranked_ids)

    ranking = [
        {
            "rank": item.evidence.rank,
            "evidence_id": item.evidence_id,
            "chunk_id": item.evidence.chunk_id,
            "source_id": item.evidence.source_id,
            "distance": item.evidence.distance,
            "ground_truth_relevance": relevance_lookup[item.evidence.chunk_id],
        }
        for item in fixture.evidence
    ]
    return {
        "metric_type": "deterministic",
        "broad_relevance": {
            "threshold": BROAD_RELEVANCE_THRESHOLD,
            "metrics_at_k": _metrics_by_k(broad),
            "reciprocal_rank": broad.reciprocal_rank,
        },
        "strict_relevance": {
            "threshold": STRICT_RELEVANCE_THRESHOLD,
            "metrics_at_k": _metrics_by_k(strict),
            "reciprocal_rank": strict.reciprocal_rank,
        },
        "graded_relevance": {
            "gain": "2^relevance - 1",
            "ndcg_at_k": {
                str(item.k): item.ndcg for item in broad.metrics_at_k
            },
        },
        "diagnostics": {
            "candidate_count": len(candidates.candidates),
            "document_source_count": len(source_ids),
            "relevance_distribution": {
                "0": distribution[0],
                "1": distribution[1],
                "2": distribution[2],
            },
            "theoretical_recall_ceiling_at_k": {
                "broad": {
                    str(k): min(k, len(broad_relevant)) / len(broad_relevant)
                    if broad_relevant
                    else 0.0
                    for k in KS
                },
                "strict": {
                    str(k): min(k, len(strict_relevant)) / len(strict_relevant)
                    if strict_relevant
                    else 0.0
                    for k in KS
                },
            },
            "distinct_sources_in_top_k": len(
                {item.evidence.source_id for item in fixture.evidence[:TOP_K]}
            ),
            "annotation_coverage": len(relevance_lookup) / len(candidates.candidates),
            "broad_relevant_chunks_retrieved": sorted(broad_relevant & ranked_set),
            "broad_relevant_chunks_missed": sorted(broad_relevant - ranked_set),
            "strict_relevant_chunks_retrieved": sorted(strict_relevant & ranked_set),
            "strict_relevant_chunks_missed": sorted(strict_relevant - ranked_set),
            "frozen_ranking": ranking,
        },
    }


def evaluate_generation_case(fixture: BenchmarkEvaluationFixture) -> dict[str, Any]:
    retrieved = [item.evidence for item in fixture.evidence]
    source_by_id = {item.source.source_id: item.source for item in fixture.evidence}
    sources = list(source_by_id.values())
    available_ids = {item.evidence_id for item in fixture.evidence}
    cited_ids = set(extract_citation_ids(fixture.report))
    citation_metrics = evaluate_citations(available_ids, cited_ids)

    cited_claims = extract_cited_claims(fixture.report)
    correctness_assessments = evaluate_citation_correctness(
        cited_claims,
        retrieved,
        sources,
    )
    correctness = summarize_citation_correctness(correctness_assessments)

    evidence_lookup = build_evidence_lookup(retrieved)
    source_lookup = build_source_lookup(sources)
    evidence_context = build_available_evidence_context(evidence_lookup, source_lookup)
    report_claims = extract_report_claims(fixture.report)
    faithfulness_assessments = [
        evaluate_faithful_claim(claim=claim, evidence_context=evidence_context)
        for claim in report_claims
    ]
    faithfulness = summarize_faithfulness(faithfulness_assessments)

    coverage_claims: list[dict[str, Any]] = []
    required_count = 0
    cited_required_count = 0
    for claim in report_claims:
        requirement = evaluate_citation_requirement(claim)
        claim_citations = extract_citation_ids(claim)
        if requirement.requires_citation:
            required_count += 1
            if claim_citations:
                cited_required_count += 1
        coverage_claims.append(
            {
                "claim": claim,
                "citation_ids": claim_citations,
                "requires_citation": requirement.requires_citation,
                "explanation": requirement.explanation,
            }
        )
    coverage = cited_required_count / required_count if required_count else 1.0

    return {
        "deterministic": {
            "citation_validity": citation_metrics.citation_validity,
            "evidence_utilization": citation_metrics.evidence_utilization,
            "available_evidence_ids": sorted(available_ids),
            "cited_evidence_ids": sorted(cited_ids),
        },
        "llm_judge_observations": {
            "citation_correctness": {
                "summary": correctness.model_dump(mode="json"),
                "per_claim_assessments": [
                    assessment.model_dump(mode="json")
                    for assessment in correctness_assessments
                ],
            },
            "citation_coverage": {
                "coverage": coverage,
                "citation_required_claims": required_count,
                "cited_required_claims": cited_required_count,
                "uncited_required_claims": required_count - cited_required_count,
                "per_claim_assessments": coverage_claims,
            },
            "faithfulness": {
                "summary": faithfulness.model_dump(mode="json"),
                "per_claim_assessments": [
                    assessment.model_dump(mode="json")
                    for assessment in faithfulness_assessments
                ],
            },
            "correctness_vs_faithfulness": {
                "citation_correctness_component_support_rate": (
                    correctness.component_support_rate
                ),
                "faithfulness_component_support_rate": (
                    faithfulness.component_support_rate
                ),
                "interpretation": (
                    "Citation correctness judges only cited evidence; faithfulness judges all "
                    "retrieved evidence. They are reported separately and are not a quality score."
                ),
            },
        },
    }


def _load_case_artifacts(
    case_id: str,
) -> tuple[
    BenchmarkEvaluationFixture,
    RetrievalCandidatesFixture,
    RetrievalGroundTruthFixture,
]:
    fixture = load_json_model(
        evaluation_fixture_path(case_id), BenchmarkEvaluationFixture
    )
    candidates = load_json_model(candidates_path(case_id), RetrievalCandidatesFixture)
    ground_truth = load_json_model(
        ground_truth_path(case_id), RetrievalGroundTruthFixture
    )
    validate_evaluation_fixture(fixture, candidates, ground_truth)
    if len(fixture.evidence) != min(TOP_K, len(candidates.candidates)):
        raise ValueError("Frozen ranking length is incompatible with benchmark top_k.")
    return fixture, candidates, ground_truth


def _result_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# {result['case_id']} V2 Result",
        "",
        f"Question: {result['research_question']}",
        "",
    ]
    retrieval = result.get("retrieval")
    if retrieval:
        lines.extend(["## Deterministic retrieval", ""])
        for label, key in (("Broad", "broad_relevance"), ("Strict", "strict_relevance")):
            metrics = retrieval[key]
            lines.append(f"### {label} relevance (threshold >= {metrics['threshold']})")
            lines.append("")
            lines.append("| K | Precision | Recall | nDCG |")
            lines.append("|---:|---:|---:|---:|")
            for k in KS:
                row = metrics["metrics_at_k"][str(k)]
                lines.append(
                    f"| {k} | {row['precision']:.4f} | {row['recall']:.4f} | "
                    f"{row['ndcg']:.4f} |"
                )
            lines.append("")
            lines.append(f"Reciprocal Rank: {metrics['reciprocal_rank']:.4f}")
            lines.append("")
    generation = result.get("generation")
    if generation:
        deterministic = generation["deterministic"]
        observations = generation["llm_judge_observations"]
        lines.extend(
            [
                "## Generation evaluation",
                "",
                "Deterministic metrics:",
                "",
                f"- Citation validity: {deterministic['citation_validity']:.4f}",
                f"- Evidence utilization: {deterministic['evidence_utilization']:.4f}",
                "",
                "LLM-judge observations:",
                "",
                "- Citation correctness component support rate: "
                f"{observations['citation_correctness']['summary']['component_support_rate']:.4f}",
                "- Citation coverage: "
                f"{observations['citation_coverage']['coverage']:.4f}",
                "- Faithfulness component support rate: "
                f"{observations['faithfulness']['summary']['component_support_rate']:.4f}",
                "",
                "No combined quality score is calculated.",
            ]
        )
    return "\n".join(lines)


def evaluate_case(
    case_id: str,
    *,
    mode: EvaluationMode,
    allow_overwrite: bool,
) -> dict[str, Any]:
    case = get_case(case_id)
    fixture, candidates, ground_truth = _load_case_artifacts(case_id)
    result_path = case_result_dir(case_id) / "result.json"
    result: dict[str, Any] = {}
    if result_path.exists():
        result = json.loads(result_path.read_text(encoding="utf-8"))
    result.update(
        {
            "schema_version": "1.0.0",
            "benchmark_id": load_manifest().benchmark_id,
            "benchmark_version": load_manifest().benchmark_version,
            "case_id": case.case_id,
            "research_question": case.research_question,
            "evaluated_at": utc_now().isoformat(),
            "mode": mode,
        }
    )
    if mode in {"retrieval-only", "full"}:
        result["retrieval"] = evaluate_retrieval_case(
            fixture, candidates, ground_truth
        )
    if mode in {"generation-only", "full"}:
        _load_openai_environment()
        result["generation"] = evaluate_generation_case(fixture)

    result_dir = case_result_dir(case_id)
    write_json_guarded(
        result_dir / "result.json",
        result,
        allow_overwrite=allow_overwrite,
    )
    write_text_guarded(
        result_dir / "result.md",
        _result_markdown(result),
        allow_overwrite=allow_overwrite,
    )
    return result


def aggregate_results(
    results: list[dict[str, Any]],
    *,
    failed: list[dict[str, str]],
    skipped: list[dict[str, str]],
) -> dict[str, Any]:
    retrieval_results = [result["retrieval"] for result in results if result.get("retrieval")]

    def mean_metric(section: str, metric: str, k: int | None = None) -> float | None:
        if not retrieval_results:
            return None
        values = []
        for retrieval in retrieval_results:
            if k is None:
                values.append(retrieval[section][metric])
            else:
                values.append(retrieval[section]["metrics_at_k"][str(k)][metric])
        return fmean(values)

    retrieval_macro = {
        "broad": {
            "mean_precision_at_k": {
                str(k): mean_metric("broad_relevance", "precision", k) for k in KS
            },
            "mean_recall_at_k": {
                str(k): mean_metric("broad_relevance", "recall", k) for k in KS
            },
            "mrr": mean_metric("broad_relevance", "reciprocal_rank"),
        },
        "strict": {
            "mean_precision_at_k": {
                str(k): mean_metric("strict_relevance", "precision", k) for k in KS
            },
            "mean_recall_at_k": {
                str(k): mean_metric("strict_relevance", "recall", k) for k in KS
            },
            "mrr": mean_metric("strict_relevance", "reciprocal_rank"),
        },
        "mean_ndcg_at_k": {
            str(k): (
                fmean(
                    retrieval["graded_relevance"]["ndcg_at_k"][str(k)]
                    for retrieval in retrieval_results
                )
                if retrieval_results
                else None
            )
            for k in KS
        },
    }
    return {
        "schema_version": "1.0.0",
        "benchmark_id": load_manifest().benchmark_id,
        "benchmark_version": load_manifest().benchmark_version,
        "generated_at": utc_now().isoformat(),
        "aggregation_policy": "macro average across valid cases",
        "valid_case_count": len(results),
        "failed_case_count": len(failed),
        "skipped_case_count": len(skipped),
        "failed_cases": failed,
        "skipped_cases": skipped,
        "dataset_distribution": [
            {
                "case_id": result["case_id"],
                "candidate_count": result.get("retrieval", {})
                .get("diagnostics", {})
                .get("candidate_count"),
                "relevance_distribution": result.get("retrieval", {})
                .get("diagnostics", {})
                .get("relevance_distribution"),
            }
            for result in results
        ],
        "retrieval_macro": retrieval_macro,
        "per_case": results,
    }


def _summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Competitive Intelligence V2 Benchmark Summary",
        "",
        f"Valid cases: {summary['valid_case_count']}",
        f"Failed cases: {summary['failed_case_count']}",
        f"Skipped cases: {summary['skipped_case_count']}",
        "",
        "## Macro retrieval metrics",
        "",
        "| Metric | K=1 | K=3 | K=5 |",
        "|---|---:|---:|---:|",
    ]
    macro = summary["retrieval_macro"]

    def values(section: str, name: str) -> str:
        mapping = macro[section][name]
        return " | ".join(
            "n/a" if mapping[str(k)] is None else f"{mapping[str(k)]:.4f}"
            for k in KS
        )

    lines.extend(
        [
            f"| Broad Precision | {values('broad', 'mean_precision_at_k')} |",
            f"| Broad Recall | {values('broad', 'mean_recall_at_k')} |",
            f"| Strict Precision | {values('strict', 'mean_precision_at_k')} |",
            f"| Strict Recall | {values('strict', 'mean_recall_at_k')} |",
            "| nDCG | "
            + " | ".join(
                (
                    "n/a"
                    if macro["mean_ndcg_at_k"][str(k)] is None
                    else f"{macro['mean_ndcg_at_k'][str(k)]:.4f}"
                )
                for k in KS
            )
            + " |",
            "",
            f"Broad MRR: {macro['broad']['mrr'] if macro['broad']['mrr'] is not None else 'n/a'}",
            "",
            "Strict MRR: "
            + (
                f"{macro['strict']['mrr']}"
                if macro["strict"]["mrr"] is not None
                else "n/a"
            ),
            "",
            "## Case status",
            "",
        ]
    )
    for result in summary["per_case"]:
        lines.append(f"- Valid: `{result['case_id']}`")
    for item in summary["skipped_cases"]:
        lines.append(f"- Skipped: `{item['case_id']}` — {item['reason']}")
    for item in summary["failed_cases"]:
        lines.append(f"- Failed: `{item['case_id']}` — {item['reason']}")
    lines.extend(
        [
            "",
            "Generation observations are stored per case and are never combined "
            "into a quality score.",
        ]
    )
    return "\n".join(lines)


def run(
    case_ids: list[str],
    *,
    mode: EvaluationMode,
    allow_overwrite: bool,
    tolerate_missing: bool,
    freeze: bool,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for case_id in case_ids:
        try:
            results.append(
                evaluate_case(
                    case_id,
                    mode=mode,
                    allow_overwrite=allow_overwrite,
                )
            )
            print(f"Evaluated: {case_id}")
        except (FileNotFoundError, ValueError) as error:
            if not tolerate_missing:
                raise
            skipped.append({"case_id": case_id, "reason": str(error)})
            print(f"Skipped: {case_id}: {error}")
        except Exception as error:
            if not tolerate_missing:
                raise
            failed.append({"case_id": case_id, "reason": str(error)})
            print(f"Failed: {case_id}: {error}")

    summary = aggregate_results(results, failed=failed, skipped=skipped)
    write_json_guarded(
        RESULTS_ROOT / "summary.json",
        summary,
        allow_overwrite=allow_overwrite,
    )
    write_text_guarded(
        RESULTS_ROOT / "summary.md",
        _summary_markdown(summary),
        allow_overwrite=allow_overwrite,
    )
    write_checksums()

    if freeze:
        expected_ids = {case.case_id for case in CASES}
        valid_ids = {result["case_id"] for result in results}
        if mode != "full" or valid_ids != expected_ids or failed or skipped:
            raise RuntimeError(
                "Freeze requires a successful full evaluation for all five cases."
            )
        freeze_benchmark()
        print("Benchmark V2 is frozen.")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--case")
    selection.add_argument("--all", action="store_true")
    parser.add_argument(
        "--mode",
        choices=("retrieval-only", "generation-only", "full"),
        default="full",
    )
    parser.add_argument("--allow-overwrite", action="store_true")
    parser.add_argument("--freeze", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.all:
        case_ids = [case.case_id for case in CASES]
    else:
        case_ids = [get_case(args.case).case_id]
    run(
        case_ids,
        mode=args.mode,
        allow_overwrite=args.allow_overwrite,
        tolerate_missing=args.all,
        freeze=args.freeze,
    )


if __name__ == "__main__":
    main()
