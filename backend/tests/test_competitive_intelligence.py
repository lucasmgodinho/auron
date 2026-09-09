import json
from collections import Counter
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.access_control import service as access_service
from app.core.application_events.model import ApplicationEvent
from app.core.auth import service as auth_service
from app.core.auth.dependencies import AUTH_SESSION_COOKIE_NAME
from app.core.module_registry.registry import production_module_registry
from app.core.organization_memberships import repository as membership_repository
from app.core.organization_modules import service as module_service
from app.core.organizations import service as organization_service
from app.core.users import service as user_service
from app.main import app
from app.modules.competitive_intelligence.definition import (
    MODULE_DEFINITION,
    MODULE_KEY,
    RUN_ANALYSIS_PERMISSION,
)
from app.modules.competitive_intelligence.dependencies import (
    get_competitive_intelligence_workflow,
)
from app.modules.competitive_intelligence.errors import (
    InvalidCompanyError,
    ModelProviderError,
    NoSearchResultsError,
    SearchProviderError,
    VectorStoreError,
)
from app.modules.competitive_intelligence.question_generation import QuestionPlan
from app.modules.competitive_intelligence.schemas import (
    AnalysisEvent,
    create_analysis_event,
)
from app.modules.competitive_intelligence.search import (
    SearchResult,
    SearchSource,
    TavilySearchClient,
)
from app.modules.competitive_intelligence.vector_store import (
    ChromaContextStore,
    ContextRetrievalResult,
)
from app.modules.competitive_intelligence.workflow import (
    CompetitiveAnalysisResult,
    CompetitiveIntelligenceWorkflow,
)


class StubWorkflow:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, str]] = []
        self.stream_calls: list[tuple[UUID, str]] = []
        self.error: Exception | None = None
        self.stream_error: Exception | None = None
        self.stream_events: list[AnalysisEvent] | None = None

    def analyze(
        self, *, organization_id: UUID, company_name: str
    ) -> CompetitiveAnalysisResult:
        self.calls.append((organization_id, company_name))
        if self.error is not None:
            raise self.error
        return CompetitiveAnalysisResult(
            company_name=company_name,
            sector="Automotive",
            report="# Competitive report",
        )

    def stream_analysis(
        self, *, organization_id: UUID, company_name: str
    ) -> Iterator[AnalysisEvent]:
        self.stream_calls.append((organization_id, company_name))
        events = self.stream_events or [
            create_analysis_event("analysis_started", {"company_name": company_name}),
        ]
        yield from events
        if self.stream_error is not None:
            raise self.stream_error
        if self.stream_events is None:
            yield create_analysis_event(
                "analysis_completed",
                {
                    "company_name": company_name,
                    "sector": "Automotive",
                    "report": "# Competitive report",
                },
            )


class FakeQuestionGenerator:
    def __init__(self, plan: QuestionPlan | Exception) -> None:
        self.plan = plan

    def generate(self, company_name: str) -> QuestionPlan:
        del company_name
        if isinstance(self.plan, Exception):
            raise self.plan
        return self.plan


