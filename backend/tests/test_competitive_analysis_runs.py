import json
from contextlib import closing
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import anyio
import pytest
from langchain_core.embeddings import Embeddings
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.access_control import service as access_service
from app.core.auth import service as auth_service
from app.core.auth.dependencies import AUTH_SESSION_COOKIE_NAME
from app.core.module_registry.registry import production_module_registry
from app.core.organization_memberships import repository as membership_repository
from app.core.organization_memberships.model import OrganizationMembership
from app.core.organization_modules import service as module_service
from app.core.organizations import service as organization_service
from app.core.organizations.model import Organization
from app.core.platform_admin.model import PlatformAdmin
from app.core.users import service as user_service
from app.core.users.model import User
from app.main import app
from app.modules.competitive_intelligence import repository, service
from app.modules.competitive_intelligence.definition import MODULE_KEY, RUN_ANALYSIS_PERMISSION
from app.modules.competitive_intelligence.dependencies import (
    get_analysis_run_session_factory,
    get_competitive_intelligence_workflow,
)
from app.modules.competitive_intelligence.document_processing import deduplicate_documents
from app.modules.competitive_intelligence.errors import (
    InvalidCompanyError,
    ModelProviderError,
    NoSearchResultsError,
    SearchProviderError,
    VectorStoreError,
)
from app.modules.competitive_intelligence.evidence import RetrievedEvidence, SourceDocument
from app.modules.competitive_intelligence.model import (
    AnalysisRunEvidence,
    AnalysisRunSource,
    CompetitiveAnalysisRun,
)
from app.modules.competitive_intelligence.question_generation import QuestionPlan
from app.modules.competitive_intelligence.router import AnalysisRunStreamingResponse, _stream_lines
from app.modules.competitive_intelligence.schemas import create_analysis_event
from app.modules.competitive_intelligence.search import SearchResult
from app.modules.competitive_intelligence.vector_store import ChromaEvidenceStore
from app.modules.competitive_intelligence.workflow import (
    CompetitiveAnalysisResult,
    CompetitiveIntelligenceWorkflow,
)


def path(organization_id):
    return f"/organizations/{organization_id}/modules/competitive-intelligence/analyses"


def source(key, query="Competitors?"):
    return SourceDocument(
        source_id=key,
        research_query=query,
        title=f"Title {key}",
        url=f"https://example.com/{key}",
        domain="example.com",
        content="Discarded summary",
        raw_content="FULL PAGE MUST NOT BE STORED " * 100,
        provider_result_id=f"provider-{key}",
        provider_rank=2,
        provider_score=0.9,
        content_source="search_raw",
        published_date=datetime(2026, 1, 1, tzinfo=UTC),
        retrieved_at=datetime(2026, 10, 5, tzinfo=UTC),
    )


def result():
    first = source("source-a")
    alias = source("alias", query="Market?").model_copy(update={"url": first.url})
    first = deduplicate_documents([first, alias])[0]
    second = source("source-b")
    evidence = tuple(
        RetrievedEvidence(
            chunk_id=f"chunk-{i}",
            source_id=document.source_id,
            text=f"Used excerpt {i}",
            query="Competitors?" if i < 3 else "Market?",
            rank=1,
            distance=i / 10,
            source=document,
        )
        for i, document in enumerate([first, first, second], start=1)
    )
    return CompetitiveAnalysisResult(
        company_name="Acme",
        sector="Technology",
        report="Claims [E1][E3]",
        evidence=evidence,
    )


class ScriptedWorkflow:
    def __init__(self, error=None, outcome=None):
        self.error = error
        self.outcome = outcome or result()
        self.calls = []

    def stream_analysis(self, *, organization_id, company_name, run_id, on_completed):
        self.calls.append((organization_id, company_name, run_id))
        yield create_analysis_event("analysis_started", {"company_name": company_name})
        if isinstance(self.error, InvalidCompanyError):
            raise self.error
        yield create_analysis_event(
            "questions_generated",
            {
                "sector": "Technology",
                "questions": ["Competitors?"],
            },
        )
        if self.error:
            raise self.error
        on_completed(self.outcome)
        yield create_analysis_event(
            "analysis_completed",
            {
                "company_name": company_name,
                "sector": self.outcome.sector,
                "report": self.outcome.report,
            },
        )


