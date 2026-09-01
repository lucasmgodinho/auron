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

After installing the backend and frontend dependencies described below, start the complete local
development environment from the repository root with:

```powershell
.\dev.ps1
```

The command starts PostgreSQL and Mailpit, applies pending migrations, and runs both application
services in watch mode. Python changes automatically restart the FastAPI process. React, TypeScript,
and CSS changes are applied in the open browser through Vite Hot Module Replacement, without a
manual page refresh. Press `Ctrl+C` to stop the application processes; the infrastructure containers
remain available for the next run and can be stopped with `docker compose down`.

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

When running the services separately instead of using `dev.ps1`, run migrations and start the API
from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Apply migrations to the test database from `backend/`, then restore normal configuration from `.env`:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://platform:platform@127.0.0.1:5432/platform_test"
.\.venv\Scripts\python.exe -m alembic upgrade head
Remove-Item Env:DATABASE_URL
```

The API is available at `http://127.0.0.1:8000`; `GET /health` returns its health status.

Create a migration after changing SQLAlchemy metadata with:

```powershell
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "describe change"
```

Run backend checks from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

Integration tests refuse to run if `TEST_DATABASE_URL` is missing or points to the same database as `DATABASE_URL`.

Authentication uses opaque server-side sessions stored in PostgreSQL. Session cookies are
HttpOnly and SameSite=Lax. Set `AUTH_SESSION_COOKIE_SECURE=true` in HTTPS production
environments; `AUTH_SESSION_TTL_HOURS` controls the session lifetime and defaults to seven days.

## Local authentication

Local account enrollment follows `register -> verify email -> choose password -> authenticated
session`. Submit a name and email at `/register`; Auron sends a link whose verification token is in
the URL fragment. Only after that token is proven does Auron create the User's Argon2id
`LocalCredential` and the same PostgreSQL-backed `AuthSession` used by Google login. Registration
never accepts a password and never acts as password reset.

Configure SMTP in `.env` to enable registration and resend:

```text
SMTP_HOST=127.0.0.1
SMTP_PORT=1025
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_STARTTLS=false
EMAIL_FROM=no-reply@auron.local
FRONTEND_BASE_URL=http://127.0.0.1:5173
```

`SMTP_USERNAME` and `SMTP_PASSWORD` are optional for a local SMTP capture server. Auron does not
ship or require a mail container; point these values at a local SMTP test server of your choice.
SMTP is optional at startup, and existing local credentials can still sign in when it is absent.
Registration and resend return 503 when delivery is required but unavailable. Verification links
expire after `EMAIL_VERIFICATION_TTL_HOURS` (24 by default), and resend uses
`EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS` (60 by default).

User is provider-independent. A `LocalCredential` and a Google `AuthIdentity` may both belong to
the same User. On first trusted Google linking, a verified matching email reuses that global User;
existing `provider + subject` mappings remain authoritative. Adding another authentication method
does not modify Platform Admin access, OrganizationMembership, invitations, or existing sessions.

## Account settings

Authenticated account settings are available at `/app/settings/profile` and
`/app/settings/security`. Profile updates use the existing self-only User endpoint; email remains
immutable and its verification status is read-only.

Changing a configured password requires the current password. A successful change keeps the
current authenticated session and revokes the User's other active sessions in the same database
transaction. A Google-only User can choose **Add password** to start the existing verified-email
enrollment flow; Auron commits the challenge before sending it through the configured SMTP server.
Account settings never select or modify an Organization.

Before an Internet-facing production deployment, apply distributed rate limits at the ingress to
`/auth/login`, `/auth/register`, and `/auth/email-verifications/resend`. A process-local limiter is
intentionally not included.

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
accepts the invitation. The first accepted invitation establishes the initial `owner`; subsequent
acceptances use the compatibility role `member`. If that User already has membership, acceptance
marks the invitation accepted without changing or duplicating the membership. Platform Admin V1
does not manage Organization roles, groups, or permissions.

## Module platform foundation

Business modules register stable module and permission keys explicitly in code. The production
registry currently contains the implemented `competitive_intelligence` module. PlatformAdmin may
configure an Organization's registered entitlements through `OrganizationModule`, but this does not
create OrganizationMembership or grant tenant-data access.

Organization owners manage tenant-owned Access Groups, grant registered
`module.resource.action` permission keys, and assign OrganizationMemberships to one or more groups.
Effective permissions are the union of those grants filtered to enabled modules. Owner bypasses
Access Group permission checks, but never a disabled module entitlement; `admin` and `member` receive
no automatic module permission. Disabling a module preserves its group permission configuration.
See `docs/MODULE_CONTRACT.md` for the module integration contract.

