from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.organizations.model import Organization
from app.database import get_session
from app.main import app

settings = get_settings()
test_database_url = settings.test_database_url

if not test_database_url:
    raise RuntimeError(
        "TEST_DATABASE_URL must be explicitly configured for database integration tests"
    )


def _database_target(database_url: str) -> tuple[str, int, str | None]:
    url = make_url(database_url)
    host = (url.host or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        host = "localhost"
    return host, url.port or 5432, url.database


if _database_target(test_database_url) == _database_target(settings.database_url):
    raise RuntimeError("TEST_DATABASE_URL must point to a different database than DATABASE_URL")

test_engine = create_engine(test_database_url)


@pytest.fixture
def db_session() -> Iterator[Session]:
    connection = test_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    session.execute(delete(Organization))
    session.flush()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    def override_get_session() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def create_organization(client: TestClient, name: str) -> dict[str, object]:
    response = client.post("/organizations", json={"name": name})
    assert response.status_code == 201
    return response.json()


def test_create_organization(client: TestClient) -> None:
    organization = create_organization(client, "Acme")

    assert organization["name"] == "Acme"
    assert organization["id"]
    assert organization["created_at"]
    assert organization["updated_at"]


def test_create_organization_normalizes_surrounding_whitespace(client: TestClient) -> None:
    organization = create_organization(client, "  Acme  ")

    assert organization["name"] == "Acme"


def test_create_organization_rejects_empty_name(client: TestClient) -> None:
    response = client.post("/organizations", json={"name": ""})

    assert response.status_code == 422


def test_create_organization_rejects_whitespace_only_name(client: TestClient) -> None:
    response = client.post("/organizations", json={"name": "   "})

    assert response.status_code == 422


def test_get_organization(client: TestClient) -> None:
    created = create_organization(client, "Acme")

    response = client.get(f"/organizations/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_missing_organization_returns_not_found(client: TestClient) -> None:
    response = client.get(f"/organizations/{uuid4()}")

    assert response.status_code == 404


def test_list_organizations(client: TestClient) -> None:
    created = [
        create_organization(client, "Acme"),
        create_organization(client, "Globex"),
    ]

    response = client.get("/organizations")

    assert response.status_code == 200
    assert {organization["id"] for organization in response.json()} == {
        organization["id"] for organization in created
    }


def test_list_organizations_paginates(client: TestClient) -> None:
    for name in ("Acme", "Globex", "Initech"):
        create_organization(client, name)

    all_organizations = client.get("/organizations").json()
    response = client.get("/organizations", params={"limit": 1, "offset": 1})

    assert response.status_code == 200
    assert response.json() == all_organizations[1:2]


def test_update_organization_name(client: TestClient) -> None:
    created = create_organization(client, "Acme")

    response = client.patch(
        f"/organizations/{created['id']}", json={"name": "  Acme Holdings  "}
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Acme Holdings"
    assert client.get(f"/organizations/{created['id']}").json()["name"] == "Acme Holdings"


def test_update_missing_organization_returns_not_found(client: TestClient) -> None:
    response = client.patch(f"/organizations/{uuid4()}", json={"name": "Acme"})

    assert response.status_code == 404
