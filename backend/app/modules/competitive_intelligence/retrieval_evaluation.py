"""
Deterministic retrieval evaluation metrics.

This module evaluates a ranked list of retrieved chunk IDs against a
human-labeled relevance ground truth.

Relevance scale:

0 = irrelevant
1 = partially relevant
2 = highly relevant

Binary metrics such as Precision, Recall, and MRR consider relevance >= 1
as relevant by default.

nDCG preserves the graded relevance values so that highly relevant chunks
are rewarded more strongly than partially relevant chunks.

No LLM, vector database, embedding model, or external service is used here.
"""

import math
from collections.abc import Iterable

from pydantic import BaseModel

DEFAULT_RELEVANCE_THRESHOLD = 1


class RetrievalMetricsAtK(BaseModel):
    k: int

    precision: float
    recall: float
    ndcg: float


class RetrievalEvaluationSummary(BaseModel):
    total_candidates: int
    relevant_candidates: int

    retrieved_count: int

    reciprocal_rank: float

    metrics_at_k: list[RetrievalMetricsAtK]


def precision_at_k(
    ranked_chunk_ids: list[str],
    relevance_lookup: dict[str, int],
    *,
    k: int,
    relevance_threshold: int = DEFAULT_RELEVANCE_THRESHOLD,
) -> float:
    """
    Calculate Precision@K.

    Precision@K answers:

        Of the first K retrieved chunks, how many are relevant?

    Missing positions are treated as non-relevant if fewer than K results
    were returned.
    """

    _validate_k(k)

    retrieved_at_k = ranked_chunk_ids[:k]

    relevant_count = sum(
        relevance_lookup[chunk_id] >= relevance_threshold for chunk_id in retrieved_at_k
    )

    return relevant_count / k


def recall_at_k(
    ranked_chunk_ids: list[str],
    relevance_lookup: dict[str, int],
    *,
    k: int,
    relevance_threshold: int = DEFAULT_RELEVANCE_THRESHOLD,
) -> float:
    """
    Calculate Recall@K.

    Recall@K answers:

        Of all relevant candidate chunks, how many were found in the
        first K retrieved results?
    """

    _validate_k(k)

    total_relevant = sum(
        relevance >= relevance_threshold for relevance in relevance_lookup.values()
    )

    if total_relevant == 0:
        return 0.0

    retrieved_relevant = sum(
        relevance_lookup[chunk_id] >= relevance_threshold for chunk_id in ranked_chunk_ids[:k]
    )

    return retrieved_relevant / total_relevant


def reciprocal_rank(
    ranked_chunk_ids: list[str],
    relevance_lookup: dict[str, int],
    *,
    relevance_threshold: int = DEFAULT_RELEVANCE_THRESHOLD,
) -> float:
    """
    Calculate reciprocal rank.

    MRR is the mean of this value across multiple benchmark queries.

    For a single query:

        first relevant result at rank 1 -> 1.0
        first relevant result at rank 2 -> 0.5
        first relevant result at rank 3 -> 0.333...
    """

    for rank, chunk_id in enumerate(
        ranked_chunk_ids,
        start=1,
    ):
        if relevance_lookup[chunk_id] >= relevance_threshold:
            return 1.0 / rank

    return 0.0


def dcg_at_k(
    ranked_chunk_ids: list[str],
    relevance_lookup: dict[str, int],
    *,
    k: int,
) -> float:
    """
    Calculate Discounted Cumulative Gain at K.

    nDCG uses graded relevance directly:

        0 = irrelevant
        1 = partially relevant
        2 = highly relevant

    Gain:

        2^relevance - 1

    Discount:

        log2(rank + 1)
    """

    _validate_k(k)

    dcg = 0.0

    for rank, chunk_id in enumerate(
        ranked_chunk_ids[:k],
        start=1,
    ):
        relevance = relevance_lookup[chunk_id]

        gain = (2**relevance) - 1

        discount = math.log2(rank + 1)

        dcg += gain / discount

    return dcg