class FakeSearchClient:
    def __init__(self, answers: dict[str, SearchResult | Exception]) -> None:
        self.answers = answers

    def search(self, question: str) -> SearchResult:
        answer = self.answers[question]
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakeContextStore:
    def __init__(
        self,
        result: ContextRetrievalResult | Exception | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result = result

    def index_and_retrieve(self, **kwargs: Any) -> ContextRetrievalResult:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        if self.result is not None:
            return self.result
        document_count = len(kwargs["documents"])
        return ContextRetrievalResult(
            context="trusted retrieved context",
            documents_indexed=document_count,
            embedding_units_indexed=document_count,
            embedding_units_retrieved=document_count,
        )


class FakeReportGenerator:
    def __init__(self, report: str | Exception = "# Report") -> None:
        self.report = report
        self.calls: list[dict[str, str]] = []

    def generate(self, **kwargs: str) -> str:
        self.calls.append(kwargs)
        if isinstance(self.report, Exception):
            raise self.report
        return self.report


@pytest.fixture
def stub_workflow(client: TestClient) -> Iterator[StubWorkflow]:
    workflow = StubWorkflow()
    app.dependency_overrides[get_competitive_intelligence_workflow] = lambda: workflow
    try:
        yield workflow
    finally:
        app.dependency_overrides.pop(get_competitive_intelligence_workflow, None)


def create_user(session: Session, email: str):
    return user_service.create_user(session, email=email, name="Competitive User")


def authenticate(client: TestClient, session: Session, user_id: UUID) -> None:
    _, raw_token = auth_service.create_auth_session(session, user_id)
    client.cookies.set(AUTH_SESSION_COOKIE_NAME, raw_token)


def enable_module(session: Session, organization_id: UUID) -> None:
    module_service.set_organization_module(
        session,
        organization_id=organization_id,
        module_key=MODULE_KEY,
        enabled=True,
        registry=production_module_registry,
    )


def analysis_path(organization_id: UUID) -> str:
    return (
        f"/organizations/{organization_id}/modules/"
        "competitive-intelligence/analyses"
    )


def stream_path(organization_id: UUID) -> str:
    return f"{analysis_path(organization_id)}/stream"


def parse_ndjson(response_text: str) -> list[dict[str, Any]]:
    assert response_text.endswith("\n")
    return [json.loads(line) for line in response_text.splitlines() if line]


def consume_workflow_stream(
    workflow: CompetitiveIntelligenceWorkflow,
) -> tuple[list[AnalysisEvent], Exception | None]:
    events: list[AnalysisEvent] = []
    iterator = workflow.stream_analysis(
        organization_id=uuid4(),
        company_name="Tesla",
    )
    while True:
        try:
            events.append(next(iterator))
        except StopIteration:
            return events, None
        except Exception as error:
            return events, error


def test_module_is_registered_with_stable_permission() -> None:
    assert production_module_registry.get(MODULE_KEY) is MODULE_DEFINITION
    assert [permission.key for permission in MODULE_DEFINITION.permissions] == [
        RUN_ANALYSIS_PERMISSION
    ]
    assert MODULE_DEFINITION.analytics_provider is None


def test_analysis_event_factory_uses_utc_and_serializes_valid_json() -> None:
    event = create_analysis_event(
        "search_completed",
        {
            "question": "Who competes?",
            "current": 1,
            "total": 1,
            "sources": [{"title": "Source", "url": "https://example.com"}],
            "answer_indexed": True,
        },
    )

    assert event.occurred_at.utcoffset().total_seconds() == 0
    assert json.loads(event.model_dump_json()) == event.model_dump(mode="json")


def test_tavily_search_returns_only_normalized_answer_and_safe_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def post(*args: Any, **kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "answer": "  Trusted answer  ",
                "internal": "must not be exposed",
                "results": [
                    {"title": "  Valid source  ", "url": " https://example.com/a "},
                    {"title": "Unsafe", "url": "javascript:alert(1)"},
                    {"title": "Credentials", "url": "https://user:secret@example.com"},
                    {"title": "Malformed", "url": "https://exa mple.com"},
                    {"title": 42, "url": "https://example.com/ignored"},
                ],
            },
        )

    monkeypatch.setattr(
        "app.modules.competitive_intelligence.search.httpx.post",
        post,
    )

    result = TavilySearchClient(api_key="secret").search("Question")

    assert result == SearchResult(
        answer="Trusted answer",
        sources=(SearchSource(title="Valid source", url="https://example.com/a"),),
    )
    assert captured["json"] == {
        "query": "Question",
        "search_depth": "advanced",
        "max_results": 2,
        "include_answer": True,
    }


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"answer": 42, "results": []},
        {"answer": "Answer", "results": {}},
    ],
)
def test_tavily_search_rejects_invalid_payloads(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    monkeypatch.setattr(
        "app.modules.competitive_intelligence.search.httpx.post",
        lambda *args, **kwargs: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: payload,
        ),
    )

    with pytest.raises(SearchProviderError):
        TavilySearchClient(api_key="secret").search("Question")


def test_tavily_search_maps_http_and_json_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed_post(*args: Any, **kwargs: Any) -> None:
        raise httpx.ConnectError("provider unavailable")

    monkeypatch.setattr(
        "app.modules.competitive_intelligence.search.httpx.post",
        failed_post,
    )
    with pytest.raises(SearchProviderError):
        TavilySearchClient(api_key="secret").search("Question")

    monkeypatch.setattr(
        "app.modules.competitive_intelligence.search.httpx.post",
        lambda *args, **kwargs: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: (_ for _ in ()).throw(ValueError("invalid json")),
        ),
    )
    with pytest.raises(SearchProviderError):
        TavilySearchClient(api_key="secret").search("Question")


