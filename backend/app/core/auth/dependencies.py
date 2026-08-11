from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.auth import service
from app.core.users.model import User
from app.database import get_session

AUTH_SESSION_COOKIE_NAME = "platform_session"


def set_auth_session_cookie(response: Response, raw_session_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        AUTH_SESSION_COOKIE_NAME,
        raw_session_token,
        max_age=settings.auth_session_ttl_hours * 60 * 60,
        path="/",
        secure=settings.auth_session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def clear_auth_session_cookie(response: Response) -> None:
    response.delete_cookie(
        AUTH_SESSION_COOKIE_NAME,
        path="/",
        secure=get_settings().auth_session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


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
