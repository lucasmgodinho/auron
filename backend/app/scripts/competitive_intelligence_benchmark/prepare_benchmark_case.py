"""Capture and validate one parametrized Competitive Intelligence benchmark case."""

import argparse
import os
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

from app.modules.competitive_intelligence.context_builder import build_research_context
from app.modules.competitive_intelligence.embeddings import get_embeddings
from app.modules.competitive_intelligence.evidence import EvidenceChunk
from app.modules.competitive_intelligence.report_generation import (
    REPORT_MODEL_NAME,
    generate_grounded_report,
)
from app.modules.competitive_intelligence.search import TavilySearchClient
from app.modules.competitive_intelligence.vector_store import (
    create_vector_store,
    index_chunks,
    retrieve_evidence,
)

from .benchmark_io import (
    ANNOTATION_GUIDELINE_VERSION,
    REPOSITORY_ROOT,
    SCHEMA_VERSION,
    TOP_K,
    build_candidates_fixture,
    candidates_path,
    evaluation_fixture_path,
    get_case,
    ground_truth_path,
    load_json_model,
    load_manifest,
    search_fixture_path,
    update_observed_embedding_dimension,
    utc_now,
    validate_evaluation_fixture,
    validate_ground_truth,
    write_checksums,
    write_json_guarded,
)
from .benchmark_models import (
    BenchmarkEvaluationFixture,
    BenchmarkEvidenceItem,
    BenchmarkSearchFixture,
    GroundTruthLabel,
    RetrievalCandidatesFixture,
    RetrievalGroundTruthFixture,
)


def _load_environment(required_key: str) -> str:
    env_path = REPOSITORY_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    value = os.getenv(required_key)
    if not value:
        raise RuntimeError(f"{required_key} is required for this operation.")
    return value


def capture_search(
    case_id: str,
    *,
    allow_overwrite: bool,
    client_factory: Callable[[str], TavilySearchClient] | None = None,
) -> Path:
    case = get_case(case_id)
    api_key = _load_environment("TAVILY_API_KEY")
    client = (
        client_factory(api_key)
        if client_factory is not None
        else TavilySearchClient(api_key=api_key)
    )
    result = client.search(case.research_question)
    if not result.documents:
        raise RuntimeError("Tavily returned no selected SourceDocuments.")
    manifest = load_manifest()
    fixture = BenchmarkSearchFixture(
        schema_version=SCHEMA_VERSION,
        case_id=case.case_id,
        research_question=case.research_question,
        acquisition_configuration={
            "search": manifest.search_configuration,
            "document_selection": manifest.document_acquisition_configuration,
        },
        documents=list(result.documents),
        captured_at=utc_now(),
    )
    path = search_fixture_path(case_id)
    write_json_guarded(path, fixture, allow_overwrite=allow_overwrite)
    write_checksums()
    print(f"Captured {len(fixture.documents)} frozen SourceDocuments: {path}")
    return path


def build_candidates(case_id: str, *, allow_overwrite: bool) -> Path:
    case = get_case(case_id)
    search_fixture = load_json_model(
        search_fixture_path(case_id), BenchmarkSearchFixture
    )
    if search_fixture.research_question != case.research_question:
        raise ValueError("Search fixture question does not match the canonical case question.")
    candidates = build_candidates_fixture(search_fixture)
    path = candidates_path(case_id)

    ground_truth_file = ground_truth_path(case_id)
    if ground_truth_file.exists():
        existing_ground_truth = load_json_model(
            ground_truth_file, RetrievalGroundTruthFixture
        )
        validate_ground_truth(
            existing_ground_truth,
            candidates,
            require_complete=False,
        )

    write_json_guarded(path, candidates, allow_overwrite=allow_overwrite)
    if not ground_truth_file.exists():
        draft = RetrievalGroundTruthFixture(
            schema_version=SCHEMA_VERSION,
            case_id=case.case_id,
            research_question=case.research_question,
            candidate_set_sha256=candidates.candidate_set_sha256,
            chunking_configuration_sha256=candidates.chunking_configuration_sha256,
            annotation_guideline_version=ANNOTATION_GUIDELINE_VERSION,
            annotation_method="pending_human_review",
            notes="Set every relevance value to 0, 1, or 2 after human review.",
            labels=[
                GroundTruthLabel(chunk_id=candidate.chunk_id)
                for candidate in candidates.candidates
            ],
        )
        write_json_guarded(ground_truth_file, draft)
    write_checksums()
    print(f"Built {len(candidates.candidates)} offline retrieval candidates: {path}")
    print(f"Ground truth: {ground_truth_file}")
    return path


