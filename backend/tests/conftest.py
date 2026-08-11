import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

os.environ.setdefault("GOOGLE_CLIENT_ID", "test-google-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-google-client-secret")
os.environ.setdefault("GOOGLE_REDIRECT_URI", "http://testserver/auth/google/callback")
os.environ.setdefault("OAUTH_STATE_SECRET", "test-only-oauth-state-secret-with-32-characters")
os.environ.setdefault("AUTH_LOGIN_SUCCESS_REDIRECT_URL", "http://frontend.test/app")

from app.config import get_settings
from app.core.auth.model import AuthIdentity, AuthSession
from app.core.organization_memberships.model import OrganizationMembership
from app.core.organizations.model import Organization
from app.core.users.model import User
from app.database import get_session
from app.main import app


def _database_target(database_url: str) -> tuple[str, int, str | None]:
    url = make_url(database_url)
    host = (url.host or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        host = "localhost"
    return host, url.port or 5432, url.database


@pytest.fixture(scope="session")
def test_engine() -> Iterator[Engine]:
    settings = get_settings()
    test_database_url = settings.test_database_url

    if not test_database_url:
        raise RuntimeError(
            "TEST_DATABASE_URL must be explicitly configured for database integration tests"
        )
    if _database_target(test_database_url) == _database_target(settings.database_url):
        raise RuntimeError(
            "TEST_DATABASE_URL must point to a different database than DATABASE_URL"
        )

    engine = create_engine(test_database_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session(test_engine: Engine) -> Iterator[Session]:
    connection = test_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    try:
        session.execute(delete(AuthSession))
        session.execute(delete(AuthIdentity))
        session.execute(delete(OrganizationMembership))
        session.execute(delete(User))
        session.execute(delete(Organization))
        session.flush()
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
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_session, None)
