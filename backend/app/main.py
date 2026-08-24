from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.core.access_control.router import router as access_control_router
from app.core.auth.router import router as auth_router
from app.core.organization_invitations.router import router as invitations_router
from app.core.organization_memberships.router import router as memberships_router
from app.core.organization_modules.router import router as organization_modules_router
from app.core.organizations.router import router as organizations_router
from app.core.platform_admin.router import router as platform_admin_router
from app.core.users.router import router as users_router
from app.modules import registry as module_registry  # noqa: F401

settings = get_settings()
app = FastAPI(title="Auron")
if settings.google_authentication_configured:
    assert settings.oauth_state_secret is not None
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.oauth_state_secret.get_secret_value(),
        session_cookie="oauth_state",
        max_age=600,
        path="/auth/google",
        same_site="lax",
        https_only=settings.auth_session_cookie_secure,
    )
app.include_router(auth_router)
app.include_router(platform_admin_router)
app.include_router(invitations_router)
app.include_router(organizations_router)
app.include_router(organization_modules_router)
app.include_router(access_control_router)
app.include_router(users_router)
app.include_router(memberships_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
