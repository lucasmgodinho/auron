from functools import lru_cache

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://platform:platform@localhost:5432/platform"
    test_database_url: str | None = None
    auth_session_ttl_hours: int = Field(default=168, gt=0)
    auth_session_cookie_secure: bool = False
    google_client_id: str | None = Field(default=None, min_length=1)
    google_client_secret: SecretStr | None = Field(default=None, min_length=1)
    google_redirect_uri: AnyHttpUrl | None = None
    oauth_state_secret: SecretStr | None = Field(default=None, min_length=32)
    auth_login_success_redirect_url: AnyHttpUrl | None = None

    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
