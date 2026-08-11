from fastapi import FastAPI

from app.core.organizations.router import router as organizations_router

app = FastAPI(title="Business Platform")
app.include_router(organizations_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
