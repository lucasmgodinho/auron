from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.access_control.model import OrganizationAccessGroup
from app.core.auth import service as auth_service
from app.core.auth.dependencies import AUTH_SESSION_COOKIE_NAME
from app.core.module_registry.definitions import (
    ModuleDefinition,
    PermissionDefinition,
)
from app.core.module_registry.dependencies import get_module_registry
from app.core.module_registry.registry import ModuleRegistry
from app.core.organization_invitations.model import OrganizationInvitation
from app.core.organization_memberships import repository as membership_repository
from app.core.organization_memberships.model import OrganizationMembership
from app.core.organization_modules import service as module_service
from app.core.organization_modules.model import OrganizationModule
from app.core.organizations import repository as organization_repository
from app.core.organizations.model import Organization
from app.core.platform_admin import service as platform_admin_service
from app.core.users import service as user_service
from app.core.users.model import User
from app.main import app


@pytest.fixture
def module_registry() -> ModuleRegistry:
    return ModuleRegistry(
        [
            ModuleDefinition(
                key="operations_test",
                name_key="modules.operations_test.name",
                permissions=(
                    PermissionDefinition(
                        key="operations_test.record.read",
                        resource="record",
                        action="read",
                    ),
                    PermissionDefinition(
                        key="operations_test.record.create",
                        resource="record",
                        action="create",
                    ),
                    PermissionDefinition(
                        key="operations_test.record.update",
                        resource="record",
                        action="update",
                    ),
                    PermissionDefinition(
                        key="operations_test.record.delete",
                        resource="record",
                        action="delete",
                    ),
                ),
            )
        ]
    )


@pytest.fixture
def module_client(
    client: TestClient, module_registry: ModuleRegistry
) -> TestClient:
    app.dependency_overrides[get_module_registry] = lambda: module_registry
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_module_registry, None)


def create_user(
    session: Session, *, email: str, name: str = "Module User"
) -> User:
    return user_service.create_user(session, email=email, name=name)


def authenticate(client: TestClient, session: Session, user: User) -> None:
    _, raw_token = auth_service.create_auth_session(session, user.id)
    client.cookies.set(AUTH_SESSION_COOKIE_NAME, raw_token)


def create_empty_organization(session: Session, name: str) -> Organization:
    organization = organization_repository.add_organization(session, name)
    session.commit()
    session.refresh(organization)
    return organization


def add_membership(
    session: Session,
    *,
    organization_id: UUID,
    user_id: UUID,
    role: str = "member",
) -> OrganizationMembership:
    return membership_repository.create_membership(
        session,
        user_id=user_id,
        organization_id=organization_id,
        role=role,
    )


def test_production_platform_admin_module_list_contains_implemented_module(
    client: TestClient, db_session: Session
) -> None:
    operator = create_user(db_session, email="module-registry-admin@example.com")
    platform_admin_service.grant_platform_admin(db_session, operator.email)
    authenticate(client, db_session, operator)

    response = client.get("/platform-admin/modules")

    assert response.status_code == 200
    assert response.json() == [
        {
            "key": "competitive_intelligence",
            "name_key": "modules.competitive_intelligence.name",
        }
    ]


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/platform-admin/modules", None),
        ("get", f"/platform-admin/organizations/{uuid4()}/modules", None),
        (
            "put",
            f"/platform-admin/organizations/{uuid4()}/modules/operations_test",
            {"enabled": True},
        ),
        ("get", f"/organizations/{uuid4()}/modules", None),
    ],
)
def test_module_endpoints_require_authentication(
    module_client: TestClient,
    method: str,
    path: str,
    payload: dict[str, bool] | None,
) -> None:
    response = module_client.request(method, path, json=payload)

    assert response.status_code == 401


def test_platform_admin_manages_entitlement_without_receiving_tenant_access(
    module_client: TestClient, db_session: Session
) -> None:
    operator = create_user(db_session, email="module-admin@example.com")
    platform_admin_service.grant_platform_admin(db_session, operator.email)
    organization = create_empty_organization(db_session, "Entitled Organization")
    authenticate(module_client, db_session, operator)

    module_list = module_client.get("/platform-admin/modules")
    initial = module_client.get(
        f"/platform-admin/organizations/{organization.id}/modules"
    )
    enabled = module_client.put(
        f"/platform-admin/organizations/{organization.id}/modules/operations_test",
        json={"enabled": True},
    )

    assert module_list.json() == [
        {"key": "operations_test", "name_key": "modules.operations_test.name"}
    ]
    assert initial.json() == [
        {
            "key": "operations_test",
            "name_key": "modules.operations_test.name",
            "enabled": False,
        }
    ]
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    assert db_session.scalar(
        select(func.count()).select_from(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization.id
        )
    ) == 0
    assert db_session.scalar(
        select(func.count()).select_from(OrganizationAccessGroup).where(
            OrganizationAccessGroup.organization_id == organization.id
        )
    ) == 0
    assert db_session.scalar(
        select(func.count()).select_from(OrganizationInvitation).where(
            OrganizationInvitation.organization_id == organization.id
        )
    ) == 0
    assert module_client.get(
        f"/organizations/{organization.id}/modules"
    ).status_code == 403

    disabled = module_client.put(
        f"/platform-admin/organizations/{organization.id}/modules/operations_test",
        json={"enabled": False},
    )
    re_enabled = module_client.put(
        f"/platform-admin/organizations/{organization.id}/modules/operations_test",
        json={"enabled": True},
    )
    assert disabled.json()["enabled"] is False
    assert re_enabled.json()["enabled"] is True
    assert db_session.scalar(
        select(func.count()).select_from(OrganizationModule).where(
            OrganizationModule.organization_id == organization.id,
            OrganizationModule.module_key == "operations_test",
        )
    ) == 1


