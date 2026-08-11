from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.organization_memberships import service as membership_service
from app.core.organizations import service as organization_service
from app.core.users import service as user_service
from app.core.users.model import User


def create_user(
    client: TestClient,
    *,
    email: str = "lucas@example.com",
    name: str = "Lucas",
) -> dict[str, object]:
    response = client.post("/users", json={"email": email, "name": name})
    assert response.status_code == 201
    return response.json()


def create_organization(client: TestClient, name: str = "Acme") -> dict[str, object]:
    response = client.post("/organizations", json={"name": name})
    assert response.status_code == 201
    return response.json()


def create_membership(
    client: TestClient,
    organization_id: object,
    user_id: object,
    role: str = "member",
) -> dict[str, object]:
    response = client.post(
        f"/organizations/{organization_id}/memberships",
        json={"user_id": user_id, "role": role},
    )
    assert response.status_code == 201
    return response.json()


def test_create_user(client: TestClient) -> None:
    user = create_user(client)

    assert user["email"] == "lucas@example.com"
    assert user["name"] == "Lucas"
    assert user["id"]
    assert user["created_at"]
    assert user["updated_at"]


def test_create_user_normalizes_name(client: TestClient) -> None:
    user = create_user(client, name="  Lucas  ")

    assert user["name"] == "Lucas"


def test_create_user_normalizes_email(client: TestClient) -> None:
    user = create_user(client, email="  LUCAS@EXAMPLE.COM  ")

    assert user["email"] == "lucas@example.com"


def test_create_user_rejects_invalid_email(client: TestClient) -> None:
    response = client.post("/users", json={"email": "not-an-email", "name": "Lucas"})

    assert response.status_code == 422


def test_create_user_rejects_empty_name(client: TestClient) -> None:
    response = client.post("/users", json={"email": "lucas@example.com", "name": ""})

    assert response.status_code == 422


def test_create_user_rejects_whitespace_only_name(client: TestClient) -> None:
    response = client.post("/users", json={"email": "lucas@example.com", "name": "   "})

    assert response.status_code == 422


def test_create_user_rejects_duplicate_email(client: TestClient) -> None:
    create_user(client, email="lucas@example.com")

    response = client.post(
        "/users", json={"email": "LUCAS@EXAMPLE.COM", "name": "Other Lucas"}
    )

    assert response.status_code == 409


def test_user_service_reraises_non_unique_integrity_error(db_session: Session) -> None:
    db_session.add(User(email="invalid@example.com", name=None))

    with pytest.raises(IntegrityError) as error:
        user_service.create_user(db_session, email="lucas@example.com", name="Lucas")

    assert error.value.orig.sqlstate == "23502"


