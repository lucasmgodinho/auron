# Architecture

Auron starts as a modular monolith: one deployable backend is the simplest way to develop and operate the product while its real boundaries are still emerging. Future business modules will be kept isolated within the backend so they can evolve without introducing distributed-system complexity prematurely.

The FastAPI backend owns application logic and persistence. The React frontend is a separate TypeScript application that communicates with the backend over HTTP. PostgreSQL is the primary database and SQLAlchemy plus Alembic manage access and schema evolution.

## SaaS Core and business modules

Required platform capabilities live under `app/core`, including organizations, users, organization memberships, and authentication. Organization is the tenant root, while User is a global platform identity. OrganizationMembership links Users to Organizations and stores the organization-specific role.

User is authentication-provider independent. Its nullable `email_verified_at` is the common trust
signal that Auron has established control of the immutable email, whether through Auron email
verification or a trusted provider's verified claim. `LocalCredential` stores one Argon2id password
hash per User, while AuthIdentity stores an external provider's stable subject; provider email is
not an identity key. AuthSession is an opaque authenticated platform session that stores only a
token hash. Authentication resolves User only and does not select an Organization.

The identity shape is `User -> LocalCredential`, `User -> AuthIdentity(Google)`, `User ->
AuthSession`, `User -> OrganizationMembership`, and optional `User -> PlatformAdmin`. A User may
have both local and Google authentication without duplicating or moving tenant/platform access.
For a new trusted Google subject, a verified matching email reuses the existing User and marks its
email verified. An existing `AuthIdentity(provider, subject)` is authoritative and is never
reassigned because the provider later reports a different email.

Local registration stores only a hashed, expiring email-verification challenge. Proving that token
atomically creates the LocalCredential, marks the User verified, consumes the challenge, and creates
the normal AuthSession. SMTP delivery happens only after the challenge transaction commits. Before
Internet exposure, `/auth/login`, `/auth/register`, and `/auth/email-verifications/resend` require
deployment/ingress rate limiting; no process-local limiter is treated as distributed protection.

Organization context is resolved explicitly for each organization-scoped request. The authenticated User and the route's `organization_id` are used to load the requested Organization and validate the matching OrganizationMembership, producing a request-scoped `OrganizationContext` containing all three records. A client-provided `organization_id` identifies the desired tenant but never authorizes access by itself. Missing Organizations return 404, while existing Organizations without a matching membership return 403.

PlatformAdmin is binary global Auron access and is independent from OrganizationMembership. A
Platform Admin provisions a new Organization together with one or more OrganizationInvitation
records; no placeholder Users or memberships are created. An authenticated User sees invitations
only for their verified immutable email and acceptance atomically creates the tenant membership.
This means a newly provisioned Organization may validly have no memberships until an invitation is
accepted. V1 stores at most one invitation per Organization and normalized email; duplicate form
entries are deduplicated. The first acceptance is serialized under an Organization row lock and
creates the initial `owner`; subsequent acceptances create `member` memberships. These roles remain
the current compatibility authorization mechanism. Existing membership roles are never changed by
invitation acceptance.

An expired, unaccepted invitation can be reissued in place by trusted operator tooling. Reissue
locks the existing invitation and changes only its expiration; active invitations are not extended
and accepted invitations are never reopened.

Conceptually, Auron has `PlatformAdmin -> platform provisioning` alongside
`Organization -> OrganizationInvitation -> OrganizationMembership`. Platform Admin access never
implies tenant access, and an Organization role never grants Platform Admin access. Future tenant
authorization may evolve toward `Organization -> Access Groups -> Memberships`, with permission
catalogs defined by implemented Auron modules.

The module platform uses an explicit code-defined Module Registry. Production registrations exist
only for implemented business modules, so the registry is currently empty. `OrganizationModule`
stores whether a registered module is enabled for a tenant; a missing row is disabled. PlatformAdmin
may change this entitlement without gaining OrganizationMembership or tenant access.