def validate_case_ground_truth(case_id: str) -> None:
    candidates = load_json_model(candidates_path(case_id), RetrievalCandidatesFixture)
    ground_truth = load_json_model(
        ground_truth_path(case_id), RetrievalGroundTruthFixture
    )
    validate_ground_truth(ground_truth, candidates, require_complete=True)
    print(
        f"Validated exhaustive human-reviewed ground truth for {case_id}: "
        f"{len(ground_truth.labels)} labels"
    )


def capture_evaluation(
    case_id: str,
    *,
    allow_overwrite: bool,
    draft: bool,
) -> Path:
    case = get_case(case_id)
    _load_environment("OPENAI_API_KEY")
    search_fixture = load_json_model(
        search_fixture_path(case_id), BenchmarkSearchFixture
    )
    candidates = load_json_model(candidates_path(case_id), RetrievalCandidatesFixture)
    ground_truth = load_json_model(
        ground_truth_path(case_id), RetrievalGroundTruthFixture
    )
    validate_ground_truth(ground_truth, candidates, require_complete=not draft)

    evidence_chunks = [
        EvidenceChunk(
            chunk_id=candidate.chunk_id,
            source_id=candidate.source_id,
            research_query=case.research_question,
            text=candidate.text,
            chunk_index=candidate.chunk_index,
            token_count=candidate.token_count,
        )
        for candidate in candidates.candidates
    ]
    collection_name = f"ci_v2_{case_id}_{uuid4().hex}"
    embeddings = get_embeddings()
    observed_dimension = len(embeddings.embed_query(case.research_question))
    vector_store = create_vector_store(collection_name=collection_name)
    try:
        index_chunks(vector_store, evidence_chunks)
        retrieved = retrieve_evidence(
            vector_store,
            case.research_question,
            top_k=TOP_K,
        )
        if len(retrieved) != min(TOP_K, len(evidence_chunks)):
            raise RuntimeError("Retrieval did not return the expected number of chunks.")
        context = build_research_context(retrieved, search_fixture.documents)
        report = generate_grounded_report(case.research_question, context)
    finally:
        vector_store.delete_collection()

    source_by_id = {source.source_id: source for source in search_fixture.documents}
    manifest = load_manifest()
    fixture = BenchmarkEvaluationFixture(
        schema_version=SCHEMA_VERSION,
        case_id=case.case_id,
        research_question=case.research_question,
        candidate_set_sha256=candidates.candidate_set_sha256,
        chunking_configuration_sha256=candidates.chunking_configuration_sha256,
        isolated_collection_name=collection_name,
        embedding_configuration=manifest.embedding_configuration,
        observed_embedding_dimension=observed_dimension,
        vector_store_configuration=manifest.vector_store_configuration,
        report_configuration=manifest.report_configuration,
        report_prompt_sha256=manifest.prompt_sha256["report_system"],
        ground_truth_status="draft" if draft else "validated",
        report=report,
        evidence=[
            BenchmarkEvidenceItem(
                evidence_id=f"E{index}",
                evidence=evidence,
                source=source_by_id[evidence.source_id],
            )
            for index, evidence in enumerate(retrieved, start=1)
        ],
        captured_at=utc_now(),
    )
    if not draft:
        validate_evaluation_fixture(fixture, candidates, ground_truth)

    path = evaluation_fixture_path(case_id)
    write_json_guarded(path, fixture, allow_overwrite=allow_overwrite)
    update_observed_embedding_dimension(observed_dimension)
    write_checksums()
    print(f"Captured isolated top-{len(fixture.evidence)} ranking and report: {path}")
    print(f"Report model: {REPORT_MODEL_NAME}")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, help="Stable benchmark case ID.")
    parser.add_argument(
        "operation",
        choices=(
            "capture-search",
            "build-candidates",
            "validate-ground-truth",
            "capture-evaluation",
        ),
    )
    parser.add_argument("--allow-overwrite", action="store_true")
    parser.add_argument(
        "--draft",
        action="store_true",
        help="Allow evaluation capture before human labels; output cannot be evaluated or frozen.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    get_case(args.case)
    if args.operation == "capture-search":
        capture_search(args.case, allow_overwrite=args.allow_overwrite)
    elif args.operation == "build-candidates":
        build_candidates(args.case, allow_overwrite=args.allow_overwrite)
    elif args.operation == "validate-ground-truth":
        validate_case_ground_truth(args.case)
    else:
        capture_evaluation(
            args.case,
            allow_overwrite=args.allow_overwrite,
            draft=args.draft,
        )


if __name__ == "__main__":
    main()
