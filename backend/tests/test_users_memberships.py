from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import service as auth_service
from app.core.auth.dependencies import AUTH_SESSION_COOKIE_NAME
from app.core.organization_memberships import service as membership_service
from app.core.organization_memberships.model import OrganizationMembership
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


def create_organization(
    session: Session, owner: User, name: str = "Acme"
) -> Organization:
    return organization_service.create_organization(session, name, owner.id)


def add_membership(
    session: Session,
    *,
    organization: Organization,
    actor: User,
    user: User,
    role: str = "member",
) -> OrganizationMembership:
    return membership_service.create_membership(
        session,
        organization_id=organization.id,
        user_id=user.id,
        role=role,
        current_user_id=actor.id,
    )


def test_user_routes_require_authentication(client: TestClient) -> None:
    user_id = uuid4()

    get_response = client.get(f"/users/{user_id}")
    patch_response = client.patch(f"/users/{user_id}", json={"name": "Name"})

    assert get_response.status_code == 401
    assert patch_response.status_code == 401


def test_global_user_creation_and_listing_routes_are_removed(
    client: TestClient, db_session: Session
) -> None:
    user = create_user(db_session)
    authenticate(client, db_session, user)

    list_response = client.get("/users")
    create_response = client.post(
        "/users", json={"email": "new@example.com", "name": "New"}
    )

    assert list_response.status_code == 404
    assert create_response.status_code == 404