Operational access is tenant-owned: `OrganizationAccessGroup` contains code-defined permission-key
grants through `OrganizationAccessGroupPermission`, and
`OrganizationMembershipAccessGroup` assigns one OrganizationMembership to one or more groups.
Effective permissions are resolved dynamically as the union of group grants filtered by enabled
modules. They are never stored in AuthSession. Disabling a module preserves its grants.

Future module requests follow:

```text
Authentication
→ Organization Context
→ OrganizationModule entitlement
→ owner bypass or Access Group permission
→ Business Module
```

Only `owner` bypasses Access Group permissions, and only after entitlement succeeds. `admin` has no
automatic module bypass. PlatformAdmin remains outside tenant access unless separately associated.

Implemented business modules may optionally expose a code-defined `AnalyticsProvider`. Analytics
Core discovers those providers only through the Module Registry and orchestrates one source metric
at a time:

```text
Analytics query
-> Organization Context
-> metric and source module
-> OrganizationModule entitlement
-> required source permission
-> AnalyticsProvider
-> source module repository
```

Analytics Core validates contracts and authorization but contains no business SQL. The provider
receives the existing request-scoped Session plus the validated Organization ID and may query only
its own module's repositories. A future dashboard may compose a Fleet metric and a Cost Management
metric, but it must call and authorize each provider independently; one provider never crosses into
another module's tables. Analytics definitions and results remain in memory and are neither cached
nor persisted.

Future tenant-owned modules must use `OrganizationContext.organization.id` as the validated `organization_id` for every business-data query. Organization selection is not stored in AuthSession, User, or a cookie, so membership changes apply on the next request without changing the authenticated session.

The frontend never handles authentication tokens. It derives browser authentication state from
`GET /auth/me`, while the backend-owned HttpOnly cookie remains the session mechanism.

Global User settings live at `/app/settings/*` and do not depend on Organization context.
Any future Organization settings remain tenant-scoped and separate from these global routes.
`AuthIdentity` and `LocalCredential` are authentication methods for the same User: account metadata
exposes only whether each method exists. Password changes lock the LocalCredential and atomically
revoke the User's other active sessions while preserving the server-resolved current session. A
User without LocalCredential adds one through the same verified-email challenge used by local
enrollment; this does not change AuthIdentity, OrganizationMembership, or PlatformAdmin records.

The frontend keeps tenant selection in the route. `/app` combines the authenticated User's
membership-scoped Organization list with invitations for that User's email, while
`/app/organizations/:organizationId` asks the backend to validate membership each time the route
loads. The route ID identifies the requested Organization but never grants access, and no selected
Organization is persisted in authentication state, cookies, or browser storage. Platform Admin
Organization listing and provisioning remain a separate `/admin` flow and do not imply tenant
access.

The frontend foundation is organized around the existing route tree:

```text
AppShell
├── responsive navigation
├── theme preference
├── locale preference
└── route content
```

`AppShell` is shared by desktop, tablet, and mobile layouts; its narrow layout uses an accessible
navigation drawer. Theme and locale are non-authoritative UI preferences and are the only Auron
state persisted in browser storage. Brazilian Portuguese is the default locale, English is the
second supported locale, and visible copy is sourced from `frontend/src/i18n/locales/`. The current
Organization remains route-derived and backend-authorized on every Organization route load.
PlatformAdmin remains independent from OrganizationMembership. Future implemented modules can add
real navigation entries and translation sections to this shell, but no placeholder module
navigation exists today.

Google login follows `Google OIDC -> AuthIdentity(provider="google", provider_subject=sub) -> User -> AuthSession`. Password login follows `LocalCredential -> User -> AuthSession`. Organization access remains separate through `User -> OrganizationMembership -> Organization`; neither login method selects a tenant.

Optional business capabilities such as fleet, clinic, documents, workflows, and analytics live under `app/modules`. Tenant-owned entities remain inside their business module, reference `organization_id`, and scope data access to that organization.

For local development, only PostgreSQL runs in Docker Compose. Python and Node.js run directly on the host for fast feedback and straightforward debugging.

Microservices, messaging, background-job infrastructure, and other scaling mechanisms are intentionally deferred until concrete product or operational needs justify them.