def test_analysis_requires_entitlement_and_uses_validated_organization(
    client: TestClient,
    db_session: Session,
    stub_workflow: StubWorkflow,
) -> None:
    owner = create_user(db_session, "competitive-owner@example.com")
    organization = organization_service.create_organization(
        db_session, "Competitive Organization", owner.id
    )
    authenticate(client, db_session, owner.id)

    denied = client.post(
        analysis_path(organization.id),
        json={"company_name": "Tesla"},
    )
    assert denied.status_code == 403
    assert stub_workflow.calls == []

    enable_module(db_session, organization.id)
    allowed = client.post(
        analysis_path(organization.id),
        json={"company_name": "  Tesla  "},
    )
    assert allowed.status_code == 200
    assert allowed.json() == {
        "company_name": "Tesla",
        "sector": "Automotive",
        "report": "# Competitive report",
    }
    assert stub_workflow.calls == [(organization.id, "Tesla")]


def test_stream_requires_authentication_entitlement_and_uses_validated_organization(
    client: TestClient,
    db_session: Session,
    stub_workflow: StubWorkflow,
) -> None:
    owner = create_user(db_session, "competitive-stream-owner@example.com")
    organization = organization_service.create_organization(
        db_session, "Competitive Stream Organization", owner.id
    )

    assert client.post(
        stream_path(organization.id),
        json={"company_name": "Tesla"},
    ).status_code == 401

    authenticate(client, db_session, owner.id)
    assert client.post(
        stream_path(organization.id),
        json={"company_name": "Tesla"},
    ).status_code == 403

    enable_module(db_session, organization.id)
    response = client.post(
        stream_path(organization.id),
        json={"company_name": "  Tesla  "},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert response.headers["cache-control"] == "no-store"
    assert [event["type"] for event in parse_ndjson(response.text)] == [
        "analysis_started",
        "analysis_completed",
    ]
    assert stub_workflow.stream_calls == [(organization.id, "Tesla")]


def test_member_requires_explicit_permission(
    client: TestClient,
    db_session: Session,
    stub_workflow: StubWorkflow,
) -> None:
    owner = create_user(db_session, "competitive-group-owner@example.com")
    member = create_user(db_session, "competitive-group-member@example.com")
    organization = organization_service.create_organization(
        db_session, "Competitive Group Organization", owner.id
    )
    membership = membership_repository.create_membership(
        db_session,
        organization_id=organization.id,
        user_id=member.id,
        role="member",
    )
    enable_module(db_session, organization.id)
    authenticate(client, db_session, member.id)

    assert client.post(
        analysis_path(organization.id),
        json={"company_name": "Tesla"},
    ).status_code == 403

    group = access_service.create_access_group(
        db_session,
        organization_id=organization.id,
        name="Competitive Analysts",
        description=None,
    )
    access_service.replace_access_group_permissions(
        db_session,
        organization_id=organization.id,
        access_group_id=group.id,
        permission_keys=[RUN_ANALYSIS_PERMISSION],
        registry=production_module_registry,
    )
    access_service.replace_access_group_memberships(
        db_session,
        organization_id=organization.id,
        access_group_id=group.id,
        membership_ids=[membership.id],
    )

    response = client.post(
        analysis_path(organization.id),
        json={"company_name": "Tesla"},
    )
    assert response.status_code == 200
    assert stub_workflow.calls == [(organization.id, "Tesla")]


def test_stream_member_requires_explicit_permission(
    client: TestClient,
    db_session: Session,
    stub_workflow: StubWorkflow,
) -> None:
    owner = create_user(db_session, "competitive-stream-group-owner@example.com")
    member = create_user(db_session, "competitive-stream-group-member@example.com")
    organization = organization_service.create_organization(
        db_session, "Competitive Stream Group", owner.id
    )
    membership = membership_repository.create_membership(
        db_session,
        organization_id=organization.id,
        user_id=member.id,
        role="member",
    )
    enable_module(db_session, organization.id)
    authenticate(client, db_session, member.id)

    assert client.post(
        stream_path(organization.id),
        json={"company_name": "Tesla"},
    ).status_code == 403

    group = access_service.create_access_group(
        db_session,
        organization_id=organization.id,
        name="Streaming Analysts",
        description=None,
    )
    access_service.replace_access_group_permissions(
        db_session,
        organization_id=organization.id,
        access_group_id=group.id,
        permission_keys=[RUN_ANALYSIS_PERMISSION],
        registry=production_module_registry,
    )
    access_service.replace_access_group_memberships(
        db_session,
        organization_id=organization.id,
        access_group_id=group.id,
        membership_ids=[membership.id],
    )

    assert client.post(
        stream_path(organization.id),
        json={"company_name": "Tesla"},
    ).status_code == 200
    assert stub_workflow.stream_calls == [(organization.id, "Tesla")]


def test_cross_organization_request_never_invokes_workflow(
    client: TestClient,
    db_session: Session,
    stub_workflow: StubWorkflow,
) -> None:
    first_owner = create_user(db_session, "competitive-first@example.com")
    second_owner = create_user(db_session, "competitive-second@example.com")
    first_organization = organization_service.create_organization(
        db_session, "First Competitive Organization", first_owner.id
    )
    second_organization = organization_service.create_organization(
        db_session, "Second Competitive Organization", second_owner.id
    )
    enable_module(db_session, first_organization.id)
    enable_module(db_session, second_organization.id)
    authenticate(client, db_session, first_owner.id)

    response = client.post(
        analysis_path(second_organization.id),
        json={"company_name": "Tesla"},
    )
    assert response.status_code == 403
    assert stub_workflow.calls == []


def test_cross_organization_stream_never_invokes_workflow(
    client: TestClient,
    db_session: Session,
    stub_workflow: StubWorkflow,
) -> None:
    first_owner = create_user(db_session, "competitive-stream-first@example.com")
    second_owner = create_user(db_session, "competitive-stream-second@example.com")
    first_organization = organization_service.create_organization(
        db_session, "First Stream Organization", first_owner.id
    )
    second_organization = organization_service.create_organization(
        db_session, "Second Stream Organization", second_owner.id
    )
    enable_module(db_session, first_organization.id)
    enable_module(db_session, second_organization.id)
    authenticate(client, db_session, first_owner.id)

    response = client.post(
        stream_path(second_organization.id),
        json={"company_name": "Tesla"},
    )

    assert response.status_code == 403
    assert stub_workflow.stream_calls == []


@pytest.mark.parametrize(
    "payload",
    [
        {"company_name": " "},
        {"company_name": "x" * 201},
        {"company_name": "Tesla", "organization_id": "not-authoritative"},
    ],
)
def test_analysis_request_validation_rejects_invalid_payloads(
    client: TestClient,
    db_session: Session,
    stub_workflow: StubWorkflow,
    payload: dict[str, str],
) -> None:
    owner = create_user(db_session, f"request-{uuid4()}@example.com")
    organization = organization_service.create_organization(
        db_session, "Request Validation Organization", owner.id
    )
    enable_module(db_session, organization.id)
    authenticate(client, db_session, owner.id)

    response = client.post(analysis_path(organization.id), json=payload)
    assert response.status_code == 422
    assert stub_workflow.calls == []


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_detail"),
    [
        (
            InvalidCompanyError(),
            422,
            "Company could not be validated",
        ),
        (
            NoSearchResultsError(),
            422,
            "No valid search results were found",
        ),
        (
            SearchProviderError(),
            502,
            "Competitive search provider failed",
        ),
        (
            ModelProviderError(),
            502,
            "Competitive analysis model failed",
        ),
        (
            VectorStoreError(),
            502,
            "Competitive analysis context could not be prepared",
        ),
    ],
)
def test_analysis_maps_expected_domain_failures(
    client: TestClient,
    db_session: Session,
    stub_workflow: StubWorkflow,
    error: Exception,
    expected_status: int,
    expected_detail: str,
) -> None:
    owner = create_user(db_session, f"failure-{uuid4()}@example.com")
    organization = organization_service.create_organization(
        db_session, "Failure Organization", owner.id
    )
    enable_module(db_session, organization.id)
    authenticate(client, db_session, owner.id)
    stub_workflow.error = error

    response = client.post(
        analysis_path(organization.id),
        json={"company_name": "Tesla"},
    )
    assert response.status_code == expected_status
    assert response.json() == {"detail": expected_detail}


