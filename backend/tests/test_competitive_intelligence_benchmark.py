import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.modules.competitive_intelligence.evidence import (
    RetrievedEvidence,
    SourceDocument,
)
from app.modules.competitive_intelligence.retrieval_evaluation import (
    evaluate_retrieval,
    reciprocal_rank,
)
from app.modules.competitive_intelligence.search import SearchResult
from app.scripts.competitive_intelligence_benchmark import benchmark_io
from app.scripts.competitive_intelligence_benchmark.benchmark_models import (
    BenchmarkSearchFixture,
    GroundTruthLabel,
    RetrievalCandidate,
    RetrievalCandidatesFixture,
    RetrievalGroundTruthFixture,
)
from app.scripts.competitive_intelligence_benchmark.evaluate_benchmark import (
    aggregate_results,
)
from app.scripts.competitive_intelligence_benchmark.prepare_benchmark_case import (
    capture_evaluation,
    capture_search,
)

LEGACY_FIXTURES = Path(__file__).resolve().parents[1] / "app" / "scripts" / "fixtures"
MICROSOFT_QUESTION = "Who are Microsoft's main competitors in the technology sector?"


def _source(*, source_id: str = "src_test") -> SourceDocument:
    return SourceDocument(
        source_id=source_id,
        research_query=MICROSOFT_QUESTION,
        title="Test source",
        url="https://example.com/source",
        domain="example.com",
        content="Microsoft competitors include Example Corp.",
        raw_content="Microsoft competitors include Example Corp.",
        provider_rank=1,
        content_source="search_raw",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _candidate(chunk_id: str, *, source_id: str = "src_test") -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id,
        source_id=source_id,
        source_rank=1,
        url="https://example.com/source",
        domain="example.com",
        title="Test source",
        chunk_index=0,
        token_count=5,
        text="Microsoft competitors include Example Corp.",
    )


def _candidates(*chunk_ids: str) -> RetrievalCandidatesFixture:
    candidates = [_candidate(chunk_id) for chunk_id in chunk_ids]
    return RetrievalCandidatesFixture(
        schema_version="1.0.0",
        case_id="microsoft_competitors",
        research_question=MICROSOFT_QUESTION,
        normalization_version="test",
        chunk_size_tokens=512,
        chunk_overlap_tokens=64,
        resolved_tokenizer="o200k_base",
        chunking_configuration_sha256="chunk-config",
        candidate_set_sha256=benchmark_io.candidate_set_sha256(candidates),
        candidates=candidates,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _ground_truth(
    candidates: RetrievalCandidatesFixture,
    labels: list[GroundTruthLabel],
) -> RetrievalGroundTruthFixture:
    return RetrievalGroundTruthFixture(
        schema_version="1.0.0",
        case_id=candidates.case_id,
        research_question=candidates.research_question,
        candidate_set_sha256=candidates.candidate_set_sha256,
        chunking_configuration_sha256=candidates.chunking_configuration_sha256,
        annotation_guideline_version="2.0.0",
        annotated_at=datetime(2026, 1, 1, tzinfo=UTC),
        annotation_method="human_reviewed",
        labels=labels,
    )


def test_microsoft_golden_retrieval_baseline() -> None:
    ground_truth = json.loads(
        (LEGACY_FIXTURES / "microsoft_competitors_retrieval_ground_truth.json").read_text(
            encoding="utf-8"
        )
    )
    evaluation = json.loads(
        (LEGACY_FIXTURES / "microsoft_competitors_evaluation.json").read_text(
            encoding="utf-8"
        )
    )
    relevance = {item["chunk_id"]: item["relevance"] for item in ground_truth["labels"]}
    ranking = [item["evidence"]["chunk_id"] for item in evaluation["evidence"]]

    assert len(relevance) == 28
    assert {label: list(relevance.values()).count(label) for label in range(3)} == {
        0: 8,
        1: 6,
        2: 14,
    }
    assert [relevance[chunk_id] for chunk_id in ranking] == [2, 1, 1, 2, 1]

    broad = evaluate_retrieval(
        ranked_chunk_ids=ranking,
        relevance_lookup=relevance,
        relevance_threshold=1,
    )
    strict = evaluate_retrieval(
        ranked_chunk_ids=ranking,
        relevance_lookup=relevance,
        relevance_threshold=2,
    )
    broad_at_5 = next(item for item in broad.metrics_at_k if item.k == 5)
    strict_at_5 = next(item for item in strict.metrics_at_k if item.k == 5)

    assert broad_at_5.precision == 1.0
    assert broad_at_5.recall == 0.25
    assert broad_at_5.ndcg == pytest.approx(0.6568, abs=0.0001)
    assert broad.reciprocal_rank == 1.0
    assert strict_at_5.precision == 0.4
    assert strict_at_5.recall == pytest.approx(2 / 14)
    assert strict.reciprocal_rank == 1.0


def test_reciprocal_rank_uses_the_requested_threshold() -> None:
    ranking = ["partial", "irrelevant", "high"]
    relevance = {"partial": 1, "irrelevant": 0, "high": 2}
    assert reciprocal_rank(ranking, relevance, relevance_threshold=1) == 1.0
    assert reciprocal_rank(ranking, relevance, relevance_threshold=2) == pytest.approx(1 / 3)


def test_macro_aggregation_uses_case_means_and_mrr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.scripts.competitive_intelligence_benchmark.evaluate_benchmark.load_manifest",
        lambda: SimpleNamespace(
            benchmark_id="competitive_intelligence_v2",
            benchmark_version="2.0.0",
        ),
    )
    def result(case_id: str, broad: float, strict: float, ndcg: float) -> dict:
        return {
            "case_id": case_id,
            "retrieval": {
                "broad_relevance": {
                    "reciprocal_rank": broad,
                    "metrics_at_k": {
                        str(k): {"precision": broad, "recall": broad, "ndcg": ndcg}
                        for k in (1, 3, 5)
                    },
                },
                "strict_relevance": {
                    "reciprocal_rank": strict,
                    "metrics_at_k": {
                        str(k): {"precision": strict, "recall": strict, "ndcg": ndcg}
                        for k in (1, 3, 5)
                    },
                },
                "graded_relevance": {
                    "ndcg_at_k": {str(k): ndcg for k in (1, 3, 5)}
                },
                "diagnostics": {
                    "candidate_count": 10,
                    "relevance_distribution": {"0": 2, "1": 3, "2": 5},
                },
            },
        }

    summary = aggregate_results(
        [result("a", 1.0, 0.5, 0.8), result("b", 0.5, 0.25, 0.4)],
        failed=[],
        skipped=[],
    )
    assert summary["retrieval_macro"]["broad"]["mrr"] == 0.75
    assert summary["retrieval_macro"]["strict"]["mrr"] == 0.375
    assert summary["retrieval_macro"]["mean_ndcg_at_k"]["5"] == pytest.approx(0.6)


