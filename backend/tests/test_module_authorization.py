from collections.abc import Iterator
from typing import Annotated
from uuid import UUID, uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.access_control import service as access_service
from app.core.access_control.dependencies import (
    ModuleAccessContext,
    require_module_permission,
)
from app.core.auth import service as auth_service
from app.core.auth.dependencies import AUTH_SESSION_COOKIE_NAME
from app.core.module_registry.definitions import (
    ModuleDefinition,
    PermissionDefinition,
)
from app.core.module_registry.dependencies import get_module_registry
from app.core.module_registry.registry import InvalidModuleDefinitionError, ModuleRegistry
from app.core.organization_memberships import repository as membership_repository
from app.core.organization_memberships.model import OrganizationMembership
from app.core.organization_modules import service as module_service
from app.core.organizations import service as organization_service
from app.core.platform_admin import service as platform_admin_service
from app.core.users import service as user_service
from app.core.users.model import User
from app.database import get_session


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
                        key="operations_test.record.update",
                        resource="record",
                        action="update",
                    ),
                ),
            )
        ]
    )


@pytest.fixture
def protected_client(
    db_session: Session, module_registry: ModuleRegistry
) -> Iterator[TestClient]:
    test_app = FastAPI()

    @test_app.get("/organizations/{organization_id}/test-records")
    def protected_endpoint(
        access: Annotated[
            ModuleAccessContext,
            Depends(
                require_module_permission(
                    module_key="operations_test",
                    permission_key="operations_test.record.read",
                )
            ),
        ],
    ) -> dict[str, str]:
        return {"organization_id": str(access.organization_context.organization.id)}

    @test_app.get("/organizations/{organization_id}/unknown-module")
    def unknown_module_endpoint(
        _: Annotated[
            ModuleAccessContext,
            Depends(
                require_module_permission(
                    module_key="unknown_test",
                    permission_key="unknown_test.record.read",
                )
            ),
        ],
    ) -> dict[str, bool]:
        return {"allowed": True}

    def override_session() -> Iterator[Session]:
        yield db_session

    test_app.dependency_overrides[get_session] = override_session
    test_app.dependency_overrides[get_module_registry] = lambda: module_registry
    with TestClient(test_app) as client:
        yield client


def create_user(session: Session, email: str) -> User:
    return user_service.create_user(session, email=email, name="Authorization User")


def authenticate(client: TestClient, session: Session, user: User) -> None:
    _, raw_token = auth_service.create_auth_session(session, user.id)
    client.cookies.set(AUTH_SESSION_COOKIE_NAME, raw_token)


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


def test_require_module_permission_enforces_complete_pipeline(
    protected_client: TestClient,
    db_session: Session,
    module_registry: ModuleRegistry,
) -> None:
    owner = create_user(db_session, "permission-owner@example.com")
    member = create_user(db_session, "permission-member@example.com")
    outsider = create_user(db_session, "permission-outsider@example.com")
    platform_admin = create_user(db_session, "permission-platform@example.com")
    platform_admin_service.grant_platform_admin(db_session, platform_admin.email)
    organization = organization_service.create_organization(
        db_session, "Permission Organization", owner.id
    )
    member_membership = add_membership(
        db_session,
        organization_id=organization.id,
        user_id=member.id,
        role="member",
    )
    path = f"/organizations/{organization.id}/test-records"

    assert protected_client.get(path).status_code == 401
    authenticate(protected_client, db_session, member)
    assert protected_client.get(
        f"/organizations/{uuid4()}/test-records"
    ).status_code == 404
    assert protected_client.get(path).status_code == 403

    authenticate(protected_client, db_session, outsider)
    assert protected_client.get(path).status_code == 403
    authenticate(protected_client, db_session, platform_admin)
    assert protected_client.get(path).status_code == 403

    authenticate(protected_client, db_session, owner)
    assert protected_client.get(path).status_code == 403
    module_service.set_organization_module(
        db_session,
        organization_id=organization.id,
        module_key="operations_test",
        enabled=True,
        registry=module_registry,
    )
    owner_allowed = protected_client.get(path)
    assert owner_allowed.status_code == 200
    assert owner_allowed.json() == {"organization_id": str(organization.id)}

    authenticate(protected_client, db_session, member)
    assert protected_client.get(path).status_code == 403
    group = access_service.create_access_group(
        db_session,
        organization_id=organization.id,
        name="Wrong Permission",
        description=None,
    )
    access_service.replace_access_group_permissions(
        db_session,
        organization_id=organization.id,
        access_group_id=group.id,
        permission_keys=["operations_test.record.update"],
        registry=module_registry,
    )
    access_service.replace_access_group_memberships(
        db_session,
        organization_id=organization.id,
        access_group_id=group.id,
        membership_ids=[member_membership.id],
    )
    assert protected_client.get(path).status_code == 403

    access_service.replace_access_group_permissions(
        db_session,
        organization_id=organization.id,
        access_group_id=group.id,
        permission_keys=["operations_test.record.read"],
        registry=module_registry,
    )
    assert protected_client.get(path).status_code == 200

    other_owner = create_user(db_session, "permission-other-owner@example.com")
    other_organization = organization_service.create_organization(
        db_session, "Permission Other Organization", other_owner.id
    )
    assert protected_client.get(
        f"/organizations/{other_organization.id}/test-records"
    ).status_code == 403
    assert protected_client.get(
        f"/organizations/{organization.id}/unknown-module"
    ).status_code == 404

    module_service.set_organization_module(
        db_session,
        organization_id=organization.id,
        module_key="operations_test",
        enabled=False,
        registry=module_registry,
    )
    authenticate(protected_client, db_session, owner)
    assert protected_client.get(path).status_code == 403


@pytest.mark.parametrize(
    ("module_key", "permission_key"),
    [
        ("operations_test", "another.record.read"),
        ("Operations", "Operations.record.read"),
        ("operations_test", "operations_test.Record.read"),
        ("operations_test", "operations_test.record"),
    ],
)
def test_require_module_permission_rejects_programmer_mistakes(
    module_key: str, permission_key: str
) -> None:
    with pytest.raises((ValueError, InvalidModuleDefinitionError)):
        require_module_permission(
            module_key=module_key,
            permission_key=permission_key,
        )
