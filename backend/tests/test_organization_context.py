from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.auth import service as auth_service
from app.core.auth.dependencies import AUTH_SESSION_COOKIE_NAME
from app.core.organization_context.dependencies import get_organization_context
from app.core.organization_memberships import repository as membership_repository
from app.core.organization_memberships import service as membership_service
from app.core.organizations import service as organization_service
from app.core.organizations.model import Organization
from app.core.users import service as user_service
from app.core.users.model import User


def create_user(session: Session, *, email: str, name: str) -> User:
    return user_service.create_user(session, email=email, name=name)


def create_organization(session: Session, owner: User, name: str) -> Organization:
    return organization_service.create_organization(session, name, owner.id)


def authenticate(client: TestClient, session: Session, user: User) -> None:
    _, raw_token = auth_service.create_auth_session(session, user.id)
    client.cookies.set(AUTH_SESSION_COOKIE_NAME, raw_token)


def test_organization_context_route_requires_authentication(client: TestClient) -> None:
    response = client.get(f"/organizations/{uuid4()}")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


@pytest.mark.parametrize("role", ["owner", "admin", "member"])
def test_organization_context_contains_exact_models_and_role(
    db_session: Session, role: str
) -> None:
    owner = create_user(db_session, email="owner@example.com", name="Owner")
    organization = create_organization(db_session, owner, "Acme")
    user = owner

    if role != "owner":
        user = create_user(
            db_session,
            email=f"{role}@example.com",
            name=role.title(),
        )
        membership_service.create_membership(
            db_session,
            organization_id=organization.id,
            user_id=user.id,
            role=role,
            current_user_id=owner.id,
        )

    expected_membership = (
        membership_repository.get_membership_for_user_organization(
            db_session,
            user_id=user.id,
            organization_id=organization.id,
        )
    )
    context = get_organization_context(organization.id, db_session, user)

    assert expected_membership is not None
    assert context.user is user
    assert context.organization is organization
    assert context.membership is expected_membership
    assert context.membership.role == role


def test_route_organization_id_selects_the_matching_context(
    client: TestClient, db_session: Session
) -> None:
    user = create_user(db_session, email="user@example.com", name="User")
    first_organization = create_organization(db_session, user, "Acme")
    second_organization = create_organization(db_session, user, "Globex")
    authenticate(client, db_session, user)

    first_response = client.get(f"/organizations/{first_organization.id}")
    second_response = client.get(f"/organizations/{second_organization.id}")
    first_context = get_organization_context(
        first_organization.id, db_session, user
    )
    second_context = get_organization_context(
        second_organization.id, db_session, user
    )

    assert first_response.status_code == second_response.status_code == 200
    assert first_response.json()["id"] == str(first_organization.id)
    assert second_response.json()["id"] == str(second_organization.id)
    assert first_context.organization.id == first_organization.id
    assert second_context.organization.id == second_organization.id
    assert first_context.membership.organization_id == first_organization.id
    assert second_context.membership.organization_id == second_organization.id


def test_changing_route_organization_id_cannot_bypass_membership(
    client: TestClient, db_session: Session
) -> None:
    current_user = create_user(
        db_session, email="current@example.com", name="Current"
    )
    other_user = create_user(db_session, email="other@example.com", name="Other")
    accessible = create_organization(db_session, current_user, "Accessible")
    inaccessible = create_organization(db_session, other_user, "Inaccessible")
    authenticate(client, db_session, current_user)

    accessible_response = client.get(f"/organizations/{accessible.id}")
    inaccessible_response = client.get(f"/organizations/{inaccessible.id}")

    assert accessible_response.status_code == 200
    assert inaccessible_response.status_code == 403
    assert inaccessible_response.json() == {"detail": "Forbidden"}


def test_users_with_different_memberships_are_cross_tenant_isolated(
    client: TestClient, db_session: Session
) -> None:
    first_user = create_user(db_session, email="first@example.com", name="First")
    second_user = create_user(db_session, email="second@example.com", name="Second")
    first_organization = create_organization(db_session, first_user, "First organization")
    second_organization = create_organization(
        db_session, second_user, "Second organization"
    )

    authenticate(client, db_session, first_user)
    assert client.get(f"/organizations/{first_organization.id}").status_code == 200
    assert client.get(f"/organizations/{second_organization.id}").status_code == 403

    authenticate(client, db_session, second_user)
    assert client.get(f"/organizations/{second_organization.id}").status_code == 200
    assert client.get(f"/organizations/{first_organization.id}").status_code == 403


def test_missing_organization_returns_not_found(
    client: TestClient, db_session: Session
) -> None:
    user = create_user(db_session, email="user@example.com", name="User")
    authenticate(client, db_session, user)

    response = client.get(f"/organizations/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_existing_organization_without_membership_returns_forbidden(
    client: TestClient, db_session: Session
) -> None:
    owner = create_user(db_session, email="owner@example.com", name="Owner")
    outsider = create_user(db_session, email="outsider@example.com", name="Outsider")
    organization = create_organization(db_session, owner, "Acme")
    authenticate(client, db_session, outsider)

    response = client.get(f"/organizations/{organization.id}")

    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}


def test_membership_removal_affects_next_request_without_revoking_session(
    client: TestClient, db_session: Session
) -> None:
    user = create_user(db_session, email="user@example.com", name="User")
    organization = create_organization(db_session, user, "Acme")
    authenticate(client, db_session, user)

    assert client.get(f"/organizations/{organization.id}").status_code == 200
    membership = membership_repository.get_membership_for_user_organization(
        db_session,
        user_id=user.id,
        organization_id=organization.id,
    )
    assert membership is not None
    db_session.delete(membership)
    db_session.commit()

    organization_response = client.get(f"/organizations/{organization.id}")
    auth_response = client.get("/auth/me")

    assert organization_response.status_code == 403
    assert auth_response.status_code == 200
    assert auth_response.json()["id"] == str(user.id)