@pytest.mark.parametrize(
    "labels, message",
    [
        ([GroundTruthLabel(chunk_id="a", relevance=2)], "Missing"),
        (
            [
                GroundTruthLabel(chunk_id="a", relevance=2),
                GroundTruthLabel(chunk_id="b", relevance=1),
                GroundTruthLabel(chunk_id="extra", relevance=0),
            ],
            "extra",
        ),
    ],
)
def test_ground_truth_rejects_missing_and_extra_labels(
    labels: list[GroundTruthLabel], message: str
) -> None:
    candidates = _candidates("a", "b")
    ground_truth = _ground_truth(candidates, labels)
    with pytest.raises(ValueError, match=message):
        benchmark_io.validate_ground_truth(ground_truth, candidates)


def test_ground_truth_rejects_duplicate_labels() -> None:
    candidates = _candidates("a")
    with pytest.raises(ValidationError, match="duplicate chunk IDs"):
        _ground_truth(
            candidates,
            [
                GroundTruthLabel(chunk_id="a", relevance=2),
                GroundTruthLabel(chunk_id="a", relevance=1),
            ],
        )


def test_ground_truth_rejects_candidate_hash_mismatch() -> None:
    candidates = _candidates("a")
    ground_truth = _ground_truth(
        candidates, [GroundTruthLabel(chunk_id="a", relevance=2)]
    ).model_copy(update={"candidate_set_sha256": "different"})
    with pytest.raises(ValueError, match="candidate set hash"):
        benchmark_io.validate_ground_truth(ground_truth, candidates)


def test_guarded_write_requires_overwrite_and_rejects_frozen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = benchmark_io.build_manifest()
    manifest_path = tmp_path / "benchmark.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(benchmark_io, "MANIFEST_PATH", manifest_path)
    target = tmp_path / "artifact.json"
    target.write_text('{"old": true}\n', encoding="utf-8")

    with pytest.raises(FileExistsError, match="--allow-overwrite"):
        benchmark_io.write_json_guarded(target, {"new": True})

    manifest.status = "frozen"
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="frozen"):
        benchmark_io.write_json_guarded(target, {"new": True}, allow_overwrite=True)


def test_vector_store_creates_isolated_ephemeral_collections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.competitive_intelligence import vector_store

    clients: list[object] = []
    calls: list[dict] = []

    def ephemeral_client() -> object:
        client = object()
        clients.append(client)
        return client

    def fake_chroma(**kwargs):
        calls.append(kwargs)
        return kwargs

    monkeypatch.setattr(vector_store.chromadb, "EphemeralClient", ephemeral_client)
    monkeypatch.setattr(vector_store, "Chroma", fake_chroma)
    monkeypatch.setattr(vector_store, "get_embeddings", lambda: object())

    vector_store.create_vector_store()
    vector_store.create_vector_store()

    assert len(clients) == 2
    assert calls[0]["client"] is not calls[1]["client"]
    assert calls[0]["collection_name"] != calls[1]["collection_name"]


