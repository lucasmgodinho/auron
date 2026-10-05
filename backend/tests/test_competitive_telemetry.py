import json
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import test_competitive_analysis_runs as runs
from langchain_core.embeddings import Embeddings
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core import tracing
from app.main import app
from app.modules.competitive_intelligence import telemetry
from app.modules.competitive_intelligence.cost_estimation import (
    PricingCatalog,
    TokenPrice,
    estimate_call,
    estimate_run,
)
from app.modules.competitive_intelligence.dependencies import get_competitive_intelligence_workflow
from app.modules.competitive_intelligence.question_generation import (
    OpenAIQuestionGenerator,
    QuestionSuggestion,
)
from app.modules.competitive_intelligence.report_generation import OpenAIReportGenerator
from app.modules.competitive_intelligence.search import TAVILY_SEARCH_URL, TavilySearchClient
from app.modules.competitive_intelligence.telemetry_schemas import ProviderCall
from app.modules.competitive_intelligence.vector_store import ChromaEvidenceStore
from app.modules.competitive_intelligence.workflow import CompetitiveIntelligenceWorkflow

setup = runs.setup


@pytest.fixture
def spans(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(tracing.SafeExporter(exporter)))
    monkeypatch.setattr(telemetry, "get_tracer", lambda: provider.get_tracer("test"))
    yield exporter
    provider.shutdown()


class FakeModel:
    model_name = "gpt-4o-mini"

    def __init__(self, question=False):
        self.question = question

    def invoke(self, messages, config=None):
        message = AIMessage(
            content="Acme has competitors [E1]",
            usage_metadata={
                "input_tokens": 20,
                "output_tokens": 10,
                "total_tokens": 30,
                "input_token_details": {"cache_read": 2},
            },
        )
        for callback in (config or {}).get("callbacks", []):
            callback.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]))
        if self.question:
            return QuestionSuggestion(
                sector="Technology",
                is_valid_company=True,
                questions=["PRIVATE RESEARCH QUERY 1", "PRIVATE RESEARCH QUERY 2"],
            )
        return message


class FakeSDK:
    def create(self, *, input):
        return {
            "data": [{"embedding": [1.0, 0.0]} for _ in input],
            "usage": {"prompt_tokens": 8 * len(input)},
        }


class FakeEmbeddings(Embeddings):
    def __init__(self):
        self.client = telemetry.EmbeddingClientTelemetry(FakeSDK(), "text-embedding-3-small")

    def embed_documents(self, texts):
        return [item["embedding"] for item in self.client.create(input=texts)["data"]]

    def embed_query(self, text):
        return self.client.create(input=[text])["data"][0]["embedding"]


