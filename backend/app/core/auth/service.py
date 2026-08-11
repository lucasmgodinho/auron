import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from psycopg.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.auth import repository
from app.core.auth.model import AuthIdentity, AuthSession
from app.core.users import service as user_service
from app.core.users.model import User


class AuthIdentityConflictError(Exception):
    pass


def _normalize_provider(provider: str) -> str:
    normalized_provider = provider.strip().lower()
    if not normalized_provider or len(normalized_provider) > 50:
        raise ValueError("Provider must contain between 1 and 50 characters")
    return normalized_provider


def _normalize_provider_subject(provider_subject: str) -> str:
    normalized_subject = provider_subject.strip()
    if not normalized_subject or len(normalized_subject) > 255:
        raise ValueError("Provider subject must contain between 1 and 255 characters")
    return normalized_subject


def _is_identity_unique_violation(error: IntegrityError) -> bool:
    return (
        isinstance(error.orig, UniqueViolation)
        and error.orig.diag.constraint_name == "uq_auth_identities_provider_subject"
    )


def _hash_session_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def find_user_by_external_identity(
    session: Session, *, provider: str, provider_subject: str
) -> User | None:
    return repository.find_user_by_identity(
        session,
        _normalize_provider(provider),
        _normalize_provider_subject(provider_subject),
    )


def link_identity(
    session: Session,
    *,
    user_id: UUID,
    provider: str,
    provider_subject: str,
) -> AuthIdentity:
    normalized_provider = _normalize_provider(provider)
    normalized_subject = _normalize_provider_subject(provider_subject)
    user_service.get_user(session, user_id)

    try:
        return repository.create_identity(
            session,
            user_id=user_id,
            provider=normalized_provider,
            provider_subject=normalized_subject,
        )
    except IntegrityError as error:
        session.rollback()
        if _is_identity_unique_violation(error):
            raise AuthIdentityConflictError from error
        raise


def create_auth_session(session: Session, user_id: UUID) -> tuple[AuthSession, str]:
    user_service.get_user(session, user_id)
    raw_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(
        hours=get_settings().auth_session_ttl_hours
    )
    auth_session = repository.create_auth_session(
        session,
        user_id=user_id,
        token_hash=_hash_session_token(raw_token),
        expires_at=expires_at,
    )
    return auth_session, raw_token


def resolve_user_from_session_token(session: Session, raw_token: str) -> User | None:
    auth_session = repository.get_auth_session_by_token_hash(
        session, _hash_session_token(raw_token)
    )
    if (
        auth_session is None
        or auth_session.revoked_at is not None
        or auth_session.expires_at <= datetime.now(UTC)
    ):
        return None
    return user_service.get_user(session, auth_session.user_id)


def revoke_session(session: Session, raw_token: str) -> bool:
    auth_session = repository.get_auth_session_by_token_hash(
        session, _hash_session_token(raw_token)
    )
    if auth_session is None:
        return False
    repository.revoke_auth_session(session, auth_session, datetime.now(UTC))
    return True
