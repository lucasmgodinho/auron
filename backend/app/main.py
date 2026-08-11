from fastapi import FastAPI

from app.core.organization_memberships.router import router as memberships_router
from app.core.organizations.router import router as organizations_router
from app.core.users.router import router as users_router

app = FastAPI(title="Business Platform")
app.include_router(organizations_router)
app.include_router(users_router)
app.include_router(memberships_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