def ideal_dcg_at_k(
    relevance_lookup: dict[str, int],
    *,
    k: int,
) -> float:
    """
    Calculate the best possible DCG@K for the labeled candidate set.

    The ideal ranking orders candidate chunks by descending relevance.
    """

    _validate_k(k)

    ideal_relevances = sorted(
        relevance_lookup.values(),
        reverse=True,
    )[:k]

    ideal_dcg = 0.0

    for rank, relevance in enumerate(
        ideal_relevances,
        start=1,
    ):
        gain = (2**relevance) - 1

        discount = math.log2(rank + 1)

        ideal_dcg += gain / discount

    return ideal_dcg


def ndcg_at_k(
    ranked_chunk_ids: list[str],
    relevance_lookup: dict[str, int],
    *,
    k: int,
) -> float:
    """
    Calculate Normalized Discounted Cumulative Gain at K.

    nDCG measures both:

    - whether relevant chunks were retrieved;
    - whether the most relevant chunks appeared near the top.

    Result range:

        1.0 = ideal ranking
        0.0 = no useful ranking signal
    """

    actual_dcg = dcg_at_k(
        ranked_chunk_ids,
        relevance_lookup,
        k=k,
    )

    ideal_dcg = ideal_dcg_at_k(
        relevance_lookup,
        k=k,
    )

    if ideal_dcg == 0:
        return 0.0

    return actual_dcg / ideal_dcg


def evaluate_retrieval(
    *,
    ranked_chunk_ids: list[str],
    relevance_lookup: dict[str, int],
    ks: Iterable[int] = (
        1,
        3,
        5,
    ),
    relevance_threshold: int = DEFAULT_RELEVANCE_THRESHOLD,
) -> RetrievalEvaluationSummary:
    """
    Evaluate a ranked retrieval result against relevance ground truth.

    The ranked_chunk_ids must contain chunk IDs ordered from most relevant
    to least relevant according to the retrieval system.
    """

    if not relevance_lookup:
        raise ValueError("Relevance lookup cannot be empty.")

    if not ranked_chunk_ids:
        raise ValueError("Ranked chunk IDs cannot be empty.")

    _validate_ranked_chunk_ids(
        ranked_chunk_ids,
        relevance_lookup,
    )

    normalized_ks = sorted(set(ks))

    if not normalized_ks:
        raise ValueError("At least one K value is required.")

    for k in normalized_ks:
        _validate_k(k)

    metrics = [
        RetrievalMetricsAtK(
            k=k,
            precision=precision_at_k(
                ranked_chunk_ids,
                relevance_lookup,
                k=k,
                relevance_threshold=(relevance_threshold),
            ),
            recall=recall_at_k(
                ranked_chunk_ids,
                relevance_lookup,
                k=k,
                relevance_threshold=(relevance_threshold),
            ),
            ndcg=ndcg_at_k(
                ranked_chunk_ids,
                relevance_lookup,
                k=k,
            ),
        )
        for k in normalized_ks
    ]

    relevant_candidates = sum(
        relevance >= relevance_threshold for relevance in relevance_lookup.values()
    )

    return RetrievalEvaluationSummary(
        total_candidates=len(relevance_lookup),
        relevant_candidates=relevant_candidates,
        retrieved_count=len(ranked_chunk_ids),
        reciprocal_rank=reciprocal_rank(
            ranked_chunk_ids,
            relevance_lookup,
            relevance_threshold=relevance_threshold,
        ),
        metrics_at_k=metrics,
    )


def _validate_k(
    k: int,
) -> None:
    if k <= 0:
        raise ValueError("K must be greater than zero.")


def _validate_ranked_chunk_ids(
    ranked_chunk_ids: list[str],
    relevance_lookup: dict[str, int],
) -> None:
    if len(ranked_chunk_ids) != len(set(ranked_chunk_ids)):
        raise ValueError("Ranked retrieval contains duplicate chunk IDs.")

    unknown_chunk_ids = [
        chunk_id for chunk_id in ranked_chunk_ids if chunk_id not in relevance_lookup
    ]

    if unknown_chunk_ids:
        raise ValueError(f"Retrieved chunks are missing from the ground truth: {unknown_chunk_ids}")
