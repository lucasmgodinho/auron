# Auron

Auron is a modular B2B SaaS platform. The FastAPI backend and React frontend run directly on the host; Docker Compose runs PostgreSQL only.

## Prerequisites

- Python 3.14
- Node.js 24 and npm 11
- Docker with Docker Compose

This foundation was validated with Python 3.14.7, Node.js 24.19.0, npm 11.17.0, Docker 29.6.2, and Docker Compose 5.3.1.

Copy `.env.example` to `.env` for local development. `POSTGRES_*` variables configure the Docker PostgreSQL container, while `DATABASE_URL` configures the backend; keep them consistent when changing database settings. `TEST_DATABASE_URL` must explicitly identify a separate test database. The checked-in values are intended only for local development.

Use `127.0.0.1` consistently for both local web servers. Authentication cookies are host-scoped,
so mixing `localhost` and `127.0.0.1` can make a valid browser session appear unauthenticated.

## Backend setup

From PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
```

Start PostgreSQL from the repository root:

```powershell
docker compose up -d postgres
```

Create the separate test database once, using the local defaults:

```powershell
docker compose exec postgres createdb -U platform platform_test
```

Run migrations and start the API from `backend/`:

```powershell
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\uvicorn.exe app.main:app --reload
```

Apply migrations to the test database from `backend/`, then restore normal configuration from `.env`:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://platform:platform@127.0.0.1:5432/platform_test"
.\.venv\Scripts\alembic.exe upgrade head
Remove-Item Env:DATABASE_URL
```

The API is available at `http://127.0.0.1:8000`; `GET /health` returns its health status.

Create a migration after changing SQLAlchemy metadata with:

```powershell
.\.venv\Scripts\alembic.exe revision --autogenerate -m "describe change"
```

Run backend checks from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
```

Integration tests refuse to run if `TEST_DATABASE_URL` is missing or points to the same database as `DATABASE_URL`.

Authentication uses opaque server-side sessions stored in PostgreSQL. Session cookies are
HttpOnly and SameSite=Lax. Set `AUTH_SESSION_COOKIE_SECURE=true` in HTTPS production
environments; `AUTH_SESSION_TTL_HOURS` controls the session lifetime and defaults to seven days.

Google authentication is optional for local core development. Without its configuration, the core
API starts normally and the Google login endpoints return 503. To enable Google sign-in, configure
the OAuth consent screen, create a Google OAuth web client, and register
`http://127.0.0.1:8000/auth/google/callback` as its exact local authorized redirect URI. Then
uncomment and configure all five Google OIDC values in `.env`.
`GOOGLE_REDIRECT_URI` is the backend callback registered with Google, while
`AUTH_LOGIN_SUCCESS_REDIRECT_URL` is the trusted frontend destination after a successful login.
In production, use HTTPS URLs, a strong independently generated `OAUTH_STATE_SECRET`, and
`AUTH_SESSION_COOKIE_SECURE=true`.

Start sign-in at `GET /auth/google/login`. The callback is handled only at
`GET /auth/google/callback`; on success it sets the existing `platform_session` cookie and
redirects to `AUTH_LOGIN_SUCCESS_REDIRECT_URL`. The flow requests only `openid`, `email`, and
`profile`; Google access and ID tokens are not stored.

## Platform Admin bootstrap

Platform Admin is global Auron access and is independent from tenant access through
OrganizationMembership. To bootstrap an operator:

1. Sign in to Auron through Google once so the existing authentication flow creates the User.
2. From `backend/`, grant that existing User Platform Admin access:

   ```powershell
   .\.venv\Scripts\python.exe -m app.scripts.grant_platform_admin --email operator@example.com
   ```

3. Open `http://127.0.0.1:5173/admin` and create an Organization with one or more initial
   invitation emails.

The grant command is idempotent, does not create Users, and does not create Organization
memberships. Platform Admin provisioning creates the Organization and its normalized email
invitations atomically. An invited User later authenticates with the same verified email and
accepts the invitation; the current schema assigns the compatibility role `member`. If that User
already has membership, acceptance marks the invitation accepted without changing or duplicating
the membership. Platform Admin V1 does not manage modules, Organization roles, groups, or
permissions.

## Frontend setup

From a second terminal:

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

The Vite development server is available at `http://127.0.0.1:5173`. It proxies relative
`/auth/*` requests to the backend at `http://127.0.0.1:8000`, so no frontend secrets or local CORS
configuration are needed.

Run frontend checks and a production build from `frontend/`:

```powershell
npm.cmd run lint
npm.cmd run build
```

## Manual Google login validation

With `.env` configured so `GOOGLE_REDIRECT_URI` is
`http://127.0.0.1:8000/auth/google/callback` and `AUTH_LOGIN_SUCCESS_REDIRECT_URL` is
`http://127.0.0.1:5173/app`:

1. Start PostgreSQL, then start the backend and frontend using the commands above.
2. Open `http://127.0.0.1:5173/login` and select **Continue with Google**.
3. Complete authentication at Google and confirm the browser returns to `/app`.
4. Confirm the User name and email appear, then refresh `/app` and verify the session remains.
5. Select **Log out** and confirm the browser returns to `/login`.
6. Confirm `/auth/me` now returns 401 and visiting `/app` redirects to `/login`.

This requires operator-owned Google credentials and an authorized consent-screen user. Automated
tests and builds do not make real requests to Google.

To stop PostgreSQL, run `docker compose down` from the repository root. The named volume keeps local database data between runs.
