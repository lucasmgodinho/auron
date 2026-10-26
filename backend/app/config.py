from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, EmailStr, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPOSITORY_ROOT / ".env"


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://platform:platform@127.0.0.1:5432/platform"
    test_database_url: str | None = None
    auth_session_ttl_hours: int = Field(default=168, gt=0)
    auth_session_cookie_secure: bool = False
    google_client_id: str | None = Field(default=None, min_length=1)
    google_client_secret: SecretStr | None = Field(default=None, min_length=1)
    google_redirect_uri: AnyHttpUrl | None = None
    oauth_state_secret: SecretStr | None = Field(default=None, min_length=32)
    auth_login_success_redirect_url: AnyHttpUrl | None = None
    email_verification_ttl_hours: int = Field(default=24, gt=0)
    email_verification_resend_cooldown_seconds: int = Field(default=60, ge=0)
    smtp_host: str | None = Field(default=None, min_length=1)
    smtp_port: int = Field(default=587, gt=0, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True
    email_from: EmailStr | None = None
    frontend_base_url: AnyHttpUrl | None = None
    openai_api_key: SecretStr | None = Field(default=None, min_length=1)
    openai_base_url: AnyHttpUrl | None = None
    tavily_api_key: SecretStr | None = Field(default=None, min_length=1)
    ci_pricing_file: Path | None = None

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    @property
    def google_authentication_configured(self) -> bool:
        return all(
            value is not None
            for value in (
                self.google_client_id,
                self.google_client_secret,
                self.google_redirect_uri,
                self.oauth_state_secret,
                self.auth_login_success_redirect_url,
            )
        )

    @property
    def email_delivery_configured(self) -> bool:
        return all(
            value is not None
            for value in (self.smtp_host, self.email_from, self.frontend_base_url)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
