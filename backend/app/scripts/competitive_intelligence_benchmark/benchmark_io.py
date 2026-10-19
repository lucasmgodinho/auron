"""Filesystem, hashing, validation, and manifest helpers for the V2 benchmark."""

import hashlib
import importlib.metadata
import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.modules.competitive_intelligence.document_processing import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    EMBEDDING_MODEL,
    TOKENIZER_NAME,
    chunk_document,
)
from app.modules.competitive_intelligence.evaluation import (
    CITATION_JUDGE_SYSTEM_PROMPT,
    CITATION_REQUIREMENT_SYSTEM_PROMPT,
    EVALUATION_MODEL_NAME,
    FAITHFULNESS_JUDGE_SYSTEM_PROMPT,
)
from app.modules.competitive_intelligence.report_generation import (
    REPORT_MODEL_NAME,
    SYSTEM_PROMPT,
)
from app.modules.competitive_intelligence.search import (
    PRIMARY_CANDIDATES,
    SEARCH_CANDIDATES,
    TARGET_DOCUMENTS,
)

from .benchmark_models import (
    BenchmarkCaseDefinition,
    BenchmarkEvaluationFixture,
    BenchmarkManifest,
    BenchmarkSearchFixture,
    RetrievalCandidate,
    RetrievalCandidatesFixture,
    RetrievalGroundTruthFixture,
)

SCHEMA_VERSION = "1.0.0"
BENCHMARK_ID = "competitive_intelligence_v2"
BENCHMARK_VERSION = "2.0.0"
ANNOTATION_GUIDELINE_VERSION = "2.0.0"
NORMALIZATION_VERSION = "v2_whitespace_markdown_1"
KS = [1, 3, 5]
TOP_K = 5
BROAD_RELEVANCE_THRESHOLD = 1
STRICT_RELEVANCE_THRESHOLD = 2

PACKAGE_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = PACKAGE_DIR.parents[2]
REPOSITORY_ROOT = BACKEND_ROOT.parent
BENCHMARK_ROOT = BACKEND_ROOT / "evaluation" / "benchmarks" / "v2"
CASES_ROOT = BENCHMARK_ROOT / "cases"
RESULTS_ROOT = BENCHMARK_ROOT / "results"
LEGACY_FIXTURES_ROOT = PACKAGE_DIR.parent / "fixtures"
MANIFEST_PATH = BENCHMARK_ROOT / "benchmark.json"
CHECKSUMS_PATH = BENCHMARK_ROOT / "checksums.json"

CASES = (
    BenchmarkCaseDefinition(
        case_id="microsoft_competitors",
        research_question="Who are Microsoft's main competitors in the technology sector?",
    ),
    BenchmarkCaseDefinition(
        case_id="salesforce_crm_competitors",
        research_question="Who are Salesforce's main competitors in the CRM market?",
    ),
    BenchmarkCaseDefinition(
        case_id="nvidia_ai_accelerators",
        research_question="Who are Nvidia's main competitors in the AI accelerator market?",
    ),
    BenchmarkCaseDefinition(
        case_id="slack_enterprise_alternatives",
        research_question="What are the main alternatives to Slack for enterprise collaboration?",
    ),
    BenchmarkCaseDefinition(
        case_id="aws_cloud_competitors",
        research_question="Who are AWS's main competitors in cloud infrastructure services?",
    ),
)
CASE_BY_ID = {case.case_id: case for case in CASES}

def utc_now() -> datetime:
    return datetime.now(UTC)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def json_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def chunking_configuration() -> dict[str, Any]:
    return {
        "normalization_version": NORMALIZATION_VERSION,
        "chunk_size_tokens": DEFAULT_CHUNK_SIZE,
        "chunk_overlap_tokens": DEFAULT_CHUNK_OVERLAP,
        "resolved_tokenizer": TOKENIZER_NAME,
    }


def chunking_configuration_sha256() -> str:
    return json_sha256(chunking_configuration())


def candidate_set_sha256(candidates: list[RetrievalCandidate]) -> str:
    return json_sha256(
        [candidate.model_dump(mode="json") for candidate in candidates]
    )


def get_case(case_id: str) -> BenchmarkCaseDefinition:
    try:
        return CASE_BY_ID[case_id]
    except KeyError as error:
        raise ValueError(f"Unknown benchmark case: {case_id}") from error


def case_dir(case_id: str) -> Path:
    get_case(case_id)
    return CASES_ROOT / case_id


def search_fixture_path(case_id: str) -> Path:
    return case_dir(case_id) / "search_fixture.json"


def candidates_path(case_id: str) -> Path:
    return case_dir(case_id) / "retrieval_candidates.json"


