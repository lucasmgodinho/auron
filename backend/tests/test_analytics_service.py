from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID, uuid4

import pytest
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.access_control import service as access_service
from app.core.analytics import service as analytics_service
from app.core.analytics.schemas import (
    AnalyticsDataPoint,
    AnalyticsMetricQuery,
    AnalyticsMetricResult,
)
from app.core.analytics.validation import (
    AnalyticsQueryValidationError,
    AnalyticsResultValidationError,
)
from app.core.auth import service as auth_service
from app.core.auth.dependencies import AUTH_SESSION_COOKIE_NAME
from app.core.module_registry.definitions import (
    ModuleDefinition,
    PermissionDefinition,
)
from app.core.module_registry.registry import ModuleRegistry, production_module_registry
from app.core.organization_context.context import OrganizationContext
from app.core.organization_context.dependencies import get_organization_context
from app.core.organization_memberships import repository as membership_repository
from app.core.organization_memberships.model import OrganizationMembership
from app.core.organization_modules import service as module_service
from app.core.organizations import service as organization_service
from app.core.platform_admin import service as platform_admin_service
from app.core.users import service as user_service
from app.core.users.model import User
from app.database import get_session
from app.main import app
from tests.analytics_fakes import (
    FinanceAnalyticsProvider,
    OperationsAnalyticsProvider,
)


def permission(module_key: str, resource: str) -> PermissionDefinition:
    return PermissionDefinition(
        key=f"{module_key}.{resource}.read",
        resource=resource,
        action="read",
    )


@pytest.fixture
def operations_provider() -> OperationsAnalyticsProvider:
    return OperationsAnalyticsProvider()


@pytest.fixture
def finance_provider() -> FinanceAnalyticsProvider:
    return FinanceAnalyticsProvider()


@pytest.fixture
def analytics_registry(
    operations_provider: OperationsAnalyticsProvider,
    finance_provider: FinanceAnalyticsProvider,
) -> ModuleRegistry:
    return ModuleRegistry(
        [
            ModuleDefinition(
                key="operations_test",
                name_key="modules.operations_test.name",
                permissions=(
                    permission("operations_test", "record"),
                    permission("operations_test", "audit"),
                ),
                analytics_provider=operations_provider,
            ),
            ModuleDefinition(
                key="finance_test",
                name_key="modules.finance_test.name",
                permissions=(permission("finance_test", "entry"),),
                analytics_provider=finance_provider,
            ),
            ModuleDefinition(
                key="plain_test",
                name_key="modules.plain_test.name",
                permissions=(permission("plain_test", "record"),),
            ),
        ]
    )


def create_user(session: Session, email: str) -> User:
    return user_service.create_user(session, email=email, name="Analytics User")


def add_membership(
    session: Session,
    *,
    organization_id: UUID,
    user_id: UUID,
    role: str,
) -> OrganizationMembership:
    return membership_repository.create_membership(
        session,
        organization_id=organization_id,
        user_id=user_id,
        role=role,
    )


def context_for(
    session: Session,
    *,
    user: User,
    organization_id: UUID,
) -> OrganizationContext:
    return get_organization_context(organization_id, session, user)


def operations_query(*, group_by: str | None = None) -> AnalyticsMetricQuery:
    return AnalyticsMetricQuery(
        metric_key="operations_test.record_count",
        group_by=group_by,
        filters={"date_from": "2026-01-01"},
    )


def enable_module(
    session: Session,
    *,
    organization_id: UUID,
    module_key: str,
    registry: ModuleRegistry,
    enabled: bool = True,
) -> None:
    module_service.set_organization_module(
        session,
        organization_id=organization_id,
        module_key=module_key,
        enabled=enabled,
        registry=registry,
    )


def create_group(
    session: Session,
    *,
    organization_id: UUID,
    name: str,
    permission_keys: list[str],
    membership_ids: list[UUID],
    registry: ModuleRegistry,
) -> UUID:
    group = access_service.create_access_group(
        session,
        organization_id=organization_id,
        name=name,
        description=None,
    )
    access_service.replace_access_group_permissions(
        session,
        organization_id=organization_id,
        access_group_id=group.id,
        permission_keys=permission_keys,
        registry=registry,
    )
    access_service.replace_access_group_memberships(
        session,
        organization_id=organization_id,
        access_group_id=group.id,
        membership_ids=membership_ids,
    )
    return group.id