def test_unconfigured_module_endpoint_returns_503(
    client: TestClient,
    db_session: Session,
) -> None:
    owner = create_user(db_session, "competitive-unconfigured@example.com")
    organization = organization_service.create_organization(
        db_session, "Unconfigured Organization", owner.id
    )
    enable_module(db_session, organization.id)
    authenticate(client, db_session, owner.id)
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        openai_api_key=None,
        tavily_api_key=None,
    )
    try:
        response = client.post(
            analysis_path(organization.id),
            json={"company_name": "Tesla"},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Competitive Intelligence is not configured"
    }


def test_unconfigured_stream_returns_503_before_stream(
    client: TestClient,
    db_session: Session,
) -> None:
    owner = create_user(db_session, "competitive-stream-unconfigured@example.com")
    organization = organization_service.create_organization(
        db_session, "Unconfigured Stream Organization", owner.id
    )
    enable_module(db_session, organization.id)
    authenticate(client, db_session, owner.id)
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        openai_api_key=None,
        tavily_api_key=None,
    )
    try:
        response = client.post(
            stream_path(organization.id),
            json={"company_name": "Tesla"},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (InvalidCompanyError("internal company detail"), "invalid_company"),
        (NoSearchResultsError("internal result detail"), "no_search_results"),
        (SearchProviderError("raw Tavily response"), "search_provider_failed"),
        (ModelProviderError("raw model response"), "model_provider_failed"),
        (VectorStoreError("raw Chroma detail"), "vector_store_failed"),
        (RuntimeError("secret stack detail"), "unexpected_error"),
    ],
)
def test_stream_maps_failures_to_one_safe_terminal_event(
    client: TestClient,
    db_session: Session,
    stub_workflow: StubWorkflow,
    error: Exception,
    expected_code: str,
) -> None:
    owner = create_user(db_session, f"stream-failure-{uuid4()}@example.com")
    organization = organization_service.create_organization(
        db_session, "Stream Failure Organization", owner.id
    )
    enable_module(db_session, organization.id)
    authenticate(client, db_session, owner.id)
    stub_workflow.stream_error = error

    response = client.post(
        stream_path(organization.id),
        json={"company_name": "Tesla"},
    )
    events = parse_ndjson(response.text)
    terminal_events = [
        event for event in events
        if event["type"] in {"analysis_completed", "analysis_failed"}
    ]

    assert response.status_code == 200
    assert terminal_events == [
        {
            "type": "analysis_failed",
            "occurred_at": terminal_events[0]["occurred_at"],
            "data": {"code": expected_code},
        }
    ]
    assert events[-1] == terminal_events[0]
    assert str(error) not in response.text


