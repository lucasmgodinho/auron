warning: in the working copy of 'AGENTS.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'backend/app/database.py', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'backend/app/main.py', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'backend/migrations/env.py', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'docs/ARCHITECTURE.md', LF will be replaced by CRLF the next time Git touches it
[1mdiff --git a/AGENTS.md b/AGENTS.md[m
[1mindex f5f48db..ca7201b 100644[m
[1m--- a/AGENTS.md[m
[1m+++ b/AGENTS.md[m
[36m@@ -9,7 +9,14 @@[m
 - Every feature needs appropriate tests.[m
 - Apply all database schema changes through Alembic migrations.[m
 - Use `Decimal`, never `float`, for future monetary values.[m
[31m-- Future tenant-owned data must be scoped to an organization; multi-tenancy is not part of the current foundation.[m
 - Do not modify unrelated parts of the project.[m
 - Run relevant validation commands before declaring work complete.[m
 [m
[32m+[m[32m## SaaS boundaries and multi-tenancy[m
[32m+[m
[32m+[m[32m- `app/core` contains required SaaS platform capabilities; `app/modules` contains optional business modules.[m
[32m+[m[32m- Organization is the tenant root. Classify data as global/platform data or tenant-owned data.[m
[32m+[m[32m- Tenant-owned entities must include `organization_id`, and their queries must always be scoped by it.[m
[32m+[m[32m- Never trust an `organization_id` supplied by a client as authorization context.[m
[32m+[m[32m- Include `organization_id` in tenant-specific uniqueness constraints when appropriate.[m
[32m+[m[32m- Cover cross-tenant isolation with automated tests.[m
[1mdiff --git a/backend/app/database.py b/backend/app/database.py[m
[1mindex ba4721c..b6b0e72 100644[m
[1m--- a/backend/app/database.py[m
[1m+++ b/backend/app/database.py[m
[36m@@ -1,5 +1,7 @@[m
[32m+[m[32mfrom collections.abc import Iterator[m
[32m+[m
 from sqlalchemy import create_engine[m
[31m-from sqlalchemy.orm import DeclarativeBase, sessionmaker[m
[32m+[m[32mfrom sqlalchemy.orm import DeclarativeBase, Session, sessionmaker[m
 [m
 from app.config import get_settings[m
 [m
[36m@@ -11,3 +13,7 @@[m [mclass Base(DeclarativeBase):[m
 engine = create_engine(get_settings().database_url)[m
 SessionLocal = sessionmaker(bind=engine)[m
 [m
[32m+[m
[32m+[m[32mdef get_session() -> Iterator[Session]:[m
[32m+[m[32m    with SessionLocal() as session:[m
[32m+[m[32m        yield session[m
[1mdiff --git a/backend/app/main.py b/backend/app/main.py[m
[1mindex 0704838..a81e036 100644[m
[1m--- a/backend/app/main.py[m
[1m+++ b/backend/app/main.py[m
[36m@@ -1,9 +1,11 @@[m
 from fastapi import FastAPI[m
 [m
[32m+[m[32mfrom app.core.organizations.router import router as organizations_router[m
[32m+[m
 app = FastAPI(title="Business Platform")[m
[32m+[m[32mapp.include_router(organizations_router)[m
 [m
 [m
 @app.get("/health")[m
 def health() -> dict[str, str]:[m
     return {"status": "ok"}[m
[31m-[m
[1mdiff --git a/backend/migrations/env.py b/backend/migrations/env.py[m
[1mindex d358340..ffaa6ff 100644[m
[1m--- a/backend/migrations/env.py[m
[1m+++ b/backend/migrations/env.py[m
[36m@@ -4,6 +4,7 @@[m [mfrom alembic import context[m
 from sqlalchemy import engine_from_config, pool[m
 [m
 from app.config import get_settings[m
[32m+[m[32mfrom app.core.organizations import model as organization_model  # noqa: F401[m
 from app.database import Base[m
 [m
 config = context.config[m
[1mdiff --git a/docs/ARCHITECTURE.md b/docs/ARCHITECTURE.md[m
[1mindex ff38246..9c1a1a9 100644[m
[1m--- a/docs/ARCHITECTURE.md[m
[1m+++ b/docs/ARCHITECTURE.md[m
[36m@@ -4,7 +4,12 @@[m [mThe platform starts as a modular monolith: one deployable backend is the simples[m
 [m
 The FastAPI backend owns application logic and persistence. The React frontend is a separate TypeScript application that communicates with the backend over HTTP. PostgreSQL is the primary database and SQLAlchemy plus Alembic manage access and schema evolution.[m
 [m
[32m+[m[32m## SaaS Core and business modules[m
[32m+[m
[32m+[m[32mRequired platform capabilities live under `app/core`, including organizations and, when implemented, users, authentication, tenancy, and module management. Organization is the tenant root.[m
[32m+[m
[32m+[m[32mOptional business capabilities such as fleet, clinic, documents, workflows, and analytics live under `app/modules`. Tenant-owned entities remain inside their business module, reference `organization_id`, and scope data access to that organization.[m
[32m+[m
 For local development, only PostgreSQL runs in Docker Compose. Python and Node.js run directly on the host for fast feedback and straightforward debugging.[m
 [m
 Microservices, messaging, background-job infrastructure, and other scaling mechanisms are intentionally deferred until concrete product or operational needs justify them.[m
[31m-[m
