from collections.abc import Mapping

from authlib.integrations.starlette_client import OAuth
from psycopg.errors import UniqueViolation
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.auth import repository, service
from app.core.users.model import User
from app.core.users.schemas import UserCreate

GOOGLE_PROVIDER = "google"
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"


class GoogleAuthenticationError(Exception):
    pass


settings = get_settings()
google_oauth_client = None
if settings.google_authentication_configured:
    assert settings.google_client_id is not None
    assert settings.google_client_secret is not None
    oauth = OAuth()
    oauth.register(
        name=GOOGLE_PROVIDER,
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret.get_secret_value(),
        server_metadata_url=GOOGLE_DISCOVERY_URL,
        client_kwargs={"scope": "openid email profile"},
    )
    google_oauth_client = oauth.create_client(GOOGLE_PROVIDER)


def _is_expected_first_login_conflict(error: IntegrityError) -> bool:
    return isinstance(error.orig, UniqueViolation) and error.orig.diag.constraint_name in {
        "uq_auth_identities_provider_subject",
        "uq_users_email",
    }


def _validated_claims(claims: Mapping[str, object]) -> tuple[str, UserCreate]:
    provider_subject = claims.get("sub")
    email = claims.get("email")
    if not isinstance(provider_subject, str) or not isinstance(email, str):
        raise GoogleAuthenticationError
    if claims.get("email_verified") is not True:
        raise GoogleAuthenticationError

    raw_name = claims.get("name")
    name = raw_name.strip() if isinstance(raw_name, str) else ""
    if not name or len(name) > 255:
        name = email.strip().lower()[:255]

    try:
        user_data = UserCreate(email=email, name=name)
        normalized_subject = provider_subject
        if (
            not normalized_subject
            or normalized_subject != normalized_subject.strip()
            or len(normalized_subject) > 255
        ):
            raise ValueError
    except (ValidationError, ValueError) as error:
        raise GoogleAuthenticationError from error
    return normalized_subject, user_data


def _link_identity_or_resolve(session: Session, *, user: User, provider_subject: str) -> User:
    try:
        service.link_identity(
            session,
            user_id=user.id,
            provider=GOOGLE_PROVIDER,
            provider_subject=provider_subject,
        )
        return user
    except service.AuthIdentityConflictError as error:
        resolved_user = service.find_user_by_external_identity(
            session,
            provider=GOOGLE_PROVIDER,
            provider_subject=provider_subject,
        )
        if resolved_user is None:
            raise GoogleAuthenticationError from error
        return resolved_user


def resolve_google_user(session: Session, claims: Mapping[str, object]) -> User:
    provider_subject, user_data = _validated_claims(claims)
    existing_user = service.find_user_by_external_identity(
        session,
        provider=GOOGLE_PROVIDER,
        provider_subject=provider_subject,
    )
    if existing_user is not None:
        return existing_user

    user = repository.find_user_by_email(session, str(user_data.email))
    if user is not None:
        return _link_identity_or_resolve(
            session,
            user=user,
            provider_subject=provider_subject,
        )

    try:
        return repository.create_user_with_identity(
            session,
            email=str(user_data.email),
            name=user_data.name,
            provider=GOOGLE_PROVIDER,
            provider_subject=provider_subject,
        )
    except IntegrityError as error:
        session.rollback()
        if not _is_expected_first_login_conflict(error):
            raise

        existing_user = service.find_user_by_external_identity(
            session,
            provider=GOOGLE_PROVIDER,
            provider_subject=provider_subject,
        )
        if existing_user is not None:
            return existing_user

        user = repository.find_user_by_email(session, str(user_data.email))
        if user is None:
            raise GoogleAuthenticationError from error
        return _link_identity_or_resolve(
            session,
            user=user,
            provider_subject=provider_subject,
        )