@pytest.fixture
def pipeline(setup, monkeypatch):
    def post(url, **kwargs):
        assert kwargs["json"]["include_usage"] is True
        if url == TAVILY_SEARCH_URL:
            assert kwargs["json"]["include_answer"] is False
            results = [
                {
                    "title": f"Source {i}",
                    "url": f"https://example.com/{i}?token=SECRET",
                    "content": "PRIVATE SEARCH SUMMARY",
                }
                for i in range(3)
            ]
            credits = 2
        else:
            results = [
                {"url": requested, "raw_content": f"PRIVATE PAGE {i} " * 20}
                for i, requested in enumerate(kwargs["json"]["urls"])
            ]
            credits = 1
        return httpx.Response(
            200,
            json={"results": results, "usage": {"credits": credits}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("app.modules.competitive_intelligence.search.httpx.post", post)
    question = object.__new__(OpenAIQuestionGenerator)
    question._max_questions = 40
    question._model = FakeModel(question=True)
    report = object.__new__(OpenAIReportGenerator)
    report._model = FakeModel()
    store = object.__new__(ChromaEvidenceStore)
    store._embeddings = FakeEmbeddings()
    workflow = CompetitiveIntelligenceWorkflow(
        question_generator=question,
        search_client=TavilySearchClient(api_key="SECRET_KEY"),
        context_store=store,
        report_generator=report,
    )
    app.dependency_overrides[get_competitive_intelligence_workflow] = lambda: workflow
    return workflow


def request_run(client, setup, streamed=False):
    response = client.post(
        runs.path(setup.organization.id) + ("/stream" if streamed else ""),
        json={"company_name": "Acme"},
    )
    assert response.status_code == 200
    run_id = response.headers["X-Analysis-Run-ID"] if streamed else response.json()["run_id"]
    detail = client.get(runs.path(setup.organization.id) + f"/{run_id}").json()
    return detail


@pytest.mark.parametrize("streamed", [False, True])
def test_full_trace_and_sanitized_product_snapshot(client, setup, pipeline, spans, streamed):
    detail = request_run(client, setup, streamed)
    snapshot = detail["telemetry"]
    assert snapshot["analysis_run_id"] == detail["id"]
    assert snapshot["pipeline_version"] == "2.0.0"
    assert snapshot["status"] == "completed"
    assert snapshot["total_duration_ms"] > 0
    finished = spans.get_finished_spans()
    root = next(span for span in finished if span.name == "competitive_intelligence.analysis")
    assert root.parent is None
    assert root.attributes["analysis_run_id"] == detail["id"]
    assert root.attributes["organization_id"] == str(setup.organization.id)
    assert snapshot["trace_id"] == f"{root.context.trace_id:032x}"
    assert {span.context.trace_id for span in finished} == {root.context.trace_id}
    expected_stages = {
        "question_generation",
        "web_research",
        "source_acquisition",
        "deduplication",
        "source_processing",
        "chunking",
        "embeddings",
        "retrieval",
        "context_building",
        "report_generation",
    }
    assert expected_stages <= {span.name for span in finished}
    assert all(stage["duration_ms"] > 0 for stage in snapshot["stages"])
    assert all(stage["failures"] == 0 for stage in snapshot["stages"])
    by_id = {span.context.span_id: span.name for span in finished}
    llm_spans = [span for span in finished if span.name == "llm.invoke"]
    assert {by_id[span.parent.span_id] for span in llm_spans} == {
        "question_generation",
        "report_generation",
    }
    assert all(span.attributes["gen_ai.usage.input_tokens"] == 20 for span in llm_spans)
    calls = snapshot["provider_calls"]
    llm = [
        call
        for call in calls
        if call["operation"]
        in {
            "question_generation",
            "report_generation",
        }
    ]
    assert len(llm) == 2
    assert all(
        call["input_tokens"] == 20
        and call["output_tokens"] == 10
        and call["cached_input_tokens"] == 2
        for call in llm
    )
    document_batches = [call for call in calls if call["operation"] == "document_embedding"]
    assert len(document_batches) == 1
    assert document_batches[0]["embedded_units"] == 3
    assert document_batches[0]["input_tokens"] == 24
    assert len([call for call in calls if call["operation"] == "query_embedding"]) == 2
    assert len([call for call in calls if call["operation"] == "search"]) == 2
    extracts = [call for call in calls if call["operation"] == "extract"]
    assert len(extracts) == 2
    assert all(call["successful_extractions"] == 3 for call in extracts)
    assert snapshot["tokens"]["known_input_tokens"] == 80
    assert snapshot["statistics"] == {
        "research_questions": 2,
        "searches_executed": 2,
        "search_failures": 0,
        "source_candidates": 6,
        "sources_before_deduplication": 6,
        "unique_sources": 3,
        "documents_selected": 6,
        "chunks_generated": 3,
        "chunks_indexed": 3,
        "embedding_index_batches": 1,
        "embedding_provider_batches": 3,
        "embedded_units": 5,
        "retrieval_queries": 2,
        "top_k": 5,
        "evidence_retrieved": 3,
        "distinct_evidence_sources": 3,
        "context_characters": snapshot["statistics"]["context_characters"],
    }
    assert snapshot["statistics"]["context_characters"] > 0
    assert {item["source_key"] for item in snapshot["evidence"]} == {
        source["source_key"] for source in detail["sources"]
    }
    assert [item["chunk_id"] for item in snapshot["evidence"]] == [
        item["chunk_id"] for item in detail["evidence"]
    ]
    serialized = json.dumps(snapshot) + str([dict(span.attributes) for span in finished])
    for private in ("SECRET", "PRIVATE PAGE", "PRIVATE RESEARCH", "PRIVATE SEARCH", "Acme"):
        assert private not in serialized
    assert snapshot["cost"]["estimated_total"] is None


def test_failed_stage_has_safe_failure_snapshot(client, setup, pipeline, spans, monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ConnectError("SECRET_PROVIDER_MESSAGE")

    monkeypatch.setattr("app.modules.competitive_intelligence.search.httpx.post", fail)
    response = client.post(runs.path(setup.organization.id), json={"company_name": "Acme"})
    assert response.status_code == 502
    run_id = response.headers["X-Analysis-Run-ID"]
    detail = client.get(runs.path(setup.organization.id) + f"/{run_id}").json()
    assert detail["status"] == "failed"
    snapshot = detail["telemetry"]
    assert snapshot["status"] == "failed"
    assert snapshot["statistics"]["search_failures"] == 2
    assert snapshot["total_duration_ms"] > 0
    assert any(
        stage["name"] == "web_research" and stage["failures"] for stage in snapshot["stages"]
    )
    assert "SECRET_PROVIDER_MESSAGE" not in json.dumps(snapshot)
    root = next(
        span
        for span in spans.get_finished_spans()
        if span.name == "competitive_intelligence.analysis"
    )
    assert root.status.status_code.name == "ERROR"


def test_exporter_failure_cannot_fail_analysis(client, setup, pipeline, monkeypatch):
    exporter = SimpleNamespace(
        export=lambda spans: (_ for _ in ()).throw(RuntimeError("secret")), shutdown=lambda: None
    )
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(tracing.SafeExporter(exporter)))
    monkeypatch.setattr(telemetry, "get_tracer", lambda: provider.get_tracer("failure"))
    try:
        assert request_run(client, setup)["status"] == "completed"
    finally:
        provider.shutdown()


def test_disabled_exporter_and_disabled_sdk(client, setup, pipeline, monkeypatch):
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "none")
    provider = tracing.create_provider()
    assert isinstance(provider, TracerProvider)
    provider.shutdown()
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    monkeypatch.setattr(
        telemetry, "get_tracer", lambda: tracing.create_provider().get_tracer("off")
    )
    detail = request_run(client, setup)
    assert detail["telemetry"]["trace_id"] is None
    assert detail["telemetry"]["statistics"]["chunks_indexed"] == 3


def test_snapshot_failure_cannot_invalidate_report(client, setup, pipeline, monkeypatch):
    monkeypatch.setattr(
        telemetry.RunRecorder,
        "snapshot",
        lambda *args: (_ for _ in ()).throw(RuntimeError("broken telemetry")),
    )
    detail = request_run(client, setup)
    assert detail["status"] == "completed"
    assert detail["report"]
    assert detail["telemetry"] is None


def test_telemetry_is_tenant_scoped(client, setup, pipeline, db_session):
    detail = request_run(client, setup)
    other = runs.organization_service.create_organization(db_session, "Other", setup.owner.id)
    runs.module_service.set_organization_module(
        db_session,
        organization_id=other.id,
        module_key=runs.MODULE_KEY,
        enabled=True,
        registry=runs.production_module_registry,
    )
    assert client.get(runs.path(other.id) + f"/{detail['id']}").status_code == 404
    assert client.get(runs.path(other.id)).json()["items"] == []
    client.cookies.clear()
    assert client.get(runs.path(setup.organization.id) + f"/{detail['id']}").status_code == 401


def test_known_and_unknown_costs_use_decimal():
    pricing = PricingCatalog(
        version="test-v1",
        models={
            "openai:chat": TokenPrice(
                input_per_million="1", cached_input_per_million="0.5", output_per_million="2"
            ),
            "openai:embed": TokenPrice(input_per_million="0.1"),
        },
        tavily_credit_usd="0.01",
    )
    chat = ProviderCall(
        provider="openai",
        model="chat",
        operation="report_generation",
        input_tokens=100,
        cached_input_tokens=20,
        output_tokens=10,
    )
    embedding = ProviderCall(
        provider="openai", model="embed", operation="document_embedding", input_tokens=100
    )
    search = ProviderCall(provider="tavily", operation="search", usage_credits="2")
    assert estimate_call(chat, pricing) == Decimal("0.00011")
    assert estimate_call(embedding, pricing) == Decimal("0.00001")
    assert estimate_call(search, pricing) == Decimal("0.02")
    total = estimate_run([chat, embedding, search], pricing)
    assert total.estimated_total == Decimal("0.02012")
    assert total.pricing_version == "test-v1"
    unknown = ProviderCall(provider="openai", model="unknown", operation="query_embedding")
    partial = estimate_run([chat, unknown], pricing)
    assert partial.estimated_total is None
    assert partial.status == "partial" and partial.known_subtotal == Decimal("0.00011")
    assert estimate_run([unknown], pricing).known_subtotal is None
    assert estimate_call(chat.model_copy(update={"cached_input_tokens": None}), pricing) is None
    assert estimate_call(search.model_copy(update={"usage_credits": None}), pricing) is None
    assert estimate_run([], pricing).estimated_total is None


def test_configured_pricing_is_persisted_without_pipeline_changes(
    client,
    setup,
    pipeline,
    tmp_path,
    monkeypatch,
):
    catalog = tmp_path / "pricing.json"
    catalog.write_text(
        json.dumps(
            {
                "version": "test-catalog-v1",
                "tavily_credit_usd": "0.01",
                "models": {
                    "openai:gpt-4o-mini": {
                        "input_per_million": "1",
                        "cached_input_per_million": "0.5",
                        "output_per_million": "2",
                    },
                    "openai:text-embedding-3-small": {"input_per_million": "0.1"},
                },
            }
        )
    )
    monkeypatch.setattr(telemetry, "get_settings", lambda: SimpleNamespace(ci_pricing_file=catalog))
    snapshot = request_run(client, setup)["telemetry"]
    assert snapshot["cost"]["pricing_version"] == "test-catalog-v1"
    assert snapshot["cost"]["status"] == "estimated"
    assert Decimal(snapshot["cost"]["estimated_total"]) == Decimal("0.060082")
    assert all(call["estimated_cost_usd"] is not None for call in snapshot["provider_calls"])


def test_partial_extractions_record_retry_and_missing_usage(monkeypatch):
    requests = []

    def post(url, **kwargs):
        requested = kwargs["json"]["urls"]
        requests.append(requested)
        results = [
            {"url": value, "raw_content": "private page"}
            for value in (requested[:1] if len(requests) == 1 else requested)
        ]
        return httpx.Response(200, json={"results": results}, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.modules.competitive_intelligence.search.httpx.post", post)
    recorder = telemetry.RunRecorder(
        SimpleNamespace(id=uuid4(), organization_id=uuid4(), pipeline_version="2.0.0")
    )
    docs = [runs.source(f"doc-{i}").model_copy(update={"raw_content": None}) for i in range(3)]
    with recorder.bind():
        selected = TavilySearchClient(api_key="secret")._acquire_raw_content(docs)
    recorder.finish("completed")
    snapshot = recorder.snapshot("completed")
    assert all(doc.raw_content for doc in selected)
    assert [call.retry_count for call in snapshot.provider_calls] == [0, 1]
    assert [call.successful_extractions for call in snapshot.provider_calls] == [1, 2]
    assert [call.failed_extractions for call in snapshot.provider_calls] == [2, 0]
    assert all(call.usage_credits is None for call in snapshot.provider_calls)
    assert snapshot.cost.estimated_total is None


def test_unavailable_embedding_usage_and_hidden_llm_retries_are_not_zero():
    recorder = telemetry.RunRecorder(
        SimpleNamespace(id=uuid4(), organization_id=uuid4(), pipeline_version="2.0.0")
    )
    client = SimpleNamespace(create=lambda **kwargs: {"data": []})
    with recorder.bind():
        telemetry.EmbeddingClientTelemetry(client, "embed").create(input=["private"])
        with telemetry.provider_call("openai", "question_generation", model="chat") as call:
            callback = telemetry.UsageCallback(call)
            callback.on_retry(None)
            assert call.retry_count == 1
    recorder.finish("completed")
    snapshot = recorder.snapshot("completed")
    assert snapshot.provider_calls[0].input_tokens is None
    assert snapshot.provider_calls[0].retry_count is None
    assert snapshot.tokens.calls_with_unknown_usage == 2


def test_invalid_tracing_and_pricing_configuration_degrade_gracefully(
    client,
    setup,
    pipeline,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "invalid")
    monkeypatch.setattr(
        telemetry, "get_tracer", lambda: tracing.create_provider().get_tracer("bad")
    )
    monkeypatch.setattr(
        telemetry,
        "get_settings",
        lambda: SimpleNamespace(ci_pricing_file=tmp_path / "missing.json"),
    )
    detail = request_run(client, setup)
    assert detail["status"] == "completed"
    assert detail["telemetry"]["trace_id"] is None
    assert detail["telemetry"]["cost"]["pricing_version"] == "unavailable"


def test_telemetry_persistence_failure_keeps_completed_report(client, setup, pipeline, monkeypatch):
    original_factory = app.dependency_overrides[runs.get_analysis_run_session_factory]()

    @contextmanager
    def failing_snapshot_factory():
        with original_factory() as session:
            original_commit = session.commit

            def commit():
                if any(
                    isinstance(row, runs.CompetitiveAnalysisRun) and row.telemetry is not None
                    for row in session.dirty
                ):
                    raise RuntimeError("Telemetry commit unavailable")
                original_commit()

            session.commit = commit
            yield session

    monkeypatch.setitem(
        app.dependency_overrides,
        runs.get_analysis_run_session_factory,
        lambda: failing_snapshot_factory,
    )
    detail = request_run(client, setup)
    assert detail["status"] == "completed" and detail["report"]
    assert detail["telemetry"] is None


def test_otlp_configuration_uses_official_exporter_without_network(monkeypatch):
    from opentelemetry.exporter.otlp.proto.grpc import trace_exporter

    exporter = InMemorySpanExporter()
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "otlp")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "auron-test-service")
    monkeypatch.setattr(trace_exporter, "OTLPSpanExporter", lambda: exporter)
    provider = tracing.create_provider()
    try:
        with provider.get_tracer("test").start_as_current_span("example"):
            pass
        assert provider.force_flush()
        assert len(exporter.get_finished_spans()) == 1
        assert provider.resource.attributes["service.name"] == "auron-test-service"
    finally:
        provider.shutdown()
