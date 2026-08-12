from uuid import UUID

from psycopg.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.users import repository
from app.core.users.model import User


class UserNotFoundError(Exception):
    pass


class UserEmailConflictError(Exception):
    pass


class UserAccessDeniedError(Exception):
    pass


def _is_user_email_unique_violation(error: IntegrityError) -> bool:
    return (
        isinstance(error.orig, UniqueViolation)
        and error.orig.diag.constraint_name == "uq_users_email"
    )


def _normalize_name(name: str) -> str:
    normalized_name = name.strip()
    if not normalized_name or len(normalized_name) > 255:
        raise ValueError("User name must contain between 1 and 255 characters")
    return normalized_name


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def create_user(session: Session, email: str, name: str) -> User:
    try:
        return repository.create_user(
            session,
            email=_normalize_email(email),
            name=_normalize_name(name),
        )
    except IntegrityError as error:
        session.rollback()
        if _is_user_email_unique_violation(error):
            raise UserEmailConflictError from error
        raise


def get_user(session: Session, user_id: UUID) -> User:
    user = repository.get_user(session, user_id)
    if user is None:
        raise UserNotFoundError
    return user


def get_own_user(session: Session, user_id: UUID, current_user_id: UUID) -> User:
    if user_id != current_user_id:
        raise UserAccessDeniedError
    return get_user(session, user_id)


def update_user(
    session: Session,
    user_id: UUID,
    *,
    name: str,
) -> User:
    user = get_user(session, user_id)
    return repository.update_user_name(session, user, _normalize_name(name))


def update_own_user(
    session: Session,
    user_id: UUID,
    current_user_id: UUID,
    *,
    name: str,
) -> User:
    if user_id != current_user_id:
        raise UserAccessDeniedError
    return update_user(session, user_id, name=name)