def test_query_authorization_provider_context_and_immediate_freshness(
    db_session: Session,
    analytics_registry: ModuleRegistry,
    operations_provider: OperationsAnalyticsProvider,
) -> None:
    owner = create_user(db_session, "analytics-owner@example.com")
    member = create_user(db_session, "analytics-member@example.com")
    admin = create_user(db_session, "analytics-admin@example.com")
    organization = organization_service.create_organization(
        db_session, "Analytics Organization", owner.id
    )
    member_membership = add_membership(
        db_session,
        organization_id=organization.id,
        user_id=member.id,
        role="member",
    )
    add_membership(
        db_session,
        organization_id=organization.id,
        user_id=admin.id,
        role="admin",
    )
    enable_module(
        db_session,
        organization_id=organization.id,
        module_key="operations_test",
        registry=analytics_registry,
    )
    owner_context = context_for(
        db_session, user=owner, organization_id=organization.id
    )
    member_context = context_for(
        db_session, user=member, organization_id=organization.id
    )
    admin_context = context_for(
        db_session, user=admin, organization_id=organization.id
    )

    for denied_context in (member_context, admin_context):
        with pytest.raises(access_service.ModuleAccessDeniedError):
            analytics_service.query_metric(
                db_session,
                context=denied_context,
                registry=analytics_registry,
                query=operations_query(),
            )
    assert operations_provider.calls == 0

    owner_result = analytics_service.query_metric(
        db_session,
        context=owner_context,
        registry=analytics_registry,
        query=operations_query(),
    )
    assert owner_result.points[0].value == Decimal("12")
    assert operations_provider.last_context is not None
    assert operations_provider.last_context.organization_id == organization.id

    create_group(
        db_session,
        organization_id=organization.id,
        name="Analytics auxiliary",
        permission_keys=["operations_test.audit.read"],
        membership_ids=[member_membership.id],
        registry=analytics_registry,
    )
    permission_group_id = create_group(
        db_session,
        organization_id=organization.id,
        name="Analytics source permission",
        permission_keys=["operations_test.record.read"],
        membership_ids=[member_membership.id],
        registry=analytics_registry,
    )
    member_result = analytics_service.query_metric(
        db_session,
        context=member_context,
        registry=analytics_registry,
        query=operations_query(group_by="month"),
    )
    assert member_result.group_by == "month"
    assert operations_provider.last_query is not None
    assert operations_provider.last_query.group_by == "month"
    assert operations_provider.last_query.filters["date_from"] == date(2026, 1, 1)

    access_service.replace_access_group_permissions(
        db_session,
        organization_id=organization.id,
        access_group_id=permission_group_id,
        permission_keys=[],
        registry=analytics_registry,
    )
    calls_before_denial = operations_provider.calls
    with pytest.raises(access_service.ModuleAccessDeniedError):
        analytics_service.query_metric(
            db_session,
            context=member_context,
            registry=analytics_registry,
            query=operations_query(),
        )
    assert operations_provider.calls == calls_before_denial

    access_service.replace_access_group_permissions(
        db_session,
        organization_id=organization.id,
        access_group_id=permission_group_id,
        permission_keys=["operations_test.record.read"],
        registry=analytics_registry,
    )
    enable_module(
        db_session,
        organization_id=organization.id,
        module_key="operations_test",
        registry=analytics_registry,
        enabled=False,
    )
    for denied_context in (member_context, owner_context):
        with pytest.raises(access_service.ModuleAccessDeniedError):
            analytics_service.query_metric(
                db_session,
                context=denied_context,
                registry=analytics_registry,
                query=operations_query(),
            )


def test_catalog_filters_entitlement_permission_and_provider_presence(
    db_session: Session,
    analytics_registry: ModuleRegistry,
) -> None:
    owner = create_user(db_session, "catalog-owner@example.com")
    member = create_user(db_session, "catalog-member@example.com")
    organization = organization_service.create_organization(
        db_session, "Catalog Organization", owner.id
    )
    membership = add_membership(
        db_session,
        organization_id=organization.id,
        user_id=member.id,
        role="member",
    )
    for module_key in ("operations_test", "finance_test", "plain_test"):
        enable_module(
            db_session,
            organization_id=organization.id,
            module_key=module_key,
            registry=analytics_registry,
        )
    create_group(
        db_session,
        organization_id=organization.id,
        name="Catalog operations",
        permission_keys=["operations_test.record.read"],
        membership_ids=[membership.id],
        registry=analytics_registry,
    )
    owner_context = context_for(
        db_session, user=owner, organization_id=organization.id
    )
    member_context = context_for(
        db_session, user=member, organization_id=organization.id
    )

    owner_metrics = analytics_service.list_available_metrics(
        db_session,
        context=owner_context,
        registry=analytics_registry,
    )
    member_metrics = analytics_service.list_available_metrics(
        db_session,
        context=member_context,
        registry=analytics_registry,
    )

    assert [item.key for item in owner_metrics] == [
        "finance_test.total_cost",
        "operations_test.record_count",
    ]
    assert [item.key for item in member_metrics] == [
        "operations_test.record_count"
    ]
    assert all(not hasattr(item, "provider") for item in owner_metrics)
    assert analytics_service.list_provider_metrics(analytics_registry, "plain_test") == ()

    enable_module(
        db_session,
        organization_id=organization.id,
        module_key="operations_test",
        registry=analytics_registry,
        enabled=False,
    )
    assert analytics_service.list_available_metrics(
        db_session,
        context=member_context,
        registry=analytics_registry,
    ) == ()