def test_normal_user_cannot_configure_entitlement_and_unknown_module_is_rejected(
    module_client: TestClient, db_session: Session
) -> None:
    user = create_user(db_session, email="normal-module-user@example.com")
    organization = create_empty_organization(db_session, "Normal Organization")
    add_membership(
        db_session,
        organization_id=organization.id,
        user_id=user.id,
        role="owner",
    )
    authenticate(module_client, db_session, user)

    forbidden = module_client.put(
        f"/platform-admin/organizations/{organization.id}/modules/operations_test",
        json={"enabled": True},
    )
    assert forbidden.status_code == 403

    platform_admin_service.grant_platform_admin(db_session, user.email)
    unknown = module_client.put(
        f"/platform-admin/organizations/{organization.id}/modules/unknown_module",
        json={"enabled": True},
    )
    missing_organization = module_client.get(
        f"/platform-admin/organizations/{uuid4()}/modules"
    )
    assert unknown.status_code == 404
    assert missing_organization.status_code == 404
    invalid_boolean = module_client.put(
        f"/platform-admin/organizations/{organization.id}/modules/operations_test",
        json={"enabled": "true"},
    )
    assert invalid_boolean.status_code == 422
    assert db_session.scalar(select(func.count()).select_from(OrganizationModule)) == 0


def test_tenant_module_listing_is_membership_scoped_and_enabled_only(
    module_client: TestClient,
    db_session: Session,
    module_registry: ModuleRegistry,
) -> None:
    member = create_user(db_session, email="module-member@example.com")
    outsider = create_user(db_session, email="module-outsider@example.com")
    organization = create_empty_organization(db_session, "Member Organization")
    add_membership(
        db_session,
        organization_id=organization.id,
        user_id=member.id,
    )
    module_service.set_organization_module(
        db_session,
        organization_id=organization.id,
        module_key="operations_test",
        enabled=True,
        registry=module_registry,
    )
    authenticate(module_client, db_session, member)

    enabled = module_client.get(f"/organizations/{organization.id}/modules")
    assert enabled.status_code == 200
    assert enabled.json() == [
        {"key": "operations_test", "name_key": "modules.operations_test.name"}
    ]

    module_service.set_organization_module(
        db_session,
        organization_id=organization.id,
        module_key="operations_test",
        enabled=False,
        registry=module_registry,
    )
    assert module_client.get(f"/organizations/{organization.id}/modules").json() == []

    authenticate(module_client, db_session, outsider)
    assert module_client.get(
        f"/organizations/{organization.id}/modules"
    ).status_code == 403


def test_organization_module_unique_constraint_is_enforced(
    db_session: Session,
) -> None:
    organization = create_empty_organization(db_session, "Unique Module")
    db_session.add_all(
        [
            OrganizationModule(
                organization_id=organization.id,
                module_key="operations_test",
                enabled=True,
            ),
            OrganizationModule(
                organization_id=organization.id,
                module_key="operations_test",
                enabled=False,
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_concurrent_entitlement_updates_leave_one_valid_row(
    test_engine: Engine, module_registry: ModuleRegistry
) -> None:
    with Session(test_engine) as setup:
        organization = create_empty_organization(
            setup, f"Concurrent Modules {uuid4().hex}"
        )
        organization_id = organization.id
    start = Barrier(2)

    def update_once(enabled: bool) -> bool:
        with Session(test_engine) as session:
            start.wait(timeout=10)
            _, stored_enabled = module_service.set_organization_module(
                session,
                organization_id=organization_id,
                module_key="operations_test",
                enabled=enabled,
                registry=module_registry,
            )
            return stored_enabled

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(update_once, [True, False]))
        with Session(test_engine) as check:
            rows = list(
                check.scalars(
                    select(OrganizationModule).where(
                        OrganizationModule.organization_id == organization_id
                    )
                )
            )
        assert sorted(results) == [False, True]
        assert len(rows) == 1
        assert isinstance(rows[0].enabled, bool)
    finally:
        with Session(test_engine) as cleanup:
            cleanup.execute(
                delete(OrganizationModule).where(
                    OrganizationModule.organization_id == organization_id
                )
            )
            cleanup.execute(
                delete(Organization).where(Organization.id == organization_id)
            )
            cleanup.commit()
