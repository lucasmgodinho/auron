from functools import lru_cache

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://platform:platform@localhost:5432/platform"
    test_database_url: str | None = None
    auth_session_ttl_hours: int = Field(default=168, gt=0)
    auth_session_cookie_secure: bool = False
    google_client_id: str = Field(min_length=1)
    google_client_secret: SecretStr
    google_redirect_uri: AnyHttpUrl
    oauth_state_secret: SecretStr = Field(min_length=32)
    auth_login_success_redirect_url: AnyHttpUrl

    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
