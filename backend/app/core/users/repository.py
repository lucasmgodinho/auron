from uuid import UUID

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


def update_user_name(session: Session, user: User, name: str) -> User:
    user.name = name
    session.commit()
    session.refresh(user)
    return user
