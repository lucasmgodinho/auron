"""Bootstrap the V2 benchmark and safely migrate the reviewed Microsoft case."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from app.scripts.evaluation_fixture import GroundedReportFixture
from app.scripts.search_fixture import SearchFixture

from .benchmark_io import (
    ANNOTATION_GUIDELINE_VERSION,
    BENCHMARK_ROOT,
    CASES,
    CHECKSUMS_PATH,
    LEGACY_FIXTURES_ROOT,
    MANIFEST_PATH,
    SCHEMA_VERSION,
    build_candidates_fixture,
    build_manifest,
    candidates_path,
    case_dir,
    chunking_configuration_sha256,
    evaluation_fixture_path,
    ground_truth_path,
    load_manifest,
    search_fixture_path,
    validate_evaluation_fixture,
    validate_ground_truth,
    write_checksums,
    write_json_guarded,
    write_text_guarded,
)
from .benchmark_models import (
    BenchmarkEvaluationFixture,
    BenchmarkEvidenceItem,
    BenchmarkSearchFixture,
    GroundTruthLabel,
    RetrievalGroundTruthFixture,
)

LEGACY_SEARCH = LEGACY_FIXTURES_ROOT / "microsoft_competitors.json"
LEGACY_GROUND_TRUTH = (
    LEGACY_FIXTURES_ROOT / "microsoft_competitors_retrieval_ground_truth.json"
)
LEGACY_EVALUATION = LEGACY_FIXTURES_ROOT / "microsoft_competitors_evaluation.json"

EVALUATION_README = """
# Competitive Intelligence Evaluation

This directory contains versioned benchmark data and persisted evaluation results. Runtime
Python code remains under `app/scripts/competitive_intelligence_benchmark`.

Never store API keys, `.env` files, raw embeddings, persistent Chroma databases, or disposable
caches here.
"""

BENCHMARK_README = r"""
# Competitive Intelligence V2 Benchmark

V2 is a frozen-source benchmark for five canonical competitive-intelligence questions. Retrieval
metrics are deterministic after search fixtures and evaluation rankings have been captured.
Generation metrics are reported separately as LLM-judge observations.

## Workflow

Run commands from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m `
  app.scripts.competitive_intelligence_benchmark.migrate_v2_benchmark
.\.venv\Scripts\python.exe -m `
  app.scripts.competitive_intelligence_benchmark.prepare_benchmark_case `
  --case <case_id> capture-search
.\.venv\Scripts\python.exe -m `
  app.scripts.competitive_intelligence_benchmark.prepare_benchmark_case `
  --case <case_id> build-candidates
.\.venv\Scripts\python.exe -m `
  app.scripts.competitive_intelligence_benchmark.prepare_benchmark_case `
  --case <case_id> validate-ground-truth
.\.venv\Scripts\python.exe -m `
  app.scripts.competitive_intelligence_benchmark.prepare_benchmark_case `
  --case <case_id> capture-evaluation
.\.venv\Scripts\python.exe -m `
  app.scripts.competitive_intelligence_benchmark.evaluate_benchmark --all --mode full
