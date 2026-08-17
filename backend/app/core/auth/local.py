import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from psycopg.errors import UniqueViolation
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.auth import repository as auth_repository
from app.core.auth import service as auth_service
from app.core.auth.model import AuthIdentity, AuthSession, EmailVerification, LocalCredential
from app.core.users.model import User

_PASSWORD_HASHER = PasswordHasher()
_DUMMY_PASSWORD_HASH = _PASSWORD_HASHER.hash("auron-dummy-password-verification")


class InvalidCredentialsError(Exception):
    pass


class InvalidVerificationError(Exception):
    pass


class ExpiredVerificationError(Exception):
    pass


class CompletedVerificationError(Exception):
    pass


class PasswordNotConfiguredError(Exception):
    pass


class IncorrectCurrentPasswordError(Exception):
    pass


class PasswordReuseError(Exception):
    pass


class PasswordAlreadyConfiguredError(Exception):
    pass


class EmailNotVerifiedError(Exception):
    pass


@dataclass(frozen=True)
class VerificationDelivery:
    recipient: str
    raw_token: str


@dataclass(frozen=True)
class AuthenticationMethods:
    password: bool
    google: bool


def hash_verification_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def hash_password(password: str) -> str:
    return _PASSWORD_HASHER.hash(password)


def _verify_password(password_hash: str, password: str) -> bool:
    try:
        return _PASSWORD_HASHER.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def _find_user_for_update(session: Session, email: str) -> User | None:
    return session.scalar(
        select(User).where(User.email == email).with_for_update()
    )


def _find_credential(session: Session, user_id: object) -> LocalCredential | None:
    return session.scalar(
        select(LocalCredential).where(LocalCredential.user_id == user_id)
    )


def _find_credential_for_update(
    session: Session, user_id: object
) -> LocalCredential | None:
    return session.scalar(
        select(LocalCredential)
        .where(LocalCredential.user_id == user_id)
        .with_for_update()
    )


def _find_verification_for_user(
    session: Session, user_id: object
) -> EmailVerification | None:
    return session.scalar(
        select(EmailVerification)
        .where(EmailVerification.user_id == user_id)
        .with_for_update()
    )


def _rotate_verification(
    verification: EmailVerification | None,
    *,
    user_id: object,
    now: datetime,
) -> tuple[EmailVerification, str]:
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_verification_token(raw_token)
    expires_at = now + timedelta(hours=get_settings().email_verification_ttl_hours)
    if verification is None:
        verification = EmailVerification(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            last_sent_at=now,
        )
    else:
        verification.token_hash = token_hash
        verification.expires_at = expires_at
        verification.last_sent_at = now
        verification.used_at = None
    return verification, raw_token


def register(session: Session, *, email: str, name: str) -> VerificationDelivery | None:
    for attempt in range(2):
        try:
            user = _find_user_for_update(session, email)
            if user is None:
                user = User(email=email, name=name)
                session.add(user)
                session.flush()

            if _find_credential(session, user.id) is not None:
                session.commit()
                return None

            now = datetime.now(UTC)
            verification = _find_verification_for_user(session, user.id)
            cooldown = timedelta(
                seconds=get_settings().email_verification_resend_cooldown_seconds
            )
            if verification is not None and verification.last_sent_at + cooldown > now:
                session.commit()
                return None

            verification, raw_token = _rotate_verification(
                verification, user_id=user.id, now=now
            )
            recipient = user.email
            session.add(verification)
            session.commit()
            return VerificationDelivery(recipient=recipient, raw_token=raw_token)
        except IntegrityError as error:
            session.rollback()
            is_email_race = (
                isinstance(error.orig, UniqueViolation)
                and error.orig.diag.constraint_name == "uq_users_email"
            )
            if not is_email_race or attempt == 1:
                raise
    raise RuntimeError("Registration retry exhausted")


def resend_verification(session: Session, *, email: str) -> VerificationDelivery | None:
    try:
        user = _find_user_for_update(session, email)
        if user is None or _find_credential(session, user.id) is not None:
            session.commit()
            return None

        now = datetime.now(UTC)
        verification = _find_verification_for_user(session, user.id)
        cooldown = timedelta(
            seconds=get_settings().email_verification_resend_cooldown_seconds
        )
        if verification is not None and verification.last_sent_at + cooldown > now:
            session.commit()
            return None

        verification, raw_token = _rotate_verification(
            verification, user_id=user.id, now=now
        )
        recipient = user.email
        session.add(verification)
        session.commit()
        return VerificationDelivery(recipient=recipient, raw_token=raw_token)
    except Exception:
        session.rollback()
        raise


