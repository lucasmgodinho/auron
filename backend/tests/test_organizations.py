from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import service as auth_service
from app.core.auth.dependencies import AUTH_SESSION_COOKIE_NAME
from app.core.organization_memberships import service as membership_service
from app.core.organizations import service as organization_service
from app.core.organizations.model import Organization
from app.core.users import service as user_service
from app.core.users.model import User


def create_user(
    session: Session,
    *,
    email: str = "lucas@example.com",
    name: str = "Lucas",
) -> User:
    return user_service.create_user(session, email=email, name=name)


def authenticate(client: TestClient, session: Session, user: User) -> None:
    _, raw_token = auth_service.create_auth_session(session, user.id)
    client.cookies.set(AUTH_SESSION_COOKIE_NAME, raw_token)


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/organizations", None),
        ("get", f"/organizations/{uuid4()}", None),
        ("patch", f"/organizations/{uuid4()}", {"name": "Acme"}),
    ],
)
def test_organization_endpoints_require_authentication(
    client: TestClient, method: str, path: str, payload: dict[str, str] | None
) -> None:
    response = client.request(method, path, json=payload)

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_ordinary_authenticated_user_cannot_create_organization(
    client: TestClient, db_session: Session
) -> None:
    user = create_user(db_session)
    authenticate(client, db_session, user)

    response = client.post("/organizations", json={"name": "Acme"})

    assert response.status_code == 405
    assert db_session.scalar(select(func.count()).select_from(Organization)) == 0


def test_organization_and_initial_owner_are_created_atomically(
    db_session: Session,
) -> None:
    organization_name = "Must roll back"

    with pytest.raises(IntegrityError):
        organization_service.create_organization(
            db_session,
            organization_name,
            uuid4(),
        )

    assert db_session.scalar(
        select(Organization).where(Organization.name == organization_name)
    ) is None


def test_get_organization_requires_membership(
    client: TestClient, db_session: Session
) -> None:
    owner = create_user(db_session, email="owner@example.com", name="Owner")
    outsider = create_user(db_session, email="outsider@example.com", name="Outsider")
    organization = organization_service.create_organization(db_session, "Acme", owner.id)
    authenticate(client, db_session, outsider)

    response = client.get(f"/organizations/{organization.id}")

    assert response.status_code == 403


def test_get_missing_organization_returns_not_found(
    client: TestClient, db_session: Session
) -> None:
    user = create_user(db_session)
    authenticate(client, db_session, user)

    response = client.get(f"/organizations/{uuid4()}")

    assert response.status_code == 404


def test_list_organizations_returns_only_current_users_organizations(
    client: TestClient, db_session: Session
) -> None:
    current_user = create_user(db_session)
    other_user = create_user(db_session, email="other@example.com", name="Other")
    authenticate(client, db_session, current_user)
    accessible = organization_service.create_organization(
        db_session, "Acme", current_user.id
    )
    organization_service.create_organization(db_session, "Other", other_user.id)

    response = client.get("/organizations")

    assert response.status_code == 200
    assert [organization["id"] for organization in response.json()] == [
        str(accessible.id)
    ]


def test_list_organizations_paginates_within_current_users_memberships(
    client: TestClient, db_session: Session
) -> None:
    user = create_user(db_session)
    authenticate(client, db_session, user)
    for name in ("Acme", "Globex", "Initech"):
        organization_service.create_organization(db_session, name, user.id)

    all_organizations = client.get("/organizations").json()
    response = client.get("/organizations", params={"limit": 1, "offset": 1})

    assert response.status_code == 200
    assert response.json() == all_organizations[1:2]


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_owner_and_admin_can_update_organization(
    client: TestClient, db_session: Session, role: str
) -> None:
    owner = create_user(db_session, email="owner@example.com", name="Owner")
    actor = owner
    organization = organization_service.create_organization(db_session, "Acme", owner.id)
    if role == "admin":
        actor = create_user(db_session, email="admin@example.com", name="Admin")
        membership_service.create_membership(
            db_session,
            organization_id=organization.id,
            user_id=actor.id,
            role="admin",
            current_user_id=owner.id,
        )
    authenticate(client, db_session, actor)

    response = client.patch(
        f"/organizations/{organization.id}",
        json={"name": "  Acme Holdings  "},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Acme Holdings"


def test_member_cannot_update_organization(
    client: TestClient, db_session: Session
) -> None:
    owner = create_user(db_session, email="owner@example.com", name="Owner")
    member = create_user(db_session, email="member@example.com", name="Member")
    organization = organization_service.create_organization(db_session, "Acme", owner.id)
    membership_service.create_membership(
        db_session,
        organization_id=organization.id,
        user_id=member.id,
        role="member",
        current_user_id=owner.id,
    )
    authenticate(client, db_session, member)

    response = client.patch(
        f"/organizations/{organization.id}", json={"name": "Forbidden"}
    )

    assert response.status_code == 403


def test_update_missing_organization_returns_not_found(
    client: TestClient, db_session: Session
) -> None:
    user = create_user(db_session)
    authenticate(client, db_session, user)

    response = client.patch(f"/organizations/{uuid4()}", json={"name": "Acme"})

    assert response.status_code == 404
