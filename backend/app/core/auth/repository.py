from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.auth.model import AuthIdentity, AuthSession
from app.core.users.model import User


def find_user_by_identity(
    session: Session, provider: str, provider_subject: str
) -> User | None:
    statement = (
        select(User)
        .join(AuthIdentity, AuthIdentity.user_id == User.id)
        .where(
            AuthIdentity.provider == provider,
            AuthIdentity.provider_subject == provider_subject,
        )
    )
    return session.scalar(statement)


def find_user_by_email(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(User.email == email))


def create_user_with_identity(
    session: Session,
    *,
    email: str,
    name: str,
    provider: str,
    provider_subject: str,
    email_verified_at: datetime,
) -> User:
    user = User(email=email, name=name, email_verified_at=email_verified_at)
    session.add(user)
    session.flush()
    session.add(
        AuthIdentity(
            user_id=user.id,
            provider=provider,
            provider_subject=provider_subject,
        )
    )
    session.commit()
    session.refresh(user)
    return user


def create_identity(
    session: Session,
    *,
    user_id: UUID,
    provider: str,
    provider_subject: str,
) -> AuthIdentity:
    identity = AuthIdentity(
        user_id=user_id,
        provider=provider,
        provider_subject=provider_subject,
    )
    session.add(identity)
    session.commit()
    session.refresh(identity)
    return identity


def create_auth_session(
    session: Session,
    *,
    user_id: UUID,
    token_hash: str,
    expires_at: datetime,
) -> AuthSession:
    auth_session = AuthSession(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    session.add(auth_session)
    session.flush()
    return auth_session


def get_auth_session_by_token_hash(
    session: Session, token_hash: str
) -> AuthSession | None:
    statement = select(AuthSession).where(AuthSession.token_hash == token_hash)
    return session.scalar(statement)


def revoke_auth_session(
    session: Session, auth_session: AuthSession, revoked_at: datetime
) -> None:
    auth_session.revoked_at = revoked_at
    session.commit()


def revoke_other_active_auth_sessions(
    session: Session,
    *,
    user_id: UUID,
    current_auth_session_id: UUID,
    revoked_at: datetime,
) -> None:
    session.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.id != current_auth_session_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > revoked_at,
        )
        .values(revoked_at=revoked_at)
    )