def get_authentication_methods(session: Session, user_id: UUID) -> AuthenticationMethods:
    password = session.scalar(
        select(LocalCredential.id).where(LocalCredential.user_id == user_id)
    ) is not None
    google = session.scalar(
        select(AuthIdentity.id).where(
            AuthIdentity.user_id == user_id,
            AuthIdentity.provider == "google",
        )
    ) is not None
    return AuthenticationMethods(password=password, google=google)


def change_password(
    session: Session,
    *,
    user_id: UUID,
    current_auth_session_id: UUID,
    current_password: str,
    new_password: str,
) -> None:
    try:
        credential = _find_credential_for_update(session, user_id)
        if credential is None:
            raise PasswordNotConfiguredError
        if not _verify_password(credential.password_hash, current_password):
            raise IncorrectCurrentPasswordError
        if _verify_password(credential.password_hash, new_password):
            raise PasswordReuseError

        credential.password_hash = hash_password(new_password)
        now = datetime.now(UTC)
        auth_repository.revoke_other_active_auth_sessions(
            session,
            user_id=user_id,
            current_auth_session_id=current_auth_session_id,
            revoked_at=now,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise


def start_password_enrollment(
    session: Session, *, user_id: UUID
) -> VerificationDelivery | None:
    try:
        user = session.scalar(
            select(User).where(User.id == user_id).with_for_update()
        )
        if user is None or user.email_verified_at is None:
            raise EmailNotVerifiedError
        if _find_credential(session, user.id) is not None:
            raise PasswordAlreadyConfiguredError

        now = datetime.now(UTC)
        verification = _find_verification_for_user(session, user.id)
        cooldown = timedelta(
            seconds=get_settings().email_verification_resend_cooldown_seconds
        )
        if verification is not None and verification.last_sent_at + cooldown > now:
            session.commit()
            return None

        verification, raw_token = _rotate_verification(
            verification, user_id=user.id, now=now
        )
        session.add(verification)
        recipient = user.email
        session.commit()
        return VerificationDelivery(recipient=recipient, raw_token=raw_token)
    except Exception:
        session.rollback()
        raise


def complete_verification(
    session: Session,
    *,
    raw_token: str,
    password: str,
    current_auth_session: AuthSession | None = None,
) -> tuple[User, str | None]:
    try:
        token_hash = hash_verification_token(raw_token)
        verification_candidate = session.scalar(
            select(EmailVerification).where(
                EmailVerification.token_hash == token_hash
            )
        )
        if verification_candidate is None:
            raise InvalidVerificationError

        user = session.scalar(
            select(User)
            .where(User.id == verification_candidate.user_id)
            .with_for_update()
        )
        if user is None:
            raise InvalidVerificationError
        if (
            current_auth_session is not None
            and current_auth_session.user_id != user.id
        ):
            raise InvalidVerificationError
        verification = session.scalar(
            select(EmailVerification)
            .where(EmailVerification.id == verification_candidate.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if verification is None or verification.token_hash != token_hash:
            raise InvalidVerificationError
        if verification.used_at is not None:
            raise CompletedVerificationError
        now = datetime.now(UTC)
        if verification.expires_at <= now:
            raise ExpiredVerificationError
        if _find_credential(session, user.id) is not None:
            raise CompletedVerificationError

        credential = LocalCredential(
            user_id=user.id,
            password_hash=hash_password(password),
        )
        user.email_verified_at = user.email_verified_at or now
        verification.used_at = now
        session.add(credential)
        raw_session_token = None
        if current_auth_session is None or current_auth_session.user_id != user.id:
            _, raw_session_token = auth_service.add_auth_session(session, user.id)
        session.commit()
        session.refresh(user)
        return user, raw_session_token
    except Exception:
        session.rollback()
        raise


def login(session: Session, *, email: str, password: str) -> tuple[User, str]:
    try:
        user = session.scalar(select(User).where(User.email == email))
        credential = _find_credential(session, user.id) if user is not None else None
        password_hash = credential.password_hash if credential is not None else _DUMMY_PASSWORD_HASH
        password_valid = _verify_password(password_hash, password)

        if (
            user is None
            or credential is None
            or user.email_verified_at is None
            or not password_valid
        ):
            raise InvalidCredentialsError

        if _PASSWORD_HASHER.check_needs_rehash(credential.password_hash):
            credential.password_hash = hash_password(password)
        _, raw_session_token = auth_service.add_auth_session(session, user.id)
        session.commit()
        session.refresh(user)
        return user, raw_session_token
    except Exception:
        session.rollback()
        raise