```

`capture-search` is the only operation that calls Tavily. `build-candidates` and retrieval
evaluation are offline. `capture-evaluation` reads only the frozen search fixture and may call
OpenAI for embeddings and report generation. Generation evaluation may call the configured LLM
judges.

## Freeze policy

While status is `draft`, changed artifacts require explicit `--allow-overwrite`. Once status is
`frozen`, canonical questions, source fixtures, candidates, ground truth, ranking, evidence IDs,
reports, configuration, results, and checksums are immutable. Corrections require a new benchmark
version.
"""

ANNOTATION_GUIDELINES = """
# Retrieval Annotation Guidelines

Version: 2.0.0

Label every candidate chunk exactly once against its case's canonical research question.

- `0` — irrelevant: the chunk does not help answer the question.
- `1` — partially relevant: the chunk provides useful context or supports only part of the answer.
- `2` — highly relevant: the chunk directly identifies or substantively explains a requested
  competitor or alternative in the specified market.

Judge only the exact chunk text. Do not use outside knowledge to repair missing context. Apply the
same standard to all companies and sources. Record uncertainty in `review_flag` or `notes` rather
than guessing. Machine suggestions may be stored separately in `suggested_relevance`, but the
final `relevance` value must be assigned or confirmed by a human reviewer. After review, set
`annotation_method` to a value containing `human` and provide `annotated_at` in UTC.
"""


def _artifact_timestamp(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def _load_legacy_artifacts() -> tuple[
    BenchmarkSearchFixture,
    RetrievalGroundTruthFixture,
    BenchmarkEvaluationFixture,
]:
    for path in (LEGACY_SEARCH, LEGACY_GROUND_TRUTH, LEGACY_EVALUATION):
        if not path.exists():
            raise FileNotFoundError(f"Legacy Microsoft artifact was not found: {path}")

    case = next(item for item in CASES if item.case_id == "microsoft_competitors")
    legacy_search = SearchFixture.model_validate_json(
        LEGACY_SEARCH.read_text(encoding="utf-8")
    )
    if legacy_search.research_question != case.research_question:
        raise ValueError("Legacy Microsoft search question does not match the canonical question.")

    search_fixture = BenchmarkSearchFixture(
        schema_version=SCHEMA_VERSION,
        case_id=case.case_id,
        research_question=case.research_question,
        acquisition_configuration={
            "provider": "tavily",
            "migration": "existing frozen normalized SourceDocument fixture",
        },
        documents=legacy_search.documents,
        captured_at=max(document.retrieved_at for document in legacy_search.documents),
        migration_source=LEGACY_SEARCH.name,
    )
    candidates = build_candidates_fixture(search_fixture).model_copy(
        update={"created_at": _artifact_timestamp(LEGACY_GROUND_TRUTH)}
    )

    legacy_ground_truth = json.loads(LEGACY_GROUND_TRUTH.read_text(encoding="utf-8"))
    if legacy_ground_truth.get("research_question") != case.research_question:
        raise ValueError("Legacy Microsoft ground truth question is not canonical.")
    labels = [GroundTruthLabel.model_validate(item) for item in legacy_ground_truth["labels"]]
    ground_truth = RetrievalGroundTruthFixture(
        schema_version=SCHEMA_VERSION,
        case_id=case.case_id,
        research_question=case.research_question,
        candidate_set_sha256=candidates.candidate_set_sha256,
        chunking_configuration_sha256=chunking_configuration_sha256(),
        annotation_guideline_version=ANNOTATION_GUIDELINE_VERSION,
        annotated_at=_artifact_timestamp(LEGACY_GROUND_TRUTH),
        annotation_method="human_reviewed_legacy_migration",
        notes="Migrated without relabeling from the existing human-reviewed Microsoft fixture.",
        labels=labels,
    )
    validate_ground_truth(ground_truth, candidates, require_complete=True)

    legacy_evaluation = GroundedReportFixture.model_validate_json(
        LEGACY_EVALUATION.read_text(encoding="utf-8")
    )
    if legacy_evaluation.research_question != case.research_question:
        raise ValueError("Legacy Microsoft evaluation question is not canonical.")
    evaluation = BenchmarkEvaluationFixture(
        schema_version=SCHEMA_VERSION,
        case_id=case.case_id,
        research_question=case.research_question,
        candidate_set_sha256=candidates.candidate_set_sha256,
        chunking_configuration_sha256=candidates.chunking_configuration_sha256,
        isolated_collection_name="legacy_microsoft_competitors_migrated",
        embedding_configuration={
            "provider": "openai",
            "model": "text-embedding-3-small",
        },
        observed_embedding_dimension=None,
        vector_store_configuration={
            "provider": "chroma",
            "distance": "cosine distance; lower is more similar",
            "persistence": "ephemeral",
        },
        report_configuration={
            "provider": "openai",
            "model": "gpt-4o-mini",
            "temperature": 0,
        },
        report_prompt_sha256=build_manifest().prompt_sha256["report_system"],
        ground_truth_status="validated",
        report=legacy_evaluation.report,
        evidence=[
            BenchmarkEvidenceItem(
                evidence_id=item.evidence_id,
                evidence=item.evidence,
                source=item.source,
            )
            for item in legacy_evaluation.evidence
        ],
        captured_at=legacy_evaluation.captured_at,
        migration_source=LEGACY_EVALUATION.name,
    )
    validate_evaluation_fixture(evaluation, candidates, ground_truth)
    return search_fixture, ground_truth, evaluation


def migrate(*, dry_run: bool, allow_overwrite: bool) -> None:
    search_fixture, ground_truth, evaluation = _load_legacy_artifacts()
    candidates = build_candidates_fixture(search_fixture).model_copy(
        update={"created_at": _artifact_timestamp(LEGACY_GROUND_TRUTH)}
    )

    legacy_ids = [label.chunk_id for label in ground_truth.labels]
    generated_ids = [candidate.chunk_id for candidate in candidates.candidates]
    if generated_ids != legacy_ids:
        raise ValueError(
            "Generated Microsoft candidate chunk IDs do not exactly match existing ground truth."
        )

    print(f"Validated Microsoft candidates: {len(candidates.candidates)}")
    print("Validated exact candidate ID order against existing human-reviewed ground truth.")
    print(f"Validated migrated evaluation ranking: {len(evaluation.evidence)}")
    if dry_run:
        print("Dry run complete; no files were written.")
        return

    existing_manifest = load_manifest() if MANIFEST_PATH.exists() else None
    manifest = build_manifest(existing=existing_manifest)
    write_json_guarded(
        MANIFEST_PATH,
        manifest,
        allow_overwrite=allow_overwrite,
    )
    write_text_guarded(
        BENCHMARK_ROOT.parent.parent / "README.md",
        EVALUATION_README,
        allow_overwrite=allow_overwrite,
    )
    write_text_guarded(
        BENCHMARK_ROOT / "README.md",
        BENCHMARK_README,
        allow_overwrite=allow_overwrite,
    )
    write_text_guarded(
        BENCHMARK_ROOT / "annotation_guidelines.md",
        ANNOTATION_GUIDELINES,
        allow_overwrite=allow_overwrite,
    )
    for case in CASES:
        case_dir(case.case_id).mkdir(parents=True, exist_ok=True)

    write_json_guarded(
        search_fixture_path("microsoft_competitors"),
        search_fixture,
        allow_overwrite=allow_overwrite,
    )
    write_json_guarded(
        candidates_path("microsoft_competitors"),
        candidates,
        allow_overwrite=allow_overwrite,
    )
    write_json_guarded(
        ground_truth_path("microsoft_competitors"),
        ground_truth,
        allow_overwrite=allow_overwrite,
    )
    write_json_guarded(
        evaluation_fixture_path("microsoft_competitors"),
        evaluation,
        allow_overwrite=allow_overwrite,
    )
    write_checksums(allow_overwrite=True)
    print(f"Benchmark V2 bootstrapped at: {BENCHMARK_ROOT}")
    print(f"Checksums written to: {CHECKSUMS_PATH}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    migrate(dry_run=args.dry_run, allow_overwrite=args.allow_overwrite)


if __name__ == "__main__":
    main()
