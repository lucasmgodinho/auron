from typing import Annotated

from authlib.integrations.base_client import OAuthError
from authlib.oidc.core import UserInfo
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from httpx import HTTPError
from joserfc.errors import JoseError
from sqlalchemy.orm import Session
from starlette.responses import RedirectResponse

from app.config import get_settings
from app.core.auth import google, service
from app.core.auth.dependencies import (
    AUTH_SESSION_COOKIE_NAME,
    clear_auth_session_cookie,
    get_current_user,
    set_auth_session_cookie,
)
from app.core.users.model import User
from app.core.users.schemas import UserResponse
from app.database import get_session

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/google/login")
async def google_login(request: Request) -> Response:
    return await google.google_oauth_client.authorize_redirect(
        request,
        str(get_settings().google_redirect_uri),
    )


@router.get("/google/callback")
async def google_callback(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    try:
        token = await google.google_oauth_client.authorize_access_token(request)
    except (HTTPError, JoseError, OAuthError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google authentication failed",
        ) from error

    claims = token.get("userinfo")
    if not isinstance(claims, UserInfo):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google authentication failed",
        )

    try:
        user = google.resolve_google_user(session, claims)
    except google.GoogleAuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google authentication failed",
        ) from error

    _, raw_session_token = service.create_auth_session(session, user.id)
    response = RedirectResponse(
        str(get_settings().auth_login_success_redirect_url),
        status_code=status.HTTP_302_FOUND,
    )
    set_auth_session_cookie(response, raw_session_token)
    return response


@router.get("/me", response_model=UserResponse)
def get_authenticated_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    return current_user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
    raw_session_token: Annotated[
        str | None, Cookie(alias=AUTH_SESSION_COOKIE_NAME)
    ] = None,
) -> None:
    if raw_session_token is not None:
        service.revoke_session(session, raw_session_token)
    clear_auth_session_cookie(response)
