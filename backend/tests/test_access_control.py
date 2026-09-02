from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.access_control import service as access_service
from app.core.access_control.model import (
    OrganizationAccessGroup,
    OrganizationAccessGroupPermission,
    OrganizationMembershipAccessGroup,
)
from app.core.auth import service as auth_service
from app.core.auth.dependencies import AUTH_SESSION_COOKIE_NAME
from app.core.module_registry.definitions import (
    ModuleDefinition,
    PermissionDefinition,
)
from app.core.module_registry.dependencies import get_module_registry
from app.core.module_registry.registry import ModuleRegistry
from app.core.organization_memberships import repository as membership_repository
from app.core.organization_memberships.model import OrganizationMembership
from app.core.organization_modules import service as module_service
from app.core.organizations import service as organization_service
from app.core.organizations.model import Organization
from app.core.users import service as user_service
from app.core.users.model import User
from app.main import app


@pytest.fixture
def module_registry() -> ModuleRegistry:
    permissions = tuple(
        PermissionDefinition(
            key=f"operations_test.record.{action}",
            resource="record",
            action=action,
        )
        for action in ("read", "create", "update", "delete")
    )
    return ModuleRegistry(
        [
            ModuleDefinition(
                key="operations_test",
                name_key="modules.operations_test.name",
                permissions=permissions,
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


def create_user(session: Session, email: str) -> User:
    return user_service.create_user(session, email=email, name="Access User")


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
        user_id=user_id,
        organization_id=organization_id,
        role=role,
    )


def test_access_group_crud_is_owner_only_and_tenant_scoped(
    module_client: TestClient, db_session: Session
) -> None:
    owner = create_user(db_session, "group-owner@example.com")
    admin = create_user(db_session, "group-admin@example.com")
    member = create_user(db_session, "group-member@example.com")
    other_owner = create_user(db_session, "other-group-owner@example.com")
    organization = organization_service.create_organization(
        db_session, "Group Organization", owner.id
    )
    other_organization = organization_service.create_organization(
        db_session, "Other Group Organization", other_owner.id
    )
    add_membership(
        db_session,
        organization_id=organization.id,
        user_id=admin.id,
        role="admin",
    )
    member_membership = add_membership(
        db_session,
        organization_id=organization.id,
        user_id=member.id,
        role="member",
    )
    authenticate(module_client, db_session, owner)

    created = module_client.post(
        f"/organizations/{organization.id}/access-groups",
        json={"name": "  Finance  ", "description": "Financial operations"},
    )
    assert created.status_code == 201
    group_id = created.json()["id"]
    assert created.json()["name"] == "Finance"
    duplicate = module_client.post(
        f"/organizations/{organization.id}/access-groups",
        json={"name": "Finance"},
    )
    assert duplicate.status_code == 409

    listed = module_client.get(
        f"/organizations/{organization.id}/access-groups"
    )
    read = module_client.get(
        f"/organizations/{organization.id}/access-groups/{group_id}"
    )
    updated = module_client.patch(
        f"/organizations/{organization.id}/access-groups/{group_id}",
        json={"name": "Accounting", "description": None},
    )
    cross_tenant_group = module_client.get(
        f"/organizations/{organization.id}/access-groups/{uuid4()}"
    )
    assert [item["id"] for item in listed.json()] == [group_id]
    assert read.json()["permissions"] == []
    assert read.json()["membership_ids"] == []
    assert updated.json()["name"] == "Accounting"
    assert updated.json()["description"] is None
    assert cross_tenant_group.status_code == 404

    authenticate(module_client, db_session, admin)
    assert module_client.get(
        f"/organizations/{organization.id}/access-groups"
    ).status_code == 403
    authenticate(module_client, db_session, member)
    assert module_client.post(
        f"/organizations/{organization.id}/access-groups",
        json={"name": "Forbidden"},
    ).status_code == 403

    authenticate(module_client, db_session, other_owner)
    same_name = module_client.post(
        f"/organizations/{other_organization.id}/access-groups",
        json={"name": "Accounting"},
    )
    assert same_name.status_code == 201
    assert module_client.get(
        f"/organizations/{organization.id}/access-groups"
    ).status_code == 403

    authenticate(module_client, db_session, owner)
    deleted = module_client.delete(
        f"/organizations/{organization.id}/access-groups/{group_id}"
    )
    assert deleted.status_code == 204
    assert db_session.get(User, member.id) is not None
    assert db_session.get(OrganizationMembership, member_membership.id) is not None


def test_permission_and_membership_replacement_is_atomic_and_tenant_safe(
    module_client: TestClient,
    db_session: Session,
    module_registry: ModuleRegistry,
) -> None:
    owner = create_user(db_session, "replace-owner@example.com")
    member = create_user(db_session, "replace-member@example.com")
    other_owner = create_user(db_session, "replace-other-owner@example.com")
    other_member = create_user(db_session, "replace-other-member@example.com")
    organization = organization_service.create_organization(
        db_session, "Replace Organization", owner.id
    )
    other_organization = organization_service.create_organization(
        db_session, "Replace Other Organization", other_owner.id
    )
    membership = add_membership(
        db_session,
        organization_id=organization.id,
        user_id=member.id,
        role="member",
    )
    other_membership = add_membership(
        db_session,
        organization_id=other_organization.id,
        user_id=other_member.id,
        role="member",
    )
    module_service.set_organization_module(
        db_session,
        organization_id=organization.id,
        module_key="operations_test",
        enabled=True,
        registry=module_registry,
    )
    authenticate(module_client, db_session, owner)
    first_group = module_client.post(
        f"/organizations/{organization.id}/access-groups",
        json={"name": "Operators"},
    ).json()
    second_group = module_client.post(
        f"/organizations/{organization.id}/access-groups",
        json={"name": "Reviewers"},
    ).json()

    permission_update = module_client.put(
        f"/organizations/{organization.id}/access-groups/{first_group['id']}/permissions",
        json={
            "permissions": [
                "operations_test.record.read",
                "operations_test.record.read",
                "operations_test.record.create",
            ]
        },
    )
    membership_update = module_client.put(
        f"/organizations/{organization.id}/access-groups/{first_group['id']}/memberships",
        json={"membership_ids": [str(membership.id), str(membership.id)]},
    )
    assert permission_update.status_code == 200
    assert permission_update.json()["permissions"] == [
        "operations_test.record.create",
        "operations_test.record.read",
    ]
    assert membership_update.json()["membership_ids"] == [str(membership.id)]

    invalid_permissions = module_client.put(
        f"/organizations/{organization.id}/access-groups/{first_group['id']}/permissions",
        json={"permissions": ["operations_test.record.update", "unknown.record.read"]},
    )
    invalid_memberships = module_client.put(
        f"/organizations/{organization.id}/access-groups/{first_group['id']}/memberships",
        json={"membership_ids": [str(membership.id), str(other_membership.id)]},
    )
    missing_membership = module_client.put(
        f"/organizations/{organization.id}/access-groups/{first_group['id']}/memberships",
        json={"membership_ids": [str(uuid4())]},
    )
    unchanged = module_client.get(
        f"/organizations/{organization.id}/access-groups/{first_group['id']}"
    ).json()
    assert invalid_permissions.status_code == 422
    assert invalid_memberships.status_code == 404
    assert missing_membership.status_code == 404
    assert unchanged["permissions"] == [
        "operations_test.record.create",
        "operations_test.record.read",
    ]
    assert unchanged["membership_ids"] == [str(membership.id)]

    second_membership_update = module_client.put(
        f"/organizations/{organization.id}/access-groups/{second_group['id']}/memberships",
        json={"membership_ids": [str(membership.id)]},
    )
    assert second_membership_update.status_code == 200
    assert db_session.scalar(
        select(func.count())
        .select_from(OrganizationMembershipAccessGroup)
        .where(
            OrganizationMembershipAccessGroup.organization_membership_id
            == membership.id
        )
    ) == 2


def test_effective_permissions_union_entitlement_filter_and_role_behavior(
    module_client: TestClient,
    db_session: Session,
    module_registry: ModuleRegistry,
) -> None:
    owner = create_user(db_session, "effective-owner@example.com")
    admin = create_user(db_session, "effective-admin@example.com")
    member = create_user(db_session, "effective-member@example.com")
    organization = organization_service.create_organization(
        db_session, "Effective Organization", owner.id
    )
    add_membership(
        db_session,
        organization_id=organization.id,
        user_id=admin.id,
        role="admin",
    )
    member_membership = add_membership(
        db_session,
        organization_id=organization.id,
        user_id=member.id,
        role="member",
    )
    module_service.set_organization_module(
        db_session,
        organization_id=organization.id,
        module_key="operations_test",
        enabled=True,
        registry=module_registry,
    )
    authenticate(module_client, db_session, owner)
    first_group = module_client.post(
        f"/organizations/{organization.id}/access-groups",
        json={"name": "Readers"},
    ).json()
    second_group = module_client.post(
        f"/organizations/{organization.id}/access-groups",
        json={"name": "Editors"},
    ).json()
    for group_id, permissions in (
        (
            first_group["id"],
            ["operations_test.record.read", "operations_test.record.update"],
        ),
        (
            second_group["id"],
            ["operations_test.record.read", "operations_test.record.delete"],
        ),
    ):
        assert module_client.put(
            f"/organizations/{organization.id}/access-groups/{group_id}/permissions",
            json={"permissions": permissions},
        ).status_code == 200
        assert module_client.put(
            f"/organizations/{organization.id}/access-groups/{group_id}/memberships",
            json={"membership_ids": [str(member_membership.id)]},
        ).status_code == 200

    owner_summary = module_client.get(
        f"/organizations/{organization.id}/access-control/me"
    ).json()
    assert owner_summary["is_owner"] is True
    assert owner_summary["enabled_modules"] == ["operations_test"]
    assert owner_summary["permissions"] == [
        "operations_test.record.create",
        "operations_test.record.delete",
        "operations_test.record.read",
        "operations_test.record.update",
    ]

    catalog = module_client.get(
        f"/organizations/{organization.id}/access-control/permission-catalog"
    )
    assert catalog.status_code == 200
    assert catalog.json()["modules"][0]["enabled"] is True

    authenticate(module_client, db_session, member)
    member_summary = module_client.get(
        f"/organizations/{organization.id}/access-control/me"
    ).json()
    assert member_summary == {
        "is_owner": False,
        "membership_role": "member",
        "enabled_modules": ["operations_test"],
        "permissions": [
            "operations_test.record.delete",
            "operations_test.record.read",
            "operations_test.record.update",
        ],
    }

    authenticate(module_client, db_session, admin)
    admin_summary = module_client.get(
        f"/organizations/{organization.id}/access-control/me"
    ).json()
    assert admin_summary["is_owner"] is False
    assert admin_summary["permissions"] == []
    assert module_client.get(
        f"/organizations/{organization.id}/access-control/permission-catalog"
    ).status_code == 403

    module_service.set_organization_module(
        db_session,
        organization_id=organization.id,
        module_key="operations_test",
        enabled=False,
        registry=module_registry,
    )
    authenticate(module_client, db_session, member)
    disabled_member = module_client.get(
        f"/organizations/{organization.id}/access-control/me"
    ).json()
    authenticate(module_client, db_session, owner)
    disabled_owner = module_client.get(
        f"/organizations/{organization.id}/access-control/me"
    ).json()
    assert disabled_member["enabled_modules"] == []
    assert disabled_member["permissions"] == []
    assert disabled_owner["permissions"] == []
    assert db_session.scalar(
        select(func.count()).select_from(OrganizationAccessGroupPermission)
    ) == 4

    module_service.set_organization_module(
        db_session,
        organization_id=organization.id,
        module_key="operations_test",
        enabled=True,
        registry=module_registry,
    )
    authenticate(module_client, db_session, member)
    restored = module_client.get(
        f"/organizations/{organization.id}/access-control/me"
    ).json()
    assert restored["permissions"] == member_summary["permissions"]


def test_group_deletion_removes_only_group_associations(
    module_client: TestClient, db_session: Session
) -> None:
    owner = create_user(db_session, "delete-group-owner@example.com")
    member = create_user(db_session, "delete-group-member@example.com")
    organization = organization_service.create_organization(
        db_session, "Delete Group Organization", owner.id
    )
    membership = add_membership(
        db_session,
        organization_id=organization.id,
        user_id=member.id,
        role="member",
    )
    authenticate(module_client, db_session, owner)
    group = module_client.post(
        f"/organizations/{organization.id}/access-groups",
        json={"name": "Temporary"},
    ).json()
    module_client.put(
        f"/organizations/{organization.id}/access-groups/{group['id']}/memberships",
        json={"membership_ids": [str(membership.id)]},
    )
    module_client.put(
        f"/organizations/{organization.id}/access-groups/{group['id']}/permissions",
        json={"permissions": ["operations_test.record.read"]},
    )

    response = module_client.delete(
        f"/organizations/{organization.id}/access-groups/{group['id']}"
    )

    assert response.status_code == 204
    assert db_session.get(User, member.id) is not None
    assert db_session.get(OrganizationMembership, membership.id) is not None
    assert db_session.scalar(
        select(func.count()).select_from(OrganizationMembershipAccessGroup)
    ) == 0
    assert db_session.scalar(
        select(func.count()).select_from(OrganizationAccessGroupPermission)
    ) == 0


def test_access_summary_uses_only_the_current_memberships_groups(
    module_client: TestClient,
    db_session: Session,
    module_registry: ModuleRegistry,
) -> None:
    owner = create_user(db_session, "summary-owner@example.com")
    assigned_user = create_user(db_session, "summary-assigned@example.com")
    unassigned_user = create_user(db_session, "summary-unassigned@example.com")
    outsider = create_user(db_session, "summary-outsider@example.com")
    organization = organization_service.create_organization(
        db_session, "Summary Organization", owner.id
    )
    assigned_membership = add_membership(
        db_session,
        organization_id=organization.id,
        user_id=assigned_user.id,
        role="member",
    )
    add_membership(
        db_session,
        organization_id=organization.id,
        user_id=unassigned_user.id,
        role="member",
    )
    module_service.set_organization_module(
        db_session,
        organization_id=organization.id,
        module_key="operations_test",
        enabled=True,
        registry=module_registry,
    )
    authenticate(module_client, db_session, owner)
    group = module_client.post(
        f"/organizations/{organization.id}/access-groups",
        json={"name": "Assigned Readers"},
    ).json()
    module_client.put(
        f"/organizations/{organization.id}/access-groups/{group['id']}/permissions",
        json={"permissions": ["operations_test.record.read"]},
    )
    module_client.put(
        f"/organizations/{organization.id}/access-groups/{group['id']}/memberships",
        json={"membership_ids": [str(assigned_membership.id)]},
    )

    authenticate(module_client, db_session, assigned_user)
    assigned = module_client.get(
        f"/organizations/{organization.id}/access-control/me"
    ).json()
    authenticate(module_client, db_session, unassigned_user)
    unassigned = module_client.get(
        f"/organizations/{organization.id}/access-control/me"
    ).json()
    authenticate(module_client, db_session, outsider)
    cross_tenant = module_client.get(
        f"/organizations/{organization.id}/access-control/me"
    )

    assert assigned["permissions"] == ["operations_test.record.read"]
    assert unassigned["permissions"] == []
    assert cross_tenant.status_code == 403


def test_concurrent_permission_replacements_never_mix_sets(
    test_engine: Engine, module_registry: ModuleRegistry
) -> None:
    with Session(test_engine) as setup:
        owner = create_user(setup, f"replace-concurrent-{uuid4().hex}@example.com")
        organization = organization_service.create_organization(
            setup, f"Concurrent Permissions {uuid4().hex}", owner.id
        )
        group = access_service.create_access_group(
            setup,
            organization_id=organization.id,
            name="Concurrent Group",
            description=None,
        )
        user_id = owner.id
        membership_id = membership_repository.get_membership_for_user_organization(
            setup,
            user_id=owner.id,
            organization_id=organization.id,
        ).id
        organization_id = organization.id
        group_id = group.id
    permission_sets = [
        ["operations_test.record.read", "operations_test.record.create"],
        ["operations_test.record.update", "operations_test.record.delete"],
    ]
    start = Barrier(2)

    def replace_once(permission_keys: list[str]) -> tuple[str, ...]:
        with Session(test_engine) as session:
            start.wait(timeout=10)
            details = access_service.replace_access_group_permissions(
                session,
                organization_id=organization_id,
                access_group_id=group_id,
                permission_keys=permission_keys,
                registry=module_registry,
            )
            return tuple(details.permission_keys)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(replace_once, permission_sets))
        with Session(test_engine) as check:
            final_permissions = tuple(
                sorted(
                    check.scalars(
                        select(OrganizationAccessGroupPermission.permission_key).where(
                            OrganizationAccessGroupPermission.access_group_id == group_id
                        )
                    )
                )
            )
        expected = {tuple(sorted(item)) for item in permission_sets}
        assert set(results) == expected
        assert final_permissions in expected
    finally:
        with Session(test_engine) as cleanup:
            cleanup.execute(
                delete(OrganizationAccessGroupPermission).where(
                    OrganizationAccessGroupPermission.access_group_id == group_id
                )
            )
            cleanup.execute(
                delete(OrganizationMembershipAccessGroup).where(
                    OrganizationMembershipAccessGroup.organization_membership_id
                    == membership_id
                )
            )
            cleanup.execute(
                delete(OrganizationAccessGroup).where(
                    OrganizationAccessGroup.id == group_id
                )
            )
            cleanup.execute(
                delete(OrganizationMembership).where(
                    OrganizationMembership.id == membership_id
                )
            )
            cleanup.execute(delete(User).where(User.id == user_id))
            cleanup.execute(
                delete(Organization).where(Organization.id == organization_id)
            )
            cleanup.commit()