def test_get_user(client: TestClient) -> None:
    created = create_user(client)

    response = client.get(f"/users/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_missing_user_returns_not_found(client: TestClient) -> None:
    response = client.get(f"/users/{uuid4()}")

    assert response.status_code == 404


def test_list_users(client: TestClient) -> None:
    created = [
        create_user(client, email="lucas@example.com", name="Lucas"),
        create_user(client, email="ana@example.com", name="Ana"),
    ]

    response = client.get("/users")

    assert response.status_code == 200
    assert {user["id"] for user in response.json()} == {user["id"] for user in created}


def test_list_users_paginates(client: TestClient) -> None:
    for index in range(3):
        create_user(client, email=f"user{index}@example.com", name=f"User {index}")

    all_users = client.get("/users").json()
    response = client.get("/users", params={"limit": 1, "offset": 1})

    assert response.status_code == 200
    assert response.json() == all_users[1:2]


def test_update_user(client: TestClient) -> None:
    created = create_user(client)

    response = client.patch(
        f"/users/{created['id']}",
        json={"email": "  NEW@EXAMPLE.COM  ", "name": "  New Name  "},
    )

    assert response.status_code == 200
    assert response.json()["email"] == "new@example.com"
    assert response.json()["name"] == "New Name"


def test_update_user_rejects_empty_or_null_changes(client: TestClient) -> None:
    created = create_user(client)

    empty_response = client.patch(f"/users/{created['id']}", json={})
    null_response = client.patch(f"/users/{created['id']}", json={"name": None})

    assert empty_response.status_code == 422
    assert null_response.status_code == 422


def test_update_user_rejects_duplicate_email(client: TestClient) -> None:
    first_user = create_user(client, email="first@example.com", name="First")
    create_user(client, email="second@example.com", name="Second")

    response = client.patch(
        f"/users/{first_user['id']}",
        json={"email": "SECOND@EXAMPLE.COM"},
    )

    assert response.status_code == 409


def test_create_membership(client: TestClient) -> None:
    user = create_user(client)
    organization = create_organization(client)

    membership = create_membership(client, organization["id"], user["id"], "owner")

    assert membership["user_id"] == user["id"]
    assert membership["organization_id"] == organization["id"]
    assert membership["role"] == "owner"


def test_create_membership_rejects_missing_user(client: TestClient) -> None:
    organization = create_organization(client)

    response = client.post(
        f"/organizations/{organization['id']}/memberships",
        json={"user_id": str(uuid4()), "role": "member"},
    )

    assert response.status_code == 404


def test_create_membership_rejects_missing_organization(client: TestClient) -> None:
    user = create_user(client)

    response = client.post(
        f"/organizations/{uuid4()}/memberships",
        json={"user_id": user["id"], "role": "member"},
    )

    assert response.status_code == 404


def test_create_membership_rejects_duplicate(client: TestClient) -> None:
    user = create_user(client)
    organization = create_organization(client)
    create_membership(client, organization["id"], user["id"])

    response = client.post(
        f"/organizations/{organization['id']}/memberships",
        json={"user_id": user["id"], "role": "admin"},
    )

    assert response.status_code == 409


def test_membership_service_reraises_non_unique_integrity_error(
    db_session: Session,
) -> None:
    user = user_service.create_user(db_session, email="lucas@example.com", name="Lucas")
    organization = organization_service.create_organization(db_session, "Acme")

    with pytest.raises(IntegrityError) as error:
        membership_service.create_membership(
            db_session,
            organization_id=organization.id,
            user_id=user.id,
            role="invalid",
        )

    assert error.value.orig.sqlstate == "23514"


def test_list_organization_memberships(client: TestClient) -> None:
    organization = create_organization(client)
    users = [
        create_user(client, email="lucas@example.com", name="Lucas"),
        create_user(client, email="ana@example.com", name="Ana"),
    ]
    memberships = [
        create_membership(client, organization["id"], user["id"]) for user in users
    ]

    response = client.get(f"/organizations/{organization['id']}/memberships")

    assert response.status_code == 200
    assert {item["id"] for item in response.json()} == {
        membership["id"] for membership in memberships
    }


def test_list_user_memberships(client: TestClient) -> None:
    user = create_user(client)
    organizations = [
        create_organization(client, "Acme"),
        create_organization(client, "Globex"),
    ]
    memberships = [
        create_membership(client, organization["id"], user["id"])
        for organization in organizations
    ]

    response = client.get(f"/users/{user['id']}/memberships")

    assert response.status_code == 200
    assert {item["id"] for item in response.json()} == {
        membership["id"] for membership in memberships
    }


def test_update_membership_role(client: TestClient) -> None:
    user = create_user(client)
    organization = create_organization(client)
    membership = create_membership(client, organization["id"], user["id"])

    response = client.patch(
        f"/organizations/{organization['id']}/memberships/{membership['id']}",
        json={"role": "admin"},
    )

    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_update_membership_rejects_invalid_role(client: TestClient) -> None:
    user = create_user(client)
    organization = create_organization(client)
    membership = create_membership(client, organization["id"], user["id"])

    response = client.patch(
        f"/organizations/{organization['id']}/memberships/{membership['id']}",
        json={"role": "superadmin"},
    )

    assert response.status_code == 422


def test_update_missing_membership_returns_not_found(client: TestClient) -> None:
    organization = create_organization(client)

    response = client.patch(
        f"/organizations/{organization['id']}/memberships/{uuid4()}",
        json={"role": "member"},
    )

    assert response.status_code == 404


def test_update_membership_cannot_use_different_organization(client: TestClient) -> None:
    user = create_user(client)
    organization = create_organization(client, "Acme")
    other_organization = create_organization(client, "Globex")
    membership = create_membership(client, organization["id"], user["id"])

    response = client.patch(
        f"/organizations/{other_organization['id']}/memberships/{membership['id']}",
        json={"role": "admin"},
    )

    assert response.status_code == 404