@pytest.fixture
def setup(client, db_session):
    owner = user_service.create_user(db_session, email="run-owner@example.com", name="Owner")
    organization = organization_service.create_organization(
        db_session, "Run Organization", owner.id
    )
    module_service.set_organization_module(
        db_session,
        organization_id=organization.id,
        module_key=MODULE_KEY,
        enabled=True,
        registry=production_module_registry,
    )
    _, token = auth_service.create_auth_session(db_session, owner.id)
    client.cookies.set(AUTH_SESSION_COOKIE_NAME, token)
    workflow = ScriptedWorkflow()
    app.dependency_overrides[get_competitive_intelligence_workflow] = lambda: workflow
    try:
        yield SimpleNamespace(owner=owner, organization=organization, workflow=workflow)
    finally:
        app.dependency_overrides.pop(get_competitive_intelligence_workflow, None)


def run_service(monkeypatch):
    monkeypatch.setattr(service, "record_event", lambda **kwargs: True)
    return service.AnalysisRunService(app.dependency_overrides[get_analysis_run_session_factory]())


@pytest.mark.parametrize("streamed", [False, True])
def test_success_persists_report_citation_mapping_provenance_and_requester(
    client,
    db_session,
    setup,
    streamed,
):
    response = client.post(
        path(setup.organization.id) + ("/stream" if streamed else ""),
        json={"company_name": " Acme "},
    )
    assert response.status_code == 200
    if streamed:
        events = [json.loads(line) for line in response.text.splitlines()]
        run_id = response.headers["X-Analysis-Run-ID"]
        assert all(event["data"]["run_id"] == run_id for event in events)
        assert events[-1]["type"] == "analysis_completed"
    else:
        run_id = response.json()["run_id"]
    detail = client.get(path(setup.organization.id) + f"/{run_id}").json()
    assert detail["id"] == run_id
    assert detail["organization_id"] == str(setup.organization.id)
    assert detail["requested_by_user_id"] == str(setup.owner.id)
    assert detail["pipeline_version"] == "2.0.0"
    assert detail["company_name"] == "Acme"
    assert detail["sector"] == "Technology"
    assert detail["status"] == "completed"
    assert detail["report"] == "Claims [E1][E3]"
    assert detail["started_at"] and detail["completed_at"]
    assert detail["error_code"] is None
    assert len(detail["sources"]) == 2
    assert [item["evidence_id"] for item in detail["evidence"]] == ["E1", "E2", "E3"]
    assert [item["cited"] for item in detail["evidence"]] == [True, False, True]
    assert [item["retrieval_rank"] for item in detail["evidence"]] == [1, 1, 1]
    source_ids = {item["id"] for item in detail["sources"]}
    assert all(item["source_id"] in source_ids for item in detail["evidence"])
    assert [item["research_query"] for item in detail["sources"][0]["provenance"]] == [
        "Competitors?",
        "Market?",
    ]
    assert detail["sources"][0]["provider_result_id"] == "provider-source-a"
    assert detail["sources"][0]["published_date"].startswith("2026-01-01")
    assert "FULL PAGE" not in str(detail)
    assert "Discarded summary" not in str(detail)
    assert "content" not in AnalysisRunSource.__table__.columns
    assert "raw_content" not in AnalysisRunSource.__table__.columns
    assert setup.workflow.calls == [(setup.organization.id, "Acme", UUID(run_id))]