def test_user_can_retrieve_themselves(client: TestClient, db_session: Session) -> None:
    user = create_user(db_session)
    authenticate(client, db_session, user)

    response = client.get(f"/users/{user.id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(user.id)
    assert response.json()["email"] == user.email


def test_user_cannot_retrieve_another_user(
    client: TestClient, db_session: Session
) -> None:
    current_user = create_user(db_session)
    other_user = create_user(db_session, email="other@example.com", name="Other")
    authenticate(client, db_session, current_user)

    response = client.get(f"/users/{other_user.id}")

    assert response.status_code == 403


def test_user_can_update_themselves(client: TestClient, db_session: Session) -> None:
    user = create_user(db_session)
    authenticate(client, db_session, user)

    response = client.patch(
        f"/users/{user.id}",
        json={"email": "  NEW@EXAMPLE.COM  ", "name": "  New Name  "},
    )

    assert response.status_code == 200
    assert response.json()["email"] == "new@example.com"
    assert response.json()["name"] == "New Name"


def test_user_cannot_update_another_user(
    client: TestClient, db_session: Session
) -> None:
    current_user = create_user(db_session)
    other_user = create_user(db_session, email="other@example.com", name="Other")
    authenticate(client, db_session, current_user)

    response = client.patch(f"/users/{other_user.id}", json={"name": "Changed"})

    assert response.status_code == 403
    db_session.refresh(other_user)
    assert other_user.name == "Other"


def test_update_user_rejects_empty_or_null_changes(
    client: TestClient, db_session: Session
) -> None:
    user = create_user(db_session)
    authenticate(client, db_session, user)

    empty_response = client.patch(f"/users/{user.id}", json={})
    null_response = client.patch(f"/users/{user.id}", json={"name": None})

    assert empty_response.status_code == 422
    assert null_response.status_code == 422


def test_update_user_rejects_duplicate_email(
    client: TestClient, db_session: Session
) -> None:
    first_user = create_user(db_session, email="first@example.com", name="First")
    create_user(db_session, email="second@example.com", name="Second")
    authenticate(client, db_session, first_user)

    response = client.patch(
        f"/users/{first_user.id}",
        json={"email": "SECOND@EXAMPLE.COM"},
    )

    assert response.status_code == 409


def test_user_service_normalizes_and_rejects_duplicate_email(
    db_session: Session,
) -> None:
    user = user_service.create_user(
        db_session,
        email="  LUCAS@EXAMPLE.COM  ",
        name="  Lucas  ",
    )

    assert user.email == "lucas@example.com"
    assert user.name == "Lucas"
    with pytest.raises(user_service.UserEmailConflictError):
        user_service.create_user(
            db_session,
            email="LUCAS@EXAMPLE.COM",
            name="Other Lucas",
        )


def test_user_service_reraises_non_unique_integrity_error(db_session: Session) -> None:
    db_session.add(User(email="invalid@example.com", name=None))

    with pytest.raises(IntegrityError) as error:
        user_service.create_user(db_session, email="lucas@example.com", name="Lucas")

    assert error.value.orig.sqlstate == "23502"


def test_membership_routes_require_authentication(client: TestClient) -> None:
    organization_id = uuid4()
    membership_id = uuid4()
    user_id = uuid4()
    responses = [
        client.get(f"/organizations/{organization_id}/memberships"),
        client.get(f"/users/{user_id}/memberships"),
        client.post(
            f"/organizations/{organization_id}/memberships",
            json={"user_id": str(user_id), "role": "member"},
        ),
        client.patch(
            f"/organizations/{organization_id}/memberships/{membership_id}",
            json={"role": "admin"},
        ),
    ]

    assert {response.status_code for response in responses} == {401}


def test_organization_member_can_list_memberships(
    client: TestClient, db_session: Session
) -> None:
    owner = create_user(db_session, email="owner@example.com", name="Owner")
    member = create_user(db_session, email="member@example.com", name="Member")
    organization = create_organization(db_session, owner)
    add_membership(
        db_session,
        organization=organization,
        actor=owner,
        user=member,
    )
    authenticate(client, db_session, member)

    response = client.get(f"/organizations/{organization.id}/memberships")

    assert response.status_code == 200
    assert {item["user_id"] for item in response.json()} == {
        str(owner.id),
        str(member.id),
    }


def test_outsider_cannot_list_organization_memberships(
    client: TestClient, db_session: Session
) -> None:
    owner = create_user(db_session, email="owner@example.com", name="Owner")
    outsider = create_user(db_session, email="outsider@example.com", name="Outsider")
    organization = create_organization(db_session, owner)
    authenticate(client, db_session, outsider)

    response = client.get(f"/organizations/{organization.id}/memberships")

    assert response.status_code == 403


def test_user_can_list_only_their_own_memberships(
    client: TestClient, db_session: Session
) -> None:
    owner = create_user(db_session, email="owner@example.com", name="Owner")
    member = create_user(db_session, email="member@example.com", name="Member")
    organization = create_organization(db_session, owner)
    membership = add_membership(
        db_session,
        organization=organization,
        actor=owner,
        user=member,
    )
    authenticate(client, db_session, member)

    own_response = client.get(f"/users/{member.id}/memberships")
    other_response = client.get(f"/users/{owner.id}/memberships")

    assert own_response.status_code == 200
    assert [item["id"] for item in own_response.json()] == [str(membership.id)]
    assert other_response.status_code == 403


@pytest.mark.parametrize("role", ["owner", "admin", "member"])
def test_owner_can_add_any_supported_role(
    client: TestClient, db_session: Session, role: str
) -> None:
    owner = create_user(db_session, email="owner@example.com", name="Owner")
    target = create_user(db_session, email="target@example.com", name="Target")
    organization = create_organization(db_session, owner)
    authenticate(client, db_session, owner)

    response = client.post(
        f"/organizations/{organization.id}/memberships",
        json={"user_id": str(target.id), "role": role},
    )

    assert response.status_code == 201
    assert response.json()["role"] == role


@pytest.mark.parametrize("role", ["admin", "member"])
def test_admin_can_add_admin_or_member(
    client: TestClient, db_session: Session, role: str
) -> None:
    owner = create_user(db_session, email="owner@example.com", name="Owner")
    admin = create_user(db_session, email="admin@example.com", name="Admin")
    target = create_user(db_session, email="target@example.com", name="Target")
    organization = create_organization(db_session, owner)
    add_membership(
        db_session,
        organization=organization,
        actor=owner,
        user=admin,
        role="admin",
    )
    authenticate(client, db_session, admin)

    response = client.post(
        f"/organizations/{organization.id}/memberships",
        json={"user_id": str(target.id), "role": role},
    )

    assert response.status_code == 201
    assert response.json()["role"] == role


def test_admin_cannot_create_owner(client: TestClient, db_session: Session) -> None:
    owner = create_user(db_session, email="owner@example.com", name="Owner")
    admin = create_user(db_session, email="admin@example.com", name="Admin")
    target = create_user(db_session, email="target@example.com", name="Target")
    organization = create_organization(db_session, owner)
    add_membership(
        db_session,
        organization=organization,
        actor=owner,
        user=admin,
        role="admin",
    )
    authenticate(client, db_session, admin)

    response = client.post(
        f"/organizations/{organization.id}/memberships",
        json={"user_id": str(target.id), "role": "owner"},
    )

    assert response.status_code == 403


def test_member_cannot_create_membership(
    client: TestClient, db_session: Session
) -> None:
    owner = create_user(db_session, email="owner@example.com", name="Owner")
    member = create_user(db_session, email="member@example.com", name="Member")
    target = create_user(db_session, email="target@example.com", name="Target")
    organization = create_organization(db_session, owner)
    add_membership(
        db_session,
        organization=organization,
        actor=owner,
        user=member,
    )
    authenticate(client, db_session, member)

    response = client.post(
        f"/organizations/{organization.id}/memberships",
        json={"user_id": str(target.id), "role": "member"},
    )

    assert response.status_code == 403


def test_member_cannot_update_membership(
    client: TestClient, db_session: Session
) -> None:
    owner = create_user(db_session, email="owner@example.com", name="Owner")
    member = create_user(db_session, email="member@example.com", name="Member")
    target = create_user(db_session, email="target@example.com", name="Target")
    organization = create_organization(db_session, owner)
    add_membership(
        db_session,
        organization=organization,
        actor=owner,
        user=member,
    )
    target_membership = add_membership(
        db_session,
        organization=organization,
        actor=owner,
        user=target,
    )
    authenticate(client, db_session, member)

    response = client.patch(
        f"/organizations/{organization.id}/memberships/{target_membership.id}",
        json={"role": "admin"},
    )

    assert response.status_code == 403


def test_create_membership_rejects_missing_user(
    client: TestClient, db_session: Session
) -> None:
    owner = create_user(db_session)
    organization = create_organization(db_session, owner)
    authenticate(client, db_session, owner)

    response = client.post(
        f"/organizations/{organization.id}/memberships",
        json={"user_id": str(uuid4()), "role": "member"},
    )

    assert response.status_code == 404


def test_create_membership_rejects_missing_organization(
    client: TestClient, db_session: Session
) -> None:
    user = create_user(db_session)
    authenticate(client, db_session, user)

    response = client.post(
        f"/organizations/{uuid4()}/memberships",
        json={"user_id": str(user.id), "role": "member"},
    )

    assert response.status_code == 404


def test_create_membership_rejects_duplicate(
    client: TestClient, db_session: Session
) -> None:
    owner = create_user(db_session, email="owner@example.com", name="Owner")
    target = create_user(db_session, email="target@example.com", name="Target")
    organization = create_organization(db_session, owner)
    add_membership(
        db_session,
        organization=organization,
        actor=owner,
        user=target,
    )
    authenticate(client, db_session, owner)

    response = client.post(
        f"/organizations/{organization.id}/memberships",
        json={"user_id": str(target.id), "role": "admin"},
    )

    assert response.status_code == 409


def test_membership_service_reraises_non_unique_integrity_error(
    db_session: Session,
) -> None:
    owner = create_user(db_session, email="owner@example.com", name="Owner")
    target = create_user(db_session, email="target@example.com", name="Target")
    organization = create_organization(db_session, owner)

    with pytest.raises(IntegrityError) as error:
        membership_service.create_membership(
            db_session,
            organization_id=organization.id,
            user_id=target.id,
            role="invalid",
            current_user_id=owner.id,
        )

    assert error.value.orig.sqlstate == "23514"


@pytest.mark.parametrize("role", ["owner", "admin", "member"])
def test_owner_can_update_membership_roles(
    client: TestClient, db_session: Session, role: str
) -> None:
    owner = create_user(db_session, email="owner@example.com", name="Owner")
    target = create_user(db_session, email="target@example.com", name="Target")
    organization = create_organization(db_session, owner)
    membership = add_membership(
        db_session,
        organization=organization,
        actor=owner,
        user=target,
    )
    authenticate(client, db_session, owner)

    response = client.patch(
        f"/organizations/{organization.id}/memberships/{membership.id}",
        json={"role": role},
    )

    assert response.status_code == 200
    assert response.json()["role"] == role


def test_admin_cannot_modify_owner(client: TestClient, db_session: Session) -> None:
    owner = create_user(db_session, email="owner@example.com", name="Owner")
    admin = create_user(db_session, email="admin@example.com", name="Admin")
    organization = create_organization(db_session, owner)
    add_membership(
        db_session,
        organization=organization,
        actor=owner,
        user=admin,
        role="admin",
    )
    owner_membership = membership_service.list_user_memberships(
        db_session, owner.id, owner.id
    )[0]
    authenticate(client, db_session, admin)

    response = client.patch(
        f"/organizations/{organization.id}/memberships/{owner_membership.id}",
        json={"role": "admin"},
    )

    assert response.status_code == 403


def test_admin_cannot_promote_to_owner(client: TestClient, db_session: Session) -> None:
    owner = create_user(db_session, email="owner@example.com", name="Owner")
    admin = create_user(db_session, email="admin@example.com", name="Admin")
    member = create_user(db_session, email="member@example.com", name="Member")
    organization = create_organization(db_session, owner)
    add_membership(
        db_session,
        organization=organization,
        actor=owner,
        user=admin,
        role="admin",
    )
    membership = add_membership(
        db_session,
        organization=organization,
        actor=owner,
        user=member,
    )
    authenticate(client, db_session, admin)

    response = client.patch(
        f"/organizations/{organization.id}/memberships/{membership.id}",
        json={"role": "owner"},
    )

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("initial_role", "new_role"),
    [("member", "admin"), ("admin", "member")],
)
def test_admin_can_change_member_and_admin_roles(
    client: TestClient,
    db_session: Session,
    initial_role: str,
    new_role: str,
) -> None:
    owner = create_user(db_session, email="owner@example.com", name="Owner")
    admin = create_user(db_session, email="admin@example.com", name="Admin")
    target = create_user(db_session, email="target@example.com", name="Target")
    organization = create_organization(db_session, owner)
    add_membership(
        db_session,
        organization=organization,
        actor=owner,
        user=admin,
        role="admin",
    )
    target_membership = add_membership(
        db_session,
        organization=organization,
        actor=owner,
        user=target,
        role=initial_role,
    )
    authenticate(client, db_session, admin)

    response = client.patch(
        f"/organizations/{organization.id}/memberships/{target_membership.id}",
        json={"role": new_role},
    )

    assert response.status_code == 200
    assert response.json()["role"] == new_role