def test_stream_stops_after_first_terminal_and_supplies_missing_terminal(
    client: TestClient,
    db_session: Session,
    stub_workflow: StubWorkflow,
) -> None:
    owner = create_user(db_session, "stream-terminal@example.com")
    organization = organization_service.create_organization(
        db_session, "Stream Terminal Organization", owner.id
    )
    enable_module(db_session, organization.id)
    authenticate(client, db_session, owner.id)
    completed = create_analysis_event(
        "analysis_completed",
        {
            "company_name": "Tesla",
            "sector": "Automotive",
            "report": "# Report",
        },
    )
    stub_workflow.stream_events = [
        create_analysis_event("analysis_started", {"company_name": "Tesla"}),
        completed,
        create_analysis_event(
            "search_started",
            {"question": "Must not appear", "current": 1, "total": 1},
        ),
    ]

    response = client.post(
        stream_path(organization.id),
        json={"company_name": "Tesla"},
    )
    assert [event["type"] for event in parse_ndjson(response.text)] == [
        "analysis_started",
        "analysis_completed",
    ]

    stub_workflow.stream_events = [
        create_analysis_event("analysis_started", {"company_name": "Tesla"})
    ]
    response = client.post(
        stream_path(organization.id),
        json={"company_name": "Tesla"},
    )
    events = parse_ndjson(response.text)
    assert events[-1]["type"] == "analysis_failed"
    assert events[-1]["data"] == {"code": "unexpected_error"}


