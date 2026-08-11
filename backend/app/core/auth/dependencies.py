from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import service
from app.core.users.model import User
from app.database import get_session

AUTH_SESSION_COOKIE_NAME = "platform_session"


def get_current_user(
    session: Annotated[Session, Depends(get_session)],
    raw_session_token: Annotated[
        str | None, Cookie(alias=AUTH_SESSION_COOKIE_NAME)
    ] = None,
) -> User:
    user = None
    if raw_session_token:
        user = service.resolve_user_from_session_token(session, raw_session_token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user