@pytest.mark.parametrize("streamed", [False, True])
@pytest.mark.parametrize(
    "error,code,http_status",
    [
        (InvalidCompanyError("private detail"), "invalid_company", 422),
        (NoSearchResultsError("private detail"), "no_search_results", 422),
        (SearchProviderError("private detail"), "search_provider_failed", 502),
        (ModelProviderError("private detail"), "model_provider_failed", 502),
        (VectorStoreError("private detail"), "vector_store_failed", 502),
        (RuntimeError("private detail"), "unexpected_error", 500),
    ],
)
def test_execution_failures_persist_a_safe_terminal_run(
    client,
    setup,
    streamed,
    error,
    code,
    http_status,
):
    setup.workflow.error = error
    response = client.post(
        path(setup.organization.id) + ("/stream" if streamed else ""), json={"company_name": "Acme"}
    )
    assert response.status_code == (200 if streamed else http_status)
    run_id = response.headers["X-Analysis-Run-ID"]
    detail_response = client.get(path(setup.organization.id) + f"/{run_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["status"] == "failed"
    assert detail["error_code"] == code
    assert detail["started_at"] and detail["completed_at"]
    assert detail["report"] is None
    assert detail["sources"] == detail["evidence"] == []
    assert detail["sector"] == (None if code == "invalid_company" else "Technology")
    assert "private detail" not in detail_response.text + response.text


def test_pending_running_and_terminal_transitions_are_guarded(client, setup, monkeypatch):
    lifecycle = run_service(monkeypatch)
    run = lifecycle.create_run(
        organization_id=setup.organization.id,
        requested_by_user_id=setup.owner.id,
        company_name="Acme",
    )
    assert run.status == "pending"
    assert run.started_at is run.completed_at is None
    with pytest.raises(service.InvalidRunTransitionError):
        lifecycle.complete_run(organization_id=run.organization_id, run_id=run.id, result=result())
    lifecycle.start_run(organization_id=run.organization_id, run_id=run.id)
    assert client.get(path(run.organization_id) + f"/{run.id}").json()["status"] == "running"
    with pytest.raises(service.InvalidRunTransitionError):
        lifecycle.start_run(organization_id=run.organization_id, run_id=run.id)
    lifecycle.complete_run(organization_id=run.organization_id, run_id=run.id, result=result())
    lifecycle.cancel_if_active(organization_id=run.organization_id, run_id=run.id)
    with pytest.raises(service.InvalidRunTransitionError):
        lifecycle.fail_run(
            organization_id=run.organization_id, run_id=run.id, code="unexpected_error"
        )
    assert client.get(path(run.organization_id) + f"/{run.id}").json()["status"] == "completed"


def test_completion_is_atomic_when_an_evidence_insert_fails(client, setup, monkeypatch):
    lifecycle = run_service(monkeypatch)
    run = lifecycle.create_run(
        organization_id=setup.organization.id,
        requested_by_user_id=setup.owner.id,
        company_name="Acme",
    )
    outcome = result()
    outcome.evidence[1].chunk_id = outcome.evidence[0].chunk_id
    events = list(lifecycle.stream_run(run, ScriptedWorkflow(outcome=outcome)))
    assert events[-1].type == "analysis_failed"
    detail = client.get(path(run.organization_id) + f"/{run.id}").json()
    assert detail["status"] == "failed"
    assert detail["sources"] == detail["evidence"] == []
    assert detail["report"] is None


@pytest.mark.parametrize("started", [False, True])
def test_stream_closure_cancels_pending_or_running_run(client, setup, monkeypatch, started):
    lifecycle = run_service(monkeypatch)
    run = lifecycle.create_run(
        organization_id=setup.organization.id,
        requested_by_user_id=setup.owner.id,
        company_name="Acme",
    )

    async def consume_then_disconnect():
        lines = _stream_lines(lifecycle.stream_run(run, setup.workflow))
        if started:
            await anext(lines)
            await lines.aclose()
        else:
            response = AnalysisRunStreamingResponse(lifecycle, run, setup.workflow)

            async def disconnected_send(message):
                raise OSError("Client disconnected before headers")

            async def receive():
                return {"type": "http.disconnect"}

            from starlette.requests import ClientDisconnect

            with pytest.raises(ClientDisconnect):
                await response(
                    {"type": "http", "asgi": {"spec_version": "2.4"}}, receive, disconnected_send
                )

    anyio.run(consume_then_disconnect)
    detail = client.get(path(run.organization_id) + f"/{run.id}").json()
    assert detail["status"] == "cancelled"
    assert detail["telemetry"]["status"] == "cancelled"
    assert detail["telemetry"]["analysis_run_id"] == str(run.id)
    assert detail["completed_at"]
    assert bool(detail["started_at"]) == started
    assert detail["report"] is None
    with pytest.raises(service.InvalidRunTransitionError):
        lifecycle.start_run(organization_id=run.organization_id, run_id=run.id)


def test_list_is_recent_paginated_and_excludes_other_tenants(
    client, setup, db_session, monkeypatch
):
    lifecycle = run_service(monkeypatch)
    run_ids = [
        lifecycle.create_run(
            organization_id=setup.organization.id,
            requested_by_user_id=setup.owner.id,
            company_name=str(i),
        ).id
        for i in range(3)
    ]
    other = organization_service.create_organization(db_session, "Other Tenant", setup.owner.id)
    # PostgreSQL now() is fixed within the fixture's outer rollback transaction.
    for index, run_id in enumerate(run_ids, start=1):
        stored = repository.get_run(
            db_session,
            organization_id=setup.organization.id,
            run_id=run_id,
        )
        stored.created_at = datetime(2026, 1, index, tzinfo=UTC)
    db_session.flush()
    foreign = lifecycle.create_run(
        organization_id=other.id, requested_by_user_id=setup.owner.id, company_name="Foreign"
    )
    page = client.get(path(setup.organization.id), params={"limit": 2, "offset": 1}).json()
    assert page["total"] == 3
    assert len(page["items"]) == 2
    assert all(item["organization_id"] == str(setup.organization.id) for item in page["items"])
    assert "report" not in page["items"][0]
    assert client.get(path(setup.organization.id) + f"/{foreign.id}").status_code == 404
    assert client.get(path(setup.organization.id) + f"/{uuid4()}").status_code == 404
    assert client.get(path(setup.organization.id), params={"limit": 101}).status_code == 422
    assert client.get(path(setup.organization.id), params={"offset": -1}).status_code == 422
    recent = client.get(path(setup.organization.id)).json()["items"]
    assert [item["id"] for item in recent] == [str(item) for item in reversed(run_ids)]
    with pytest.raises(service.AnalysisRunNotFoundError):
        lifecycle.start_run(organization_id=setup.organization.id, run_id=foreign.id)


@pytest.mark.parametrize("detail", [False, True])
def test_history_requires_authentication_entitlement_membership_and_permission(
    client,
    setup,
    db_session,
    monkeypatch,
    detail,
):
    lifecycle = run_service(monkeypatch)
    run = lifecycle.create_run(
        organization_id=setup.organization.id,
        requested_by_user_id=setup.owner.id,
        company_name="Acme",
    )
    endpoint = path(setup.organization.id) + (f"/{run.id}" if detail else "")
    client.cookies.clear()
    assert client.get(endpoint).status_code == 401
    member = user_service.create_user(db_session, email="history-member@example.com", name="Member")
    db_session.add(PlatformAdmin(user_id=member.id))
    db_session.flush()
    _, token = auth_service.create_auth_session(db_session, member.id)
    client.cookies.set(AUTH_SESSION_COOKIE_NAME, token)
    assert client.get(endpoint).status_code == 403
    membership = membership_repository.create_membership(
        db_session,
        organization_id=setup.organization.id,
        user_id=member.id,
        role="admin",
    )
    assert client.get(endpoint).status_code == 403
    group = access_service.create_access_group(
        db_session,
        organization_id=setup.organization.id,
        name="Analysts",
        description=None,
    )
    access_service.replace_access_group_permissions(
        db_session,
        organization_id=setup.organization.id,
        access_group_id=group.id,
        permission_keys=[RUN_ANALYSIS_PERMISSION],
        registry=production_module_registry,
    )
    access_service.replace_access_group_memberships(
        db_session,
        organization_id=setup.organization.id,
        access_group_id=group.id,
        membership_ids=[membership.id],
    )
    assert client.get(endpoint).status_code == 200
    module_service.set_organization_module(
        db_session,
        organization_id=setup.organization.id,
        module_key=MODULE_KEY,
        enabled=False,
        registry=production_module_registry,
    )
    assert client.get(endpoint).status_code == 403


def test_database_rejects_cross_tenant_and_cross_run_evidence(
    db_session, setup, client, monkeypatch
):
    lifecycle = run_service(monkeypatch)
    run = lifecycle.create_run(
        organization_id=setup.organization.id,
        requested_by_user_id=setup.owner.id,
        company_name="Acme",
    )
    with closing(lifecycle.stream_run(run, setup.workflow)) as events:
        list(events)
    stored_source = repository.list_sources(
        db_session,
        organization_id=setup.organization.id,
        run_id=run.id,
    )[0]
    other_organization = organization_service.create_organization(
        db_session,
        "Other source tenant",
        setup.owner.id,
    )
    other_tenant_run = lifecycle.create_run(
        organization_id=other_organization.id,
        requested_by_user_id=setup.owner.id,
        company_name="Other",
    )
    other_same_tenant_run = lifecycle.create_run(
        organization_id=setup.organization.id,
        requested_by_user_id=setup.owner.id,
        company_name="Other",
    )
    for organization_id, run_id in [
        (other_organization.id, other_tenant_run.id),
        (setup.organization.id, other_same_tenant_run.id),
    ]:
        with pytest.raises(IntegrityError), db_session.begin_nested():
            db_session.add(
                AnalysisRunEvidence(
                    organization_id=organization_id,
                    run_id=run_id,
                    source_id=stored_source.id,
                    evidence_id="E9",
                    chunk_id="foreign",
                    text="text",
                    query="Q",
                    rank=9,
                    distance=0.2,
                    retrieval_rank=1,
                    cited=True,
                )
            )
            db_session.flush()


def test_lifecycle_commits_are_visible_on_independent_connections(test_engine, monkeypatch):
    monkeypatch.setattr(service, "record_event", lambda **kwargs: True)
    user_id, organization_id = uuid4(), uuid4()
    factory = sessionmaker(bind=test_engine)
    with factory() as session:
        session.add(User(id=user_id, email=f"durable-{user_id}@example.com", name="Durable"))
        session.add(Organization(id=organization_id, name="Durable run test"))
        session.commit()
    lifecycle = service.AnalysisRunService(factory)
    try:
        run = lifecycle.create_run(
            organization_id=organization_id, requested_by_user_id=user_id, company_name="Acme"
        )
        with factory() as reader:
            assert (
                service.get_run(reader, organization_id=organization_id, run_id=run.id).status
                == "pending"
            )
        events = lifecycle.stream_run(run, ScriptedWorkflow(error=ModelProviderError("private")))
        next(events)
        with factory() as reader:
            assert (
                service.get_run(reader, organization_id=organization_id, run_id=run.id).status
                == "running"
            )
        list(events)
        with factory() as reader:
            assert (
                service.get_run(reader, organization_id=organization_id, run_id=run.id).status
                == "failed"
            )
    finally:
        with factory() as session:
            session.execute(
                delete(CompetitiveAnalysisRun).where(
                    CompetitiveAnalysisRun.organization_id == organization_id,
                )
            )
            session.execute(
                delete(OrganizationMembership).where(
                    OrganizationMembership.organization_id == organization_id,
                )
            )
            session.execute(delete(Organization).where(Organization.id == organization_id))
            session.execute(delete(User).where(User.id == user_id))
            session.commit()


@pytest.mark.parametrize("streamed", [False, True])
def test_real_v2_workflow_passes_retrieved_artifacts_to_domain_persistence(client, setup, streamed):
    class FixedEmbeddings(Embeddings):
        def embed_documents(self, texts):
            return [[1.0, 0.0] for text in texts]

        def embed_query(self, text):
            return [1.0, 0.0]

    store = object.__new__(ChromaEvidenceStore)
    store._embeddings = FixedEmbeddings()
    document = source("real-source").model_copy(
        update={
            "raw_content": "Acme competes with Example Corp.",
        }
    )
    plan = QuestionPlan(sector="Technology", is_valid_company=True, questions=["Competitors?"])
    contexts = []
    workflow = CompetitiveIntelligenceWorkflow(
        question_generator=SimpleNamespace(generate=lambda company: plan),
        search_client=SimpleNamespace(
            search=lambda question: SearchResult(
                sources=(),
                documents=(document,),
            )
        ),
        context_store=store,
        report_generator=SimpleNamespace(
            generate=lambda **kwargs: (
                contexts.append(kwargs["context"]) or "Acme competes with Example Corp. [E1]"
            )
        ),
    )
    app.dependency_overrides[get_competitive_intelligence_workflow] = lambda: workflow
    response = client.post(
        path(setup.organization.id) + ("/stream" if streamed else ""), json={"company_name": "Acme"}
    )
    assert response.status_code == 200
    run_id = response.headers["X-Analysis-Run-ID"] if streamed else response.json()["run_id"]
    detail = client.get(path(setup.organization.id) + f"/{run_id}").json()
    assert detail["status"] == "completed"
    assert len(detail["sources"]) == len(detail["evidence"]) == 1
    assert detail["sources"][0]["source_key"] == document.source_id
    assert detail["evidence"][0]["text"] == document.raw_content
    assert detail["evidence"][0]["cited"] is True
    assert detail["evidence"][0]["chunk_id"] == "real-source_chunk_0"
    assert '<EVIDENCE id="E1">' in contexts[0]
    assert "Discarded summary" not in contexts[0]


def test_requester_is_the_authenticated_member_and_cannot_be_spoofed(client, setup, db_session):
    member = user_service.create_user(db_session, email="run-member@example.com", name="Member")
    membership = membership_repository.create_membership(
        db_session,
        organization_id=setup.organization.id,
        user_id=member.id,
        role="member",
    )
    group = access_service.create_access_group(
        db_session,
        organization_id=setup.organization.id,
        name="Requesters",
        description=None,
    )
    access_service.replace_access_group_permissions(
        db_session,
        organization_id=setup.organization.id,
        access_group_id=group.id,
        permission_keys=[RUN_ANALYSIS_PERMISSION],
        registry=production_module_registry,
    )
    access_service.replace_access_group_memberships(
        db_session,
        organization_id=setup.organization.id,
        access_group_id=group.id,
        membership_ids=[membership.id],
    )
    _, token = auth_service.create_auth_session(db_session, member.id)
    client.cookies.set(AUTH_SESSION_COOKIE_NAME, token)
    response = client.post(path(setup.organization.id), json={"company_name": "Acme"})
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    detail = client.get(path(setup.organization.id) + f"/{run_id}").json()
    assert detail["requested_by_user_id"] == str(member.id)
    assert detail["requested_by_user_id"] != str(setup.owner.id)
    spoofed = client.post(
        path(setup.organization.id),
        json={
            "company_name": "Acme",
            "requested_by_user_id": str(setup.owner.id),
        },
    )
    assert spoofed.status_code == 422
    assert len(setup.workflow.calls) == 1


def test_failure_before_running_transition_does_not_leave_pending_run(client, setup, monkeypatch):
    lifecycle = run_service(monkeypatch)
    run = lifecycle.create_run(
        organization_id=setup.organization.id,
        requested_by_user_id=setup.owner.id,
        company_name="Acme",
    )

    def failed_start(**kwargs):
        raise RuntimeError("Unexpected start failure")

    monkeypatch.setattr(lifecycle, "start_run", failed_start)
    events = list(lifecycle.stream_run(run, setup.workflow))
    assert [event.type for event in events] == ["analysis_failed"]
    detail = client.get(path(setup.organization.id) + f"/{run.id}").json()
    assert detail["status"] == "failed"
    assert detail["error_code"] == "unexpected_error"
    assert detail["completed_at"]
    assert setup.workflow.calls == []