def test_query_resolves_correct_provider_validates_before_invocation_and_propagates_failures(
    db_session: Session,
    analytics_registry: ModuleRegistry,
    operations_provider: OperationsAnalyticsProvider,
    finance_provider: FinanceAnalyticsProvider,
) -> None:
    owner = create_user(db_session, "provider-owner@example.com")
    organization = organization_service.create_organization(
        db_session, "Provider Organization", owner.id
    )
    for module_key in ("operations_test", "finance_test"):
        enable_module(
            db_session,
            organization_id=organization.id,
            module_key=module_key,
            registry=analytics_registry,
        )
    context = context_for(db_session, user=owner, organization_id=organization.id)
    category_id = uuid4()

    result = analytics_service.query_metric(
        db_session,
        context=context,
        registry=analytics_registry,
        query=AnalyticsMetricQuery(
            metric_key="finance_test.total_cost",
            group_by="category",
            filters={
                "category_id": str(category_id),
                "minimum_cost": 10.5,
            },
        ),
    )
    assert result.unit == "BRL"
    assert finance_provider.calls == 1
    assert operations_provider.calls == 0
    assert finance_provider.last_context is not None
    assert finance_provider.last_context.organization_id == organization.id
    assert finance_provider.last_query is not None
    assert finance_provider.last_query.filters["category_id"] == category_id
    assert finance_provider.last_query.filters["minimum_cost"] == Decimal("10.5")

    with pytest.raises(AnalyticsQueryValidationError):
        analytics_service.query_metric(
            db_session,
            context=context,
            registry=analytics_registry,
            query=AnalyticsMetricQuery(
                metric_key="finance_test.total_cost",
                group_by="unsupported",
            ),
        )
    assert finance_provider.calls == 1

    for metric_key in (
        "operations_test.unknown",
        "plain_test.record_count",
        "unknown_test.record_count",
    ):
        with pytest.raises(analytics_service.AnalyticsMetricNotFoundError):
            analytics_service.query_metric(
                db_session,
                context=context,
                registry=analytics_registry,
                query=AnalyticsMetricQuery(metric_key=metric_key),
            )

    operations_provider.failure = RuntimeError("provider unavailable")
    with pytest.raises(RuntimeError, match="provider unavailable"):
        analytics_service.query_metric(
            db_session,
            context=context,
            registry=analytics_registry,
            query=operations_query(),
        )
    operations_provider.failure = None
    operations_provider.result_override = AnalyticsMetricResult(
        metric_key="operations_test.wrong",
        format=operations_provider.metrics()[0].format,
        points=(AnalyticsDataPoint(value=Decimal("1")),),
    )
    with pytest.raises(AnalyticsResultValidationError):
        analytics_service.query_metric(
            db_session,
            context=context,
            registry=analytics_registry,
            query=operations_query(),
        )


@pytest.fixture
def analytics_client(
    db_session: Session,
    analytics_registry: ModuleRegistry,
) -> Iterator[TestClient]:
    test_app = FastAPI()

    @test_app.get("/organizations/{organization_id}/test-analytics")
    def query_test_metric(
        context: Annotated[OrganizationContext, Depends(get_organization_context)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        try:
            result = analytics_service.query_metric(
                session,
                context=context,
                registry=analytics_registry,
                query=operations_query(),
            )
        except access_service.ModuleAccessDeniedError as error:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from error
        return result.model_dump(mode="json")

    def override_session() -> Iterator[Session]:
        yield db_session

    test_app.dependency_overrides[get_session] = override_session
    with TestClient(test_app) as client:
        yield client


def authenticate(client: TestClient, session: Session, user: User) -> None:
    _, raw_token = auth_service.create_auth_session(session, user.id)
    client.cookies.set(AUTH_SESSION_COOKIE_NAME, raw_token)


def test_test_only_route_proves_authentication_tenant_and_platform_admin_boundaries(
    analytics_client: TestClient,
    db_session: Session,
    analytics_registry: ModuleRegistry,
) -> None:
    owner = create_user(db_session, "route-owner@example.com")
    outsider = create_user(db_session, "route-outsider@example.com")
    platform_admin = create_user(db_session, "route-platform@example.com")
    platform_admin_service.grant_platform_admin(db_session, platform_admin.email)
    organization = organization_service.create_organization(
        db_session, "Route Analytics", owner.id
    )
    enable_module(
        db_session,
        organization_id=organization.id,
        module_key="operations_test",
        registry=analytics_registry,
    )
    path = f"/organizations/{organization.id}/test-analytics"

    assert analytics_client.get(path).status_code == 401
    authenticate(analytics_client, db_session, outsider)
    assert analytics_client.get(path).status_code == 403
    authenticate(analytics_client, db_session, platform_admin)
    assert analytics_client.get(path).status_code == 403
    authenticate(analytics_client, db_session, owner)
    assert analytics_client.get(path).status_code == 200

    other_owner = create_user(db_session, "route-other-owner@example.com")
    other_organization = organization_service.create_organization(
        db_session, "Route Other Analytics", other_owner.id
    )
    assert analytics_client.get(
        f"/organizations/{other_organization.id}/test-analytics"
    ).status_code == 403


def test_test_providers_and_routes_do_not_enter_production_application(
    client: TestClient,
) -> None:
    assert production_module_registry.list() == ()
    assert client.get("/health").status_code == 200
    paths = app.openapi()["paths"]
    assert all("analytics" not in path for path in paths)
