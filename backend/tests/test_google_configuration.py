import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest
from pydantic import ValidationError

from app.config import Settings

GOOGLE_ENVIRONMENT_VARIABLES = (
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REDIRECT_URI",
    "OAUTH_STATE_SECRET",
    "AUTH_LOGIN_SUCCESS_REDIRECT_URL",
)

COMPLETE_GOOGLE_SETTINGS = {
    "google_client_id": "configured-client-id",
    "google_client_secret": "configured-client-secret",
    "google_redirect_uri": "http://127.0.0.1:8000/auth/google/callback",
    "oauth_state_secret": "configured-state-secret-with-32-characters",
    "auth_login_success_redirect_url": "http://127.0.0.1:5173/app",
}


def clear_google_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in GOOGLE_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(variable, raising=False)


def run_unconfigured_app(tmp_path: Path, environment_updates: dict[str, str]) -> None:
    environment = os.environ.copy()
    for variable in GOOGLE_ENVIRONMENT_VARIABLES:
        environment.pop(variable, None)
    environment.update(environment_updates)

    backend_root = Path(__file__).resolve().parents[1]
    existing_python_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(backend_root), existing_python_path) if part
    )
    script = dedent(
        """
        from fastapi.testclient import TestClient
        from starlette.middleware.sessions import SessionMiddleware

        from app.core.auth import google
        from app.main import app

        assert google.google_oauth_client is None
        assert all(middleware.cls is not SessionMiddleware for middleware in app.user_middleware)

        route_paths = set(app.openapi()["paths"])
        assert "/organizations" in route_paths
        assert "/users" in route_paths
        assert "/organizations/{organization_id}/memberships" in route_paths

        with TestClient(app) as client:
            health_response = client.get("/health")
            me_response = client.get("/auth/me")
            logout_response = client.post("/auth/logout")
            login_response = client.get("/auth/google/login")
            callback_response = client.get("/auth/google/callback")

        assert health_response.status_code == 200
        assert health_response.json() == {"status": "ok"}
        assert me_response.status_code == 401
        assert me_response.json() == {"detail": "Authentication required"}
        assert logout_response.status_code == 401
        assert login_response.status_code == 503
        assert callback_response.status_code == 503
        expected_error = {"detail": "Google authentication is not configured."}
        assert login_response.json() == expected_error
        assert callback_response.json() == expected_error
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_settings_load_without_google_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_google_environment(monkeypatch)

    settings = Settings(_env_file=None)

    assert settings.google_client_id is None
    assert settings.google_client_secret is None
    assert settings.google_redirect_uri is None
    assert settings.oauth_state_secret is None
    assert settings.auth_login_success_redirect_url is None
    assert settings.google_authentication_configured is False


@pytest.mark.parametrize("missing_setting", COMPLETE_GOOGLE_SETTINGS)
def test_incomplete_google_configuration_does_not_enable_authentication(
    monkeypatch: pytest.MonkeyPatch,
    missing_setting: str,
) -> None:
    clear_google_environment(monkeypatch)
    incomplete_settings = COMPLETE_GOOGLE_SETTINGS | {missing_setting: None}

    settings = Settings(_env_file=None, **incomplete_settings)

    assert settings.google_authentication_configured is False


def test_complete_google_configuration_enables_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_google_environment(monkeypatch)

    settings = Settings(_env_file=None, **COMPLETE_GOOGLE_SETTINGS)

    assert settings.google_authentication_configured is True


def test_present_google_configuration_still_validates_security_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_google_environment(monkeypatch)
    invalid_settings = COMPLETE_GOOGLE_SETTINGS | {"oauth_state_secret": "too-short"}

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **invalid_settings)


def test_application_starts_without_google_configuration(tmp_path: Path) -> None:
    run_unconfigured_app(tmp_path, {})


def test_application_starts_with_incomplete_google_configuration(
    tmp_path: Path,
) -> None:
    run_unconfigured_app(
        tmp_path,
        {
            "GOOGLE_CLIENT_ID": "partial-client-id",
            "GOOGLE_CLIENT_SECRET": "partial-client-secret",
            "GOOGLE_REDIRECT_URI": "http://127.0.0.1:8000/auth/google/callback",
            "AUTH_LOGIN_SUCCESS_REDIRECT_URL": "http://127.0.0.1:5173/app",
        },
    )