A business module may optionally expose an `AnalyticsProvider` that returns standardized scalar or
grouped metric results. This is a code-level integration contract only; no Analytics product or API
exists yet. Every metric query requires the source module's Organization entitlement and the
metric's source-module permission, using the same dynamic Access Group and owner rules as normal
module endpoints. Analytics Core never queries business-module tables directly.

### Competitive Intelligence V1

Competitive Intelligence uses module key `competitive_intelligence` and permission
`competitive_intelligence.analysis.run`. PlatformAdmin enables the module entitlement for an
Organization. Owners may run it after entitlement succeeds; other memberships require that explicit
permission through an Access Group.

Configure `OPENAI_API_KEY` and `TAVILY_API_KEY` in the backend environment. `OPENAI_BASE_URL` is
optional. The V1 endpoint runs a synchronous question generation, Tavily search, ephemeral Chroma
retrieval, and report generation pipeline. Search documents and reports are not persisted, and each
execution removes its temporary vector collection. The frontend route is
`/app/organizations/:organizationId/modules/competitive-intelligence`. Tests replace external
providers with deterministic fakes and do not call OpenAI or Tavily.

## Module development workflow

Create a minimal registered module package with:

```powershell
.\backend\.venv\Scripts\python.exe `
  .agents\skills\auron-module\scripts\create_module.py `
  --key <module_key> `
  --name "<Name>"
```

Add `--analytics` only when the module will implement the existing AnalyticsProvider contract, or
`--dry-run` to inspect paths without writing. Before completing module work, run:

```powershell
.\backend\.venv\Scripts\python.exe `
  .agents\skills\auron-module\scripts\validate_module.py <module_key>
```

The canonical architecture remains in `AGENTS.md`, `docs/ARCHITECTURE.md`, and
`docs/MODULE_CONTRACT.md`. When an explicit cross-AI project snapshot is needed, invoke the
`auron-handoff` Skill; it generates the ignored `.ai/AURON_HANDOFF.md` from current repository
evidence. Normal module work does not generate this snapshot.

The explicitly invoked handoff Skill collects deterministic repository context from the repository
root with:

```powershell
.\backend\.venv\Scripts\python.exe `
  .agents\skills\auron-handoff\scripts\collect_context.py
```

Reissue an expired, unaccepted invitation from `backend/` with:

```powershell
.\.venv\Scripts\python.exe -m app.scripts.reissue_organization_invitation `
  --organization-id <uuid> `
  --email user@example.com
```

Use `--expires-hours` to override the default seven-day lifetime. Reissue updates the existing
invitation's expiration in place. Active invitations are not silently extended, accepted
invitations cannot be reopened, and no new invitation or membership is created.

## Frontend setup

When running the services separately instead of using `dev.ps1`, use a second terminal:

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

The Vite development server is available at `http://127.0.0.1:5173`. It proxies the frontend's
relative authentication, Organization, invitation, and Platform Admin API requests to the backend
at `http://127.0.0.1:8000`, so no frontend secrets or local CORS configuration are needed.

After authentication, `/app` loads only the User's membership-scoped Organizations and invitations
for their authenticated email. A single Organization opens automatically when no invitation is
pending; otherwise `/app` presents the applicable invitations and Organization selector. The
Organization route includes its ID (`/app/organizations/<organization-id>`) and validates access
with the backend whenever it loads. Current Organization selection is not persisted in the session,
a cookie, or browser storage. Organization provisioning remains available only through `/admin` to
authorized Platform Admins.

The frontend uses one responsive `AppShell` for desktop, tablet, and mobile. At narrow widths its
navigation becomes a keyboard-accessible drawer; there is no separate mobile application. Light
and dark themes follow the operating-system preference on first visit, and an explicit selection is
stored locally as UI preference only. The initial theme is applied before React renders to avoid a
visible theme flash.

The default interface language is Brazilian Portuguese (`pt-BR`), with English (`en`) available
from the preferences controls. An explicit language choice is also stored locally, and translation
resources live in `frontend/src/i18n/locales/`. Future modules should add their user-visible copy
under a module-specific translation section and use browser `Intl` APIs for locale-aware values.

Official brand PNGs live in `frontend/public/` and are referenced only through `BrandLogo`. The
replacement contract is a roughly 4:1 horizontal logo displayed at 140–180 px, a square vertical
brand displayed at 140–180 px on authentication screens, and a square mark displayed at 32–40 px.
Keep the current light/dark filenames when replacing them so layouts need no code changes. A future
asset delivery should preferably provide cropped, transparent SVG equivalents and a dedicated
favicon; the current pixels are intentionally unchanged.

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