def test_capture_search_uses_mocked_tavily_and_persists_normalized_documents(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: list[BenchmarkSearchFixture] = []

    class FakeClient:
        def search(self, question: str) -> SearchResult:
            assert question == MICROSOFT_QUESTION
            return SearchResult(answer=None, sources=(), documents=(_source(),))

    monkeypatch.setattr(
        "app.scripts.competitive_intelligence_benchmark.prepare_benchmark_case._load_environment",
        lambda key: "test-key",
    )
    monkeypatch.setattr(
        "app.scripts.competitive_intelligence_benchmark.prepare_benchmark_case.load_manifest",
        lambda: SimpleNamespace(
            search_configuration={"provider": "mock"},
            document_acquisition_configuration={"target_documents": 1},
        ),
    )
    monkeypatch.setattr(
        "app.scripts.competitive_intelligence_benchmark.prepare_benchmark_case.search_fixture_path",
        lambda case_id: tmp_path / f"{case_id}.json",
    )
    monkeypatch.setattr(
        "app.scripts.competitive_intelligence_benchmark.prepare_benchmark_case.write_json_guarded",
        lambda path, value, allow_overwrite=False: captured.append(value),
    )
    monkeypatch.setattr(
        "app.scripts.competitive_intelligence_benchmark.prepare_benchmark_case.write_checksums",
        lambda: None,
    )

    capture_search(
        "microsoft_competitors",
        allow_overwrite=False,
        client_factory=lambda api_key: FakeClient(),
    )
    assert len(captured) == 1
    assert captured[0].documents[0].source_id == "src_test"


def test_capture_evaluation_uses_mocked_openai_pipeline_and_isolated_collection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    candidates = _candidates("src_test_chunk_0")
    ground_truth = _ground_truth(
        candidates,
        [GroundTruthLabel(chunk_id="src_test_chunk_0", relevance=2)],
    )
    search = BenchmarkSearchFixture(
        schema_version="1.0.0",
        case_id="microsoft_competitors",
        research_question=MICROSOFT_QUESTION,
        acquisition_configuration={"provider": "mock"},
        documents=[_source()],
        captured_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    saved = []

    def load_model(path, model_type):
        if model_type is BenchmarkSearchFixture:
            return search
        if model_type is RetrievalCandidatesFixture:
            return candidates
        return ground_truth

    class FakeEmbeddings:
        def embed_query(self, query: str) -> list[float]:
            return [0.1, 0.2, 0.3]

    class FakeStore:
        deleted = False

        def delete_collection(self) -> None:
            self.deleted = True

    store = FakeStore()
    retrieved = RetrievedEvidence(
        chunk_id="src_test_chunk_0",
        source_id="src_test",
        text="Microsoft competitors include Example Corp.",
        query=MICROSOFT_QUESTION,
        distance=0.1,
        rank=1,
    )
    module = "app.scripts.competitive_intelligence_benchmark.prepare_benchmark_case"
    monkeypatch.setattr(f"{module}._load_environment", lambda key: "test-key")
    monkeypatch.setattr(f"{module}.load_json_model", load_model)
    monkeypatch.setattr(f"{module}.get_embeddings", lambda: FakeEmbeddings())
    monkeypatch.setattr(f"{module}.create_vector_store", lambda collection_name: store)
    monkeypatch.setattr(f"{module}.index_chunks", lambda vector_store, chunks: None)
    monkeypatch.setattr(
        f"{module}.retrieve_evidence", lambda vector_store, query, top_k: [retrieved]
    )
    monkeypatch.setattr(f"{module}.build_research_context", lambda retrieved, sources: "context")
    monkeypatch.setattr(
        f"{module}.generate_grounded_report", lambda question, context: "Claim [E1]"
    )
    monkeypatch.setattr(
        f"{module}.load_manifest",
        lambda: SimpleNamespace(
            embedding_configuration={"provider": "mock", "model": "mock"},
            vector_store_configuration={"provider": "chroma"},
            report_configuration={"provider": "mock"},
            prompt_sha256={"report_system": "prompt-hash"},
        ),
    )
    monkeypatch.setattr(f"{module}.evaluation_fixture_path", lambda case_id: tmp_path / "eval.json")
    monkeypatch.setattr(
        f"{module}.write_json_guarded",
        lambda path, value, allow_overwrite=False: saved.append(value),
    )
    monkeypatch.setattr(f"{module}.update_observed_embedding_dimension", lambda value: None)
    monkeypatch.setattr(f"{module}.write_checksums", lambda: None)

    capture_evaluation(
        "microsoft_competitors",
        allow_overwrite=False,
        draft=False,
    )
    assert store.deleted is True
    assert saved[0].isolated_collection_name.startswith("ci_v2_microsoft_competitors_")
    assert saved[0].observed_embedding_dimension == 3
    assert saved[0].ground_truth_status == "validated"
