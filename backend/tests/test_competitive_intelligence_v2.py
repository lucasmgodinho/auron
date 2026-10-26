from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.embeddings import Embeddings

from app.modules.competitive_intelligence import vector_store
from app.modules.competitive_intelligence.context_builder import build_research_context
from app.modules.competitive_intelligence.document_processing import (
    chunk_document,
    deduplicate_documents,
    normalize_source_url,
)
from app.modules.competitive_intelligence.errors import ModelProviderError, VectorStoreError
from app.modules.competitive_intelligence.evidence import SourceDocument
from app.modules.competitive_intelligence.question_generation import QuestionPlan
from app.modules.competitive_intelligence.report_generation import (
    OpenAIReportGenerator,
    generate_grounded_report,
)
from app.modules.competitive_intelligence.search import SearchResult, create_source_document
from app.modules.competitive_intelligence.workflow import CompetitiveIntelligenceWorkflow


def source(source_id: str, *, query: str = "Competitors?", **overrides) -> SourceDocument:
    values = dict(
        source_id=source_id, research_query=query, title=f"Title {source_id}",
        url=f"https://example.com/{source_id}", domain="example.com",
        content="A search summary", raw_content="Acme competes with Example Corp.",
        provider_result_id=f"provider_{source_id}", provider_score=0.9, provider_rank=1,
        published_date=datetime(2026, 1, 1, tzinfo=UTC),
        retrieved_at=datetime(2026, 10, 1, tzinfo=UTC), content_source="search_raw",
    )
    values.update(overrides)
    return SourceDocument(**values)


class CountingEmbeddings(Embeddings):
    def __init__(self):
        self.batches = []
        self.queries = []

    def embed_documents(self, texts):
        self.batches.append(list(texts))
        return [[1.0, 0.0] if "Example" in text else [0.0, 1.0] for text in texts]

    def embed_query(self, text):
        self.queries.append(text)
        return [1.0, 0.0]


def evidence_store(embeddings):
    store = object.__new__(vector_store.ChromaEvidenceStore)
    store._embeddings = embeddings
    return store


def test_url_dedup_preserves_all_discovery_metadata_and_prefers_full_content():
    first = source("first", raw_content=None, content_source="search_content")
    second = source(
        "second", query="Market?", url="https://EXAMPLE.com/first?utm_source=test#section",
        title="Updated title", provider_rank=3, content_source="extract_raw",
    )
    documents = deduplicate_documents([first, second])
    assert len(documents) == 1
    selected = documents[0]
    assert selected.source_id == "first"
    assert selected.raw_content == second.raw_content
    assert selected.content_source == "extract_raw"
    assert [p.research_query for p in selected.provenance] == ["Competitors?", "Market?"]
    assert selected.provenance[0].title == first.title
    assert selected.provenance[1].url == second.url
    assert selected.provenance[1].provider_result_id == second.provider_result_id
    assert selected.provenance[1].published_date == second.published_date
    assert selected.provenance[1].provider_score == second.provider_score
    assert selected.provenance[1].provider_rank == 3
    assert selected.provenance[1].content_source == "extract_raw"
    assert first.provenance == []
    assert deduplicate_documents(documents) == documents


def test_content_dedup_uses_processed_text_and_retains_url_aliases():
    first = source("first", raw_content="Acme competes with [Example](https://example.com).")
    second = source("mirror", query="Market?", raw_content="Acme competes with Example.\n\n")
    distinct = source("distinct", raw_content="A different factual document")
    documents = deduplicate_documents([first, second, distinct])
    assert [doc.source_id for doc in documents] == ["first", "distinct"]
    assert [str(p.url) for p in documents[0].provenance] == [str(first.url), str(second.url)]


def test_content_hash_never_uses_a_discarded_summary():
    summary = source("summary", raw_content=None)
    full = source("full", url=str(summary.url))
    other = source("other", raw_content=None)
    documents = deduplicate_documents([summary, full, other])
    assert len(documents) == 2
    assert documents[0].raw_content == full.raw_content


def test_url_normalization_preserves_meaningful_query_parameters():
    assert normalize_source_url("https://EXAMPLE.com:443/page?b=2&a=1&utm_source=x#top") == (
        "https://example.com:443/page?a=1&b=2"
    )
    assert normalize_source_url("https://example.com/page?id=1") != normalize_source_url(
        "https://example.com/page?id=2"
    )


@pytest.mark.parametrize("published", [
    "2026-01-01", "2026-01-01T00:00:00Z", "Thu, 01 Jan 2026 00:00:00 GMT",
])
def test_source_acquisition_retains_publication_date_and_provider_metadata(published):
    document = create_source_document(
        research_query="Competitors?", provider_rank=2,
        result={
            "title": "Source", "url": "https://example.com/source", "content": "Summary",
            "raw_content": "Full content", "published_date": published,
            "id": "provider-id", "score": 0.8,
        },
    )
    assert document.published_date == datetime(2026, 1, 1, tzinfo=UTC)
    assert document.provider_result_id == "provider-id"
    assert document.provider_rank == 2
    assert document.provider_score == 0.8
    assert document.content_source == "search_raw"


def test_real_chroma_batch_retrieval_has_source_metadata_and_reuses_query_vector():
    embeddings = CountingEmbeddings()
    documents = [source("first"), source("other", raw_content="Other market data")]
    store = vector_store.create_vector_store(embeddings=embeddings)
    try:
        vector_store.index_chunks(store, [c for doc in documents for c in chunk_document(doc)])
        query_vector = embeddings.embed_query("Competitors?")
        retrieved = vector_store.retrieve_evidence(
            store, "Competitors?", top_k=1, query_embedding=query_vector, sources=documents,
        )
        assert len(embeddings.batches) == 1
        assert len(embeddings.batches[0]) == 2
        assert embeddings.queries == ["Competitors?"]
        assert retrieved[0].source == documents[0]
        assert retrieved[0].source_id == "first"
        assert retrieved[0].distance == pytest.approx(0.0)
        context = build_research_context(retrieved, documents)
        assert "Title first" in context
        assert "https://example.com/first" in context
        assert "2026-01-01" in context
        assert "Other market data" not in context
        assert "A search summary" not in context
    finally:
        store.delete_collection()


