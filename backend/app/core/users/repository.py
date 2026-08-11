from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.users.model import User


def create_user(session: Session, email: str, name: str) -> User:
    user = User(email=email, name=name)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def get_user(session: Session, user_id: UUID) -> User | None:
    return session.get(User, user_id)


def list_users(session: Session, limit: int, offset: int) -> list[User]:
    statement = select(User).order_by(User.created_at, User.id).limit(limit).offset(offset)
    return list(session.scalars(statement))


def update_user(
    session: Session,
    user: User,
    *,
    email: str | None,
    name: str | None,
) -> User:
    if email is not None:
        user.email = email
    if name is not None:
        user.name = name
    session.commit()
    session.refresh(user)
    return user
