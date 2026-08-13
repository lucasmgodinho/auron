# Architecture

Auron starts as a modular monolith: one deployable backend is the simplest way to develop and operate the product while its real boundaries are still emerging. Future business modules will be kept isolated within the backend so they can evolve without introducing distributed-system complexity prematurely.

The FastAPI backend owns application logic and persistence. The React frontend is a separate TypeScript application that communicates with the backend over HTTP. PostgreSQL is the primary database and SQLAlchemy plus Alembic manage access and schema evolution.

## SaaS Core and business modules

Required platform capabilities live under `app/core`, including organizations, users, organization memberships, and authentication. Organization is the tenant root, while User is a global platform identity. OrganizationMembership links Users to Organizations and stores the organization-specific role.

AuthIdentity stores an external provider's stable subject and links it to User; provider email is not an identity key. AuthSession is an opaque authenticated platform session that stores only a token hash. Authentication resolves User only and does not select an Organization.

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
catalogs defined by implemented Auron modules; neither access groups nor module entitlements exist
yet.

Future tenant-owned modules must use `OrganizationContext.organization.id` as the validated `organization_id` for every business-data query. Organization selection is not stored in AuthSession, User, or a cookie, so membership changes apply on the next request without changing the authenticated session.

The frontend never handles authentication tokens. It derives browser authentication state from
`GET /auth/me`, while the backend-owned HttpOnly cookie remains the session mechanism.

Google login follows `Google OIDC -> AuthIdentity(provider="google", provider_subject=sub) -> User -> AuthSession`. Organization access remains separate through `User -> OrganizationMembership -> Organization`. Google login does not select a tenant; Current Organization resolution remains a separate future concern.

Optional business capabilities such as fleet, clinic, documents, workflows, and analytics live under `app/modules`. Tenant-owned entities remain inside their business module, reference `organization_id`, and scope data access to that organization.

For local development, only PostgreSQL runs in Docker Compose. Python and Node.js run directly on the host for fast feedback and straightforward debugging.

Microservices, messaging, background-job infrastructure, and other scaling mechanisms are intentionally deferred until concrete product or operational needs justify them.
