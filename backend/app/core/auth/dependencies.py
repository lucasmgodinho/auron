from dataclasses import dataclass
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.auth import service
from app.core.auth.model import AuthSession
from app.core.users.model import User
from app.database import get_session

AUTH_SESSION_COOKIE_NAME = "platform_session"


@dataclass(frozen=True)
class CurrentAuthentication:
    user: User
    auth_session: AuthSession


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


def get_current_authentication(
    session: Annotated[Session, Depends(get_session)],
    raw_session_token: Annotated[
        str | None, Cookie(alias=AUTH_SESSION_COOKIE_NAME)
    ] = None,
) -> CurrentAuthentication:
    auth_session = None
    if raw_session_token:
        auth_session = service.resolve_auth_session_from_session_token(
            session, raw_session_token
        )
    if auth_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    user = session.get(User, auth_session.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return CurrentAuthentication(user=user, auth_session=auth_session)


def get_current_user(
    authentication: Annotated[
        CurrentAuthentication, Depends(get_current_authentication)
    ],
) -> User:
    return authentication.user