def test_production_workflow_dedups_before_batch_embedding_and_grounds_one_report(monkeypatch):
    monkeypatch.setattr(vector_store, "RETRIEVAL_LIMIT", 1)
    embeddings = CountingEmbeddings()
    first = source("first")
    duplicate = source("duplicate", query="Market?", url=str(first.url))
    mirror = source("mirror", query="Market?")
    unrelated = source("unrelated", raw_content="Unrelated content excluded by retrieval")
    calls = []
    plan = QuestionPlan(sector="Technology", is_valid_company=True,
                        questions=["Competitors?", "Market?"])
    question_calls = []
    def generate(company):
        question_calls.append(company)
        return plan
    workflow = CompetitiveIntelligenceWorkflow(
        question_generator=SimpleNamespace(generate=generate),
        search_client=SimpleNamespace(search=lambda question: SearchResult(
            sources=(), documents=(first,) if question == "Competitors?" else (
                duplicate, mirror, unrelated,
            ),
        )),
        context_store=evidence_store(embeddings),
        report_generator=SimpleNamespace(generate=lambda **kwargs: calls.append(kwargs) or "[E1]"),
    )
    events = list(workflow.stream_analysis(organization_id=uuid4(), company_name="Acme"))
    assert question_calls == ["Acme"]
    assert embeddings.batches == [[first.raw_content, unrelated.raw_content]]
    assert embeddings.queries == plan.questions
    assert len(calls) == 1
    assert calls[0]["context"].count('<EVIDENCE id=') == 1
    assert first.raw_content in calls[0]["context"]
    assert first.content not in calls[0]["context"]
    assert unrelated.raw_content not in calls[0]["context"]
    indexed = next(event.data for event in events if event.type == "documents_indexed")
    assert indexed["documents_selected"] == 4
    assert indexed["unique_sources"] == indexed["documents"] == 2
    assert indexed["chunks_generated"] == indexed["chunks_indexed"] == 2
    assert indexed["searches_executed"] == 2
    assert events[-1].type == "analysis_completed"


def test_index_chunks_bounds_embedding_batches(monkeypatch):
    monkeypatch.setattr(vector_store, "INDEX_BATCH_SIZE", 2)
    embeddings = CountingEmbeddings()
    store = vector_store.create_vector_store(embeddings=embeddings)
    try:
        chunks = [chunk_document(source(str(i)))[0] for i in range(5)]
        vector_store.index_chunks(store, chunks)
        assert [len(batch) for batch in embeddings.batches] == [2, 2, 1]
    finally:
        store.delete_collection()


def test_production_report_reuses_grounded_prompt_in_one_model_call():
    calls = []
    generator = object.__new__(OpenAIReportGenerator)
    generator._model = SimpleNamespace(invoke=lambda messages: (
        calls.append(messages) or SimpleNamespace(content="Acme competes with Example Corp. [E1]")
    ))
    document = source("first")
    context = '<EVIDENCE id="E1">\nContent: ' + document.raw_content + '\n</EVIDENCE>'
    report = generator.generate(company_name="Acme", sector="Technology", context=context)
    assert report.endswith("[E1]")
    assert len(calls) == 1
    assert context in calls[0][1][1]
    assert "Suggested structure:" in calls[0][1][1]
    assert "Use only information supported by the supplied evidence" in calls[0][0][1]


def test_grounded_report_rejects_unknown_citations_without_another_model_call():
    calls = []
    model = SimpleNamespace(invoke=lambda messages: (
        calls.append(messages) or SimpleNamespace(content="Unsupported claim [E99]")
    ))
    with pytest.raises(ModelProviderError, match="unknown evidence"):
        generate_grounded_report("Question", '<EVIDENCE id="E1">Content</EVIDENCE>', model=model)
    assert len(calls) == 1


def test_ephemeral_collections_isolate_tenants_and_executions():
    embeddings = CountingEmbeddings()
    first = vector_store.create_vector_store(embeddings=embeddings)
    second = vector_store.create_vector_store(embeddings=embeddings)
    try:
        vector_store.index_chunks(first, chunk_document(source("tenant_a")))
        vector_store.index_chunks(second, chunk_document(source("tenant_b")))
        assert {e.source_id for e in vector_store.retrieve_evidence(first, "Q")} == {"tenant_a"}
        assert {e.source_id for e in vector_store.retrieve_evidence(second, "Q")} == {"tenant_b"}
    finally:
        first.delete_collection()
        second.delete_collection()


@pytest.mark.parametrize("stage", ["index", "retrieval"])
def test_production_cleans_up_collection_on_provider_failure(monkeypatch, stage):
    deleted = []
    store = SimpleNamespace(delete_collection=lambda: deleted.append(True))
    monkeypatch.setattr(vector_store, "create_vector_store", lambda **kwargs: store)
    def fail(*args, **kwargs):
        raise RuntimeError("private provider failure")
    monkeypatch.setattr(vector_store, "index_chunks", fail if stage == "index" else lambda *a: None)
    monkeypatch.setattr(vector_store, "retrieve_evidence", fail)
    with pytest.raises(VectorStoreError):
        evidence_store(CountingEmbeddings()).index_and_retrieve(
            organization_id=uuid4(), execution_id=uuid4(), questions=["Q"], documents=[source("s")],
        )
    assert deleted == [True]