def test_stream_records_durable_started_completed_and_failed_events(
    client: TestClient,
    db_session: Session,
    stub_workflow: StubWorkflow,
) -> None:
    owner = create_user(db_session, "stream-logs@example.com")
    organization = organization_service.create_organization(
        db_session, "Stream Logs Organization", owner.id
    )
    enable_module(db_session, organization.id)
    authenticate(client, db_session, owner.id)

    assert client.post(
        stream_path(organization.id),
        json={"company_name": "Tesla"},
    ).status_code == 200
    stub_workflow.stream_error = ModelProviderError("private provider detail")
    assert client.post(
        stream_path(organization.id),
        json={"company_name": "Tesla"},
    ).status_code == 200

    event_names = list(
        db_session.scalars(
            select(ApplicationEvent.event)
            .where(
                ApplicationEvent.organization_id == organization.id,
                ApplicationEvent.event.like("competitive_intelligence.analysis.%"),
            )
        )
    )
    assert Counter(event_names) == Counter(
        {
            "competitive_intelligence.analysis.started": 2,
            "competitive_intelligence.analysis.completed": 1,
            "competitive_intelligence.analysis.failed": 1,
        }
    )


def test_workflow_runs_successfully_with_external_fakes() -> None:
    organization_id = uuid4()
    context_store = FakeContextStore()
    report_generator = FakeReportGenerator("# Tesla report")
    workflow = CompetitiveIntelligenceWorkflow(
        question_generator=FakeQuestionGenerator(
            QuestionPlan(
                sector="Automotive",
                is_valid_company=True,
                questions=["Who are the competitors?", "What is the market position?"],
            )
        ),
        search_client=FakeSearchClient(
            {
                "Who are the competitors?": SearchResult(
                    answer="Competitor evidence",
                    sources=(),
                ),
                "What is the market position?": SearchResult(
                    answer="Market evidence",
                    sources=(),
                ),
            }
        ),
        context_store=context_store,
        report_generator=report_generator,
    )

    result = workflow.analyze(
        organization_id=organization_id,
        company_name="Tesla",
    )

    assert result == CompetitiveAnalysisResult(
        company_name="Tesla",
        sector="Automotive",
        report="# Tesla report",
    )
    assert context_store.calls[0]["organization_id"] == organization_id
    assert context_store.calls[0]["documents"] == [
        {
            "question": "Who are the competitors?",
            "answer": "Competitor evidence",
        },
        {
            "question": "What is the market position?",
            "answer": "Market evidence",
        },
    ]
    assert report_generator.calls == [
        {
            "company_name": "Tesla",
            "sector": "Automotive",
            "context": "trusted retrieved context",
        }
    ]


def test_workflow_stream_emits_complete_ordered_protocol() -> None:
    workflow = CompetitiveIntelligenceWorkflow(
        question_generator=FakeQuestionGenerator(
            QuestionPlan(
                sector="Automotive",
                is_valid_company=True,
                questions=["Competitors?", "Market position?"],
            )
        ),
        search_client=FakeSearchClient(
            {
                "Competitors?": SearchResult(
                    answer="Competitor evidence",
                    sources=(
                        SearchSource(
                            title="Competitor source",
                            url="https://example.com/competitors",
                        ),
                    ),
                ),
                "Market position?": SearchResult(
                    answer="Market evidence",
                    sources=(),
                ),
            }
        ),
        context_store=FakeContextStore(),
        report_generator=FakeReportGenerator("# Tesla report"),
    )

    events, error = consume_workflow_stream(workflow)

    assert error is None
    assert [event.type for event in events] == [
        "analysis_started",
        "questions_generated",
        "search_started",
        "search_completed",
        "search_started",
        "search_completed",
        "documents_indexed",
        "rag_retrieved",
        "report_generation_started",
        "analysis_completed",
    ]
    search_events = [
        event for event in events if event.type in {"search_started", "search_completed"}
    ]
    assert [(event.data["current"], event.data["total"]) for event in search_events] == [
        (1, 2),
        (1, 2),
        (2, 2),
        (2, 2),
    ]
    completed_searches = [
        event for event in events if event.type == "search_completed"
    ]
    assert completed_searches[0].data["answer_indexed"] is True
    assert completed_searches[0].data["sources"] == [
        {"title": "Competitor source", "url": "https://example.com/competitors"}
    ]
    assert events[-1].data == {
        "company_name": "Tesla",
        "sector": "Automotive",
        "report": "# Tesla report",
    }