def test_sole_owner_cannot_be_demoted(client: TestClient, db_session: Session) -> None:
    owner = create_user(db_session)
    organization = create_organization(db_session, owner)
    owner_membership = membership_service.list_user_memberships(
        db_session, owner.id, owner.id
    )[0]
    authenticate(client, db_session, owner)

    response = client.patch(
        f"/organizations/{organization.id}/memberships/{owner_membership.id}",
        json={"role": "admin"},
    )

    assert response.status_code == 409
    db_session.refresh(owner_membership)
    assert owner_membership.role == "owner"


def test_membership_cannot_be_modified_through_another_organization(
    client: TestClient, db_session: Session
) -> None:
    owner = create_user(db_session, email="owner@example.com", name="Owner")
    member = create_user(db_session, email="member@example.com", name="Member")
    first_organization = create_organization(db_session, owner, "Acme")
    second_organization = create_organization(db_session, owner, "Globex")
    membership = add_membership(
        db_session,
        organization=first_organization,
        actor=owner,
        user=member,
    )
    authenticate(client, db_session, owner)

    response = client.patch(
        f"/organizations/{second_organization.id}/memberships/{membership.id}",
        json={"role": "admin"},
    )

    assert response.status_code == 404


def test_update_membership_rejects_invalid_role(
    client: TestClient, db_session: Session
) -> None:
    owner = create_user(db_session, email="owner@example.com", name="Owner")
    member = create_user(db_session, email="member@example.com", name="Member")
    organization = create_organization(db_session, owner)
    membership = add_membership(
        db_session,
        organization=organization,
        actor=owner,
        user=member,
    )
    authenticate(client, db_session, owner)

    response = client.patch(
        f"/organizations/{organization.id}/memberships/{membership.id}",
        json={"role": "superadmin"},
    )

    assert response.status_code == 422
