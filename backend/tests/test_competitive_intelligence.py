from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.access_control import service as access_service
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
from app.modules.competitive_intelligence.vector_store import ChromaContextStore
from app.modules.competitive_intelligence.workflow import (
    CompetitiveAnalysisResult,
    CompetitiveIntelligenceWorkflow,
)


class StubWorkflow:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, str]] = []
        self.error: Exception | None = None

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


class FakeQuestionGenerator:
    def __init__(self, plan: QuestionPlan | Exception) -> None:
        self.plan = plan

    def generate(self, company_name: str) -> QuestionPlan:
        del company_name
        if isinstance(self.plan, Exception):
            raise self.plan
        return self.plan


class FakeSearchClient:
    def __init__(self, answers: dict[str, str | None | Exception]) -> None:
        self.answers = answers

    def search(self, question: str) -> str | None:
        answer = self.answers[question]
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakeContextStore:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def index_and_retrieve(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return "trusted retrieved context"


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


def test_module_is_registered_with_stable_permission() -> None:
    assert production_module_registry.get(MODULE_KEY) is MODULE_DEFINITION
    assert [permission.key for permission in MODULE_DEFINITION.permissions] == [
        RUN_ANALYSIS_PERMISSION
    ]
    assert MODULE_DEFINITION.analytics_provider is None


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
                "Who are the competitors?": "Competitor evidence",
                "What is the market position?": "Market evidence",
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
        search_client=FakeSearchClient({"Question": None}),
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

    assert context == "Answer 1\n\nAnswer 2"
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