@pytest.mark.parametrize(
    ("plan", "expected_error"),
    [
        (
            QuestionPlan(sector="", is_valid_company=False, questions=[]),
            InvalidCompanyError,
        ),
        (ModelProviderError("question model failed"), ModelProviderError),
    ],
)
def test_workflow_stream_question_failures_only_emit_started(
    plan: QuestionPlan | Exception,
    expected_error: type[Exception],
) -> None:
    workflow = CompetitiveIntelligenceWorkflow(
        question_generator=FakeQuestionGenerator(plan),
        search_client=FakeSearchClient({}),
        context_store=FakeContextStore(),
        report_generator=FakeReportGenerator(),
    )

    events, error = consume_workflow_stream(workflow)

    assert [event.type for event in events] == ["analysis_started"]
    assert isinstance(error, expected_error)


def test_workflow_stream_continues_after_partial_tavily_failure() -> None:
    workflow = CompetitiveIntelligenceWorkflow(
        question_generator=FakeQuestionGenerator(
            QuestionPlan(
                sector="Automotive",
                is_valid_company=True,
                questions=["Failed question", "Successful question"],
            )
        ),
        search_client=FakeSearchClient(
            {
                "Failed question": SearchProviderError("provider failed"),
                "Successful question": SearchResult(
                    answer="Useful answer",
                    sources=(),
                ),
            }
        ),
        context_store=FakeContextStore(),
        report_generator=FakeReportGenerator(),
    )

    events, error = consume_workflow_stream(workflow)

    assert error is None
    assert [event.type for event in events].count("search_failed") == 1
    assert events[-1].type == "analysis_completed"


@pytest.mark.parametrize(
    ("answers", "context_result", "report", "expected_error"),
    [
        (
            {"Question": SearchProviderError("provider failed")},
            None,
            "# Report",
            SearchProviderError,
        ),
        (
            {"Question": SearchResult(answer=None, sources=())},
            None,
            "# Report",
            NoSearchResultsError,
        ),
        (
            {"Question": SearchResult(answer="Answer", sources=())},
            VectorStoreError("Chroma failed"),
            "# Report",
            VectorStoreError,
        ),
        (
            {"Question": SearchResult(answer="Answer", sources=())},
            None,
            ModelProviderError("report model failed"),
            ModelProviderError,
        ),
    ],
)
def test_workflow_stream_propagates_stage_failures_for_router_terminal_mapping(
    answers: dict[str, SearchResult | Exception],
    context_result: ContextRetrievalResult | Exception | None,
    report: str | Exception,
    expected_error: type[Exception],
) -> None:
    workflow = CompetitiveIntelligenceWorkflow(
        question_generator=FakeQuestionGenerator(
            QuestionPlan(
                sector="Automotive",
                is_valid_company=True,
                questions=["Question"],
            )
        ),
        search_client=FakeSearchClient(answers),
        context_store=FakeContextStore(context_result),
        report_generator=FakeReportGenerator(report),
    )

    events, error = consume_workflow_stream(workflow)

    assert isinstance(error, expected_error)
    assert all(
        event.type not in {"analysis_completed", "analysis_failed"} for event in events
    )


def test_workflow_rejects_invalid_company_before_search() -> None:
    workflow = CompetitiveIntelligenceWorkflow(
        question_generator=FakeQuestionGenerator(
            QuestionPlan(sector="", is_valid_company=False, questions=[])
        ),
        search_client=FakeSearchClient({}),
        context_store=FakeContextStore(),
        report_generator=FakeReportGenerator(),
    )

    with pytest.raises(InvalidCompanyError):
        workflow.analyze(organization_id=uuid4(), company_name="Unknown Example")


def test_workflow_reports_tavily_failure_when_all_searches_fail() -> None:
    workflow = CompetitiveIntelligenceWorkflow(
        question_generator=FakeQuestionGenerator(
            QuestionPlan(
                sector="Automotive",
                is_valid_company=True,
                questions=["Question"],
            )
        ),
        search_client=FakeSearchClient(
            {"Question": SearchProviderError("provider failed")}
        ),
        context_store=FakeContextStore(),
        report_generator=FakeReportGenerator(),
    )

    with pytest.raises(SearchProviderError):
        workflow.analyze(organization_id=uuid4(), company_name="Tesla")