def ground_truth_path(case_id: str) -> Path:
    return case_dir(case_id) / "retrieval_ground_truth.json"


def evaluation_fixture_path(case_id: str) -> Path:
    return case_dir(case_id) / "evaluation_fixture.json"


def case_result_dir(case_id: str) -> Path:
    return RESULTS_ROOT / "cases" / case_id


def load_json_model[ModelT: BaseModel](
    path: Path,
    model_type: type[ModelT],
) -> ModelT:
    if not path.exists():
        raise FileNotFoundError(f"Required benchmark artifact was not found: {path}")
    return model_type.model_validate_json(path.read_text(encoding="utf-8"))


def load_manifest() -> BenchmarkManifest:
    return load_json_model(MANIFEST_PATH, BenchmarkManifest)


def ensure_mutable() -> None:
    if MANIFEST_PATH.exists() and load_manifest().status == "frozen":
        raise RuntimeError(
            "Benchmark V2 is frozen. Create a new benchmark version instead of modifying it."
        )


def write_json_guarded(
    path: Path,
    value: BaseModel | dict[str, Any] | list[Any],
    *,
    allow_overwrite: bool = False,
) -> bool:
    data = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    rendered = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing == rendered:
            return False
    ensure_mutable()
    if path.exists():
        if not allow_overwrite:
            raise FileExistsError(
                f"Refusing to overwrite changed benchmark artifact without "
                f"--allow-overwrite: {path}"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    return True


def write_text_guarded(
    path: Path,
    value: str,
    *,
    allow_overwrite: bool = False,
) -> bool:
    rendered = value.rstrip() + "\n"
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing == rendered:
            return False
    ensure_mutable()
    if path.exists():
        if not allow_overwrite:
            raise FileExistsError(
                f"Refusing to overwrite changed benchmark artifact without "
                f"--allow-overwrite: {path}"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    return True


def build_candidates_fixture(
    search_fixture: BenchmarkSearchFixture,
) -> RetrievalCandidatesFixture:
    source_by_id = {document.source_id: document for document in search_fixture.documents}
    candidates: list[RetrievalCandidate] = []
    for document in search_fixture.documents:
        for chunk in chunk_document(
            document,
            chunk_size=DEFAULT_CHUNK_SIZE,
            overlap=DEFAULT_CHUNK_OVERLAP,
        ):
            source = source_by_id[chunk.source_id]
            candidates.append(
                RetrievalCandidate(
                    chunk_id=chunk.chunk_id,
                    source_id=chunk.source_id,
                    source_rank=source.provider_rank,
                    url=str(source.url),
                    domain=source.domain,
                    title=source.title,
                    chunk_index=chunk.chunk_index,
                    token_count=chunk.token_count,
                    text=chunk.text,
                )
            )
    return RetrievalCandidatesFixture(
        schema_version=SCHEMA_VERSION,
        case_id=search_fixture.case_id,
        research_question=search_fixture.research_question,
        normalization_version=NORMALIZATION_VERSION,
        chunk_size_tokens=DEFAULT_CHUNK_SIZE,
        chunk_overlap_tokens=DEFAULT_CHUNK_OVERLAP,
        resolved_tokenizer=TOKENIZER_NAME,
        chunking_configuration_sha256=chunking_configuration_sha256(),
        candidate_set_sha256=candidate_set_sha256(candidates),
        candidates=candidates,
        created_at=utc_now(),
    )


def validate_ground_truth(
    ground_truth: RetrievalGroundTruthFixture,
    candidates: RetrievalCandidatesFixture,
    *,
    require_complete: bool = True,
) -> None:
    if ground_truth.case_id != candidates.case_id:
        raise ValueError("Ground truth case_id does not match candidates.")
    if ground_truth.research_question != candidates.research_question:
        raise ValueError("Ground truth research question does not match candidates.")
    if ground_truth.candidate_set_sha256 != candidates.candidate_set_sha256:
        raise ValueError("Ground truth candidate set hash does not match candidates.")
    if ground_truth.chunking_configuration_sha256 != candidates.chunking_configuration_sha256:
        raise ValueError("Ground truth chunking configuration hash does not match candidates.")

    candidate_ids = [candidate.chunk_id for candidate in candidates.candidates]
    label_ids = [label.chunk_id for label in ground_truth.labels]
    missing = sorted(set(candidate_ids) - set(label_ids))
    extra = sorted(set(label_ids) - set(candidate_ids))
    if missing or extra:
        raise ValueError(f"Ground truth coverage mismatch. Missing={missing}; extra={extra}")
    if len(label_ids) != len(candidate_ids):
        raise ValueError("Every candidate must be labeled exactly once.")
    if require_complete:
        unlabeled = [label.chunk_id for label in ground_truth.labels if label.relevance is None]
        if unlabeled:
            raise ValueError(
                "Ground truth is not human-reviewed and complete; "
                f"{len(unlabeled)} labels remain null."
            )
        if ground_truth.annotated_at is None:
            raise ValueError("Completed ground truth requires annotated_at.")
        if "human" not in ground_truth.annotation_method.lower():
            raise ValueError("Completed ground truth must identify a human review method.")


def validate_evaluation_fixture(
    fixture: BenchmarkEvaluationFixture,
    candidates: RetrievalCandidatesFixture,
    ground_truth: RetrievalGroundTruthFixture,
) -> None:
    validate_ground_truth(ground_truth, candidates, require_complete=True)
    if fixture.ground_truth_status != "validated":
        raise ValueError("Final evaluation requires a validated human-reviewed ground truth.")
    if fixture.case_id != candidates.case_id:
        raise ValueError("Evaluation fixture case_id does not match candidates.")
    if fixture.research_question != candidates.research_question:
        raise ValueError("Evaluation fixture research question does not match candidates.")
    if fixture.candidate_set_sha256 != candidates.candidate_set_sha256:
        raise ValueError("Evaluation fixture candidate set hash does not match candidates.")
    if fixture.chunking_configuration_sha256 != candidates.chunking_configuration_sha256:
        raise ValueError(
            "Evaluation fixture chunking configuration hash does not match candidates."
        )
    candidate_by_id = {candidate.chunk_id: candidate for candidate in candidates.candidates}
    source_ids = {candidate.source_id for candidate in candidates.candidates}
    for item in fixture.evidence:
        candidate = candidate_by_id.get(item.evidence.chunk_id)
        if candidate is None:
            raise ValueError(f"Retrieved chunk is absent from candidates: {item.evidence.chunk_id}")
        if item.evidence.source_id not in source_ids:
            raise ValueError(
                f"Retrieved source is absent from candidates: {item.evidence.source_id}"
            )
        if item.evidence.text != candidate.text:
            raise ValueError(f"Retrieved chunk text changed: {item.evidence.chunk_id}")
    if len(fixture.evidence) > TOP_K:
        raise ValueError("Evaluation fixture contains more evidence than benchmark top_k.")


def _git_value(*args: str) -> str | None:
    result = subprocess.run(
        ["git", *args],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    value = result.stdout.strip()
    return value or None


def _dependency_versions() -> dict[str, str | None]:
    names = [
        "chromadb",
        "langchain-chroma",
        "langchain-openai",
        "pydantic",
        "tiktoken",
    ]
    versions: dict[str, str | None] = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def build_manifest(*, existing: BenchmarkManifest | None = None) -> BenchmarkManifest:
    requirements_path = BACKEND_ROOT / "requirements.txt"
    created_at = existing.created_at if existing is not None else utc_now()
    return BenchmarkManifest(
        schema_version=SCHEMA_VERSION,
        benchmark_id=BENCHMARK_ID,
        benchmark_version=BENCHMARK_VERSION,
        status=existing.status if existing is not None else "draft",
        description=(
            "Frozen-source V2 baseline for deterministic retrieval metrics and "
            "separately identified LLM-judge generation observations."
        ),
        cases=list(CASES),
        relevance_scale={
            "0": "irrelevant",
            "1": "partially relevant",
            "2": "highly relevant",
        },
        ks=KS,
        broad_relevance_threshold=BROAD_RELEVANCE_THRESHOLD,
        strict_relevance_threshold=STRICT_RELEVANCE_THRESHOLD,
        metric_definitions={
            "precision_at_k": (
                "Relevant retrieved chunks divided by K; missing ranks count as non-relevant."
            ),
            "recall_at_k": "Relevant retrieved chunks divided by all relevant candidates.",
            "reciprocal_rank": "Inverse rank of the first relevant retrieved chunk for one case.",
            "mrr": "Macro mean of per-case Reciprocal Rank.",
            "ndcg_at_k": "Graded nDCG with gain 2^relevance - 1 and log2 rank discount.",
        },
        aggregation_policy={
            "primary": "macro average across valid cases",
            "micro": "optional diagnostic weighted by underlying counts",
            "failed_or_skipped": "excluded from metric means and counted explicitly",
        },
        search_configuration={
            "provider": "tavily",
            "search_depth": "advanced",
            "max_results": SEARCH_CANDIDATES,
            "include_answer": True,
            "include_raw_content": True,
            "include_published_date": True,
        },
        document_acquisition_configuration={
            "primary_candidates": PRIMARY_CANDIDATES,
            "target_documents": TARGET_DOCUMENTS,
            "extract_depth": "advanced",
            "extract_format": "markdown",
            "fallback": "search_content",
        },
        normalization_configuration={
            "remove_markdown_images": True,
            "remove_empty_markdown_links": True,
            "preserve_link_text": True,
            "trim_trailing_whitespace": True,
            "collapse_excess_blank_lines": True,
        },
        normalization_version=NORMALIZATION_VERSION,
        chunk_size_tokens=DEFAULT_CHUNK_SIZE,
        chunk_overlap_tokens=DEFAULT_CHUNK_OVERLAP,
        resolved_tokenizer=TOKENIZER_NAME,
        embedding_configuration={
            "provider": "openai",
            "model": EMBEDDING_MODEL,
            "observed_dimension": (
                existing.embedding_configuration.get("observed_dimension")
                if existing is not None
                else None
            ),
        },
        vector_store_configuration={
            "provider": "chroma",
            "persistence": "ephemeral",
            "collection_scope": "one isolated disposable collection per case capture",
            "distance": "cosine distance; lower is more similar",
        },
        top_k=TOP_K,
        report_configuration={
            "provider": "openai",
            "model": REPORT_MODEL_NAME,
            "temperature": 0,
            "max_retries": 2,
        },
        evaluation_configuration={
            "provider": "openai",
            "model": EVALUATION_MODEL_NAME,
            "temperature": 0,
            "max_retries": 2,
            "llm_judge_metrics": [
                "citation correctness",
                "citation coverage",
                "faithfulness",
            ],
        },
        prompt_sha256={
            "report_system": sha256_text(SYSTEM_PROMPT),
            "citation_judge_system": sha256_text(CITATION_JUDGE_SYSTEM_PROMPT),
            "citation_requirement_system": sha256_text(CITATION_REQUIREMENT_SYSTEM_PROMPT),
            "faithfulness_judge_system": sha256_text(FAITHFULNESS_JUDGE_SYSTEM_PROMPT),
        },
        environment={
            "python_version": platform.python_version(),
            "dependency_versions": _dependency_versions(),
            "requirements_sha256": (
                sha256_bytes(requirements_path.read_bytes())
                if requirements_path.exists()
                else None
            ),
        },
        git={
            "sha": _git_value("rev-parse", "HEAD"),
            "branch": _git_value("branch", "--show-current"),
            "working_tree": "dirty" if _git_value("status", "--porcelain") else "clean",
        },
        created_at=created_at,
        frozen_at=existing.frozen_at if existing is not None else None,
    )


def update_observed_embedding_dimension(dimension: int) -> None:
    manifest = load_manifest()
    existing = manifest.embedding_configuration.get("observed_dimension")
    if existing not in {None, dimension}:
        raise ValueError(
            f"Observed embedding dimension changed from {existing} to {dimension}."
        )
    manifest.embedding_configuration["observed_dimension"] = dimension
    write_json_guarded(MANIFEST_PATH, manifest, allow_overwrite=True)


def compute_checksums() -> dict[str, str]:
    checksums: dict[str, str] = {}
    if not BENCHMARK_ROOT.exists():
        return checksums
    for path in sorted(BENCHMARK_ROOT.rglob("*")):
        if not path.is_file() or path == CHECKSUMS_PATH:
            continue
        relative = path.relative_to(BENCHMARK_ROOT).as_posix()
        checksums[relative] = sha256_bytes(path.read_bytes())
    return checksums


def write_checksums(*, allow_overwrite: bool = True) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "algorithm": "sha256",
        "files": compute_checksums(),
    }
    write_json_guarded(CHECKSUMS_PATH, payload, allow_overwrite=allow_overwrite)


def verify_checksums() -> None:
    if not CHECKSUMS_PATH.exists():
        raise FileNotFoundError(f"Checksums file was not found: {CHECKSUMS_PATH}")
    payload = json.loads(CHECKSUMS_PATH.read_text(encoding="utf-8"))
    expected = payload.get("files")
    if not isinstance(expected, dict):
        raise ValueError("Checksums file has an invalid files mapping.")
    actual = compute_checksums()
    if expected != actual:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(
            path for path in set(expected) & set(actual) if expected[path] != actual[path]
        )
        raise ValueError(
            f"Benchmark checksum mismatch. Missing={missing}; extra={extra}; changed={changed}"
        )


def freeze_benchmark() -> None:
    """Atomically finalize the manifest state and its resulting checksum inventory."""

    manifest = load_manifest()
    if manifest.status == "frozen":
        verify_checksums()
        return
    manifest.status = "frozen"
    manifest.frozen_at = utc_now()
    MANIFEST_PATH.write_text(
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "algorithm": "sha256",
        "files": compute_checksums(),
    }
    CHECKSUMS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    verify_checksums()
