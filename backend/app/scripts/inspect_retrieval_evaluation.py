"""
Inspect deterministic retrieval evaluation for a frozen benchmark case.

This script compares a frozen retrieval ranking against human-reviewed
chunk relevance labels.

It does not call:

- Tavily
- OpenAI
- an embedding model
- Chroma
- any external service

The purpose is to provide a reproducible retrieval baseline.
"""

from app.modules.competitive_intelligence.retrieval_evaluation import (
    evaluate_retrieval,
)
from app.scripts.evaluation_fixture import load_evaluation_fixture
from app.scripts.retrieval_ground_truth import (
    build_relevance_lookup,
    load_retrieval_ground_truth,
)

EVALUATION_FIXTURE = "microsoft_competitors_evaluation.json"
GROUND_TRUTH_FIXTURE = "microsoft_competitors_retrieval_ground_truth.json"

KS = (1, 3, 5)


def main() -> None:
    evaluation_fixture = load_evaluation_fixture(
        filename=EVALUATION_FIXTURE,
    )

    ground_truth = load_retrieval_ground_truth(
        filename=GROUND_TRUTH_FIXTURE,
        expected_question=evaluation_fixture.research_question,
    )

    relevance_lookup = build_relevance_lookup(
        ground_truth,
    )

    ranked_chunk_ids = [item.evidence.chunk_id for item in evaluation_fixture.evidence]

    summary = evaluate_retrieval(
        ranked_chunk_ids=ranked_chunk_ids,
        relevance_lookup=relevance_lookup,
        ks=KS,
    )

    print_header(
        "RETRIEVAL EVALUATION",
    )

    print(f"Question: {ground_truth.research_question}")
    print(f"Total labeled candidates: {summary.total_candidates}")
    print(f"Relevant candidates: {summary.relevant_candidates}")
    print(f"Retrieved chunks: {summary.retrieved_count}")

    print_header(
        "FROZEN RETRIEVAL RANKING",
    )

    for rank, item in enumerate(
        evaluation_fixture.evidence,
        start=1,
    ):
        chunk_id = item.evidence.chunk_id
        relevance = relevance_lookup[chunk_id]

        print(f"{rank}. {item.evidence_id} | relevance={relevance} | chunk={chunk_id}")

    print_header(
        "METRICS",
    )

    for metrics in summary.metrics_at_k:
        print(
            f"K={metrics.k} | "
            f"Precision@{metrics.k}={metrics.precision:.4f} | "
            f"Recall@{metrics.k}={metrics.recall:.4f} | "
            f"nDCG@{metrics.k}={metrics.ndcg:.4f}"
        )

    print(f"Reciprocal Rank: {summary.reciprocal_rank:.4f}")

    print_header(
        "GROUND TRUTH DISTRIBUTION",
    )

    relevance_counts = {
        0: 0,
        1: 0,
        2: 0,
    }

    for relevance in relevance_lookup.values():
        relevance_counts[relevance] += 1

    print(f"Irrelevant (0): {relevance_counts[0]}")
    print(f"Partially relevant (1): {relevance_counts[1]}")
    print(f"Highly relevant (2): {relevance_counts[2]}")


def print_header(
    title: str,
) -> None:
    separator = "=" * 80

    print()
    print(separator)
    print(title)
    print(separator)


if __name__ == "__main__":
    main()