def test_workflow_propagates_openai_failure() -> None:
    workflow = CompetitiveIntelligenceWorkflow(
        question_generator=FakeQuestionGenerator(ModelProviderError("model failed")),
        search_client=FakeSearchClient({}),
        context_store=FakeContextStore(),
        report_generator=FakeReportGenerator(),
    )

    with pytest.raises(ModelProviderError):
        workflow.analyze(organization_id=uuid4(), company_name="Tesla")


def test_workflow_rejects_absence_of_valid_search_documents() -> None:
    context_store = FakeContextStore()
    workflow = CompetitiveIntelligenceWorkflow(
        question_generator=FakeQuestionGenerator(
            QuestionPlan(
                sector="Automotive",
                is_valid_company=True,
                questions=["Question"],
            )
        ),
        search_client=FakeSearchClient(
            {"Question": SearchResult(answer=None, sources=())}
        ),
        context_store=context_store,
        report_generator=FakeReportGenerator(),
    )

    with pytest.raises(NoSearchResultsError):
        workflow.analyze(organization_id=uuid4(), company_name="Tesla")
    assert context_store.calls == []


def test_chroma_store_does_not_treat_zero_documents_as_success() -> None:
    store = object.__new__(ChromaContextStore)

    with pytest.raises(NoSearchResultsError):
        store.index_and_retrieve(
            organization_id=uuid4(),
            execution_id=uuid4(),
            company_name="Tesla",
            documents=[],
        )


def test_chroma_store_scopes_collection_records_and_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeEmbeddings:
        def embed_documents(self, documents: list[str]) -> list[list[float]]:
            return [[float(index), 1.0] for index, _ in enumerate(documents)]

        def embed_query(self, query: str) -> list[float]:
            assert query == "Competitive analysis data for Tesla"
            return [0.0, 1.0]

    class FakeCollection:
        def __init__(self) -> None:
            self.added: dict[str, Any] = {}
            self.query_arguments: dict[str, Any] = {}

        def add(self, **kwargs: Any) -> None:
            self.added = kwargs

        def count(self) -> int:
            return len(self.added["ids"])

        def query(self, **kwargs: Any) -> dict[str, list[list[str]]]:
            self.query_arguments = kwargs
            return {"documents": [self.added["documents"]]}

    class FakeChromaClient:
        def __init__(self) -> None:
            self.collection = FakeCollection()
            self.created_name: str | None = None
            self.created_metadata: dict[str, str] | None = None
            self.deleted_name: str | None = None

        def create_collection(
            self, *, name: str, metadata: dict[str, str]
        ) -> FakeCollection:
            self.created_name = name
            self.created_metadata = metadata
            return self.collection

        def delete_collection(self, name: str) -> None:
            self.deleted_name = name

    client = FakeChromaClient()
    monkeypatch.setattr(
        "app.modules.competitive_intelligence.vector_store.chromadb.EphemeralClient",
        lambda: client,
    )
    store = object.__new__(ChromaContextStore)
    store._embeddings = FakeEmbeddings()
    organization_id = uuid4()
    execution_id = uuid4()

    context = store.index_and_retrieve(
        organization_id=organization_id,
        execution_id=execution_id,
        company_name="Tesla",
        documents=[
            {"question": "Question 1", "answer": "Answer 1"},
            {"question": "Question 2", "answer": "Answer 2"},
        ],
    )

    assert context == ContextRetrievalResult(
        context="Answer 1\n\nAnswer 2",
        documents_indexed=2,
        embedding_units_indexed=2,
        embedding_units_retrieved=2,
    )
    assert client.created_name == f"ci_{execution_id.hex}"
    assert client.created_metadata == {"hnsw:space": "cosine"}
    assert client.collection.added["ids"] == [
        f"{organization_id.hex}:{execution_id.hex}:0",
        f"{organization_id.hex}:{execution_id.hex}:1",
    ]
    assert client.collection.added["metadatas"] == [
        {
            "organization_id": str(organization_id),
            "execution_id": str(execution_id),
            "question": "Question 1",
        },
        {
            "organization_id": str(organization_id),
            "execution_id": str(execution_id),
            "question": "Question 2",
        },
    ]
    assert client.collection.query_arguments["n_results"] == 2
    assert client.deleted_name == client.created_name
