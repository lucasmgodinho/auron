# Project guidelines

- Prefer simple solutions over premature abstractions.
- The backend follows a modular monolith direction; keep business modules isolated when introduced.
- Business logic must not live inside FastAPI routers.
- Add dependencies only for a concrete current need.
- Do not add infrastructure for hypothetical scalability problems.
- Create abstractions only after a real use case exists.
- Every feature needs appropriate tests.
- Apply all database schema changes through Alembic migrations.
- Use `Decimal`, never `float`, for future monetary values.
- Do not modify unrelated parts of the project.
- Run relevant validation commands before declaring work complete.

## SaaS boundaries and multi-tenancy

- `app/core` contains required SaaS platform capabilities; `app/modules` contains optional business modules.
- Organization is the tenant root. Classify data as global/platform data or tenant-owned data.
- Tenant-owned entities must include `organization_id`, and their queries must always be scoped by it.
- Never trust an `organization_id` supplied by a client as authorization context.
- Organization context is request-scoped; never persist tenant selection in AuthSession, User, or a cookie.
- Tenant-owned services and repositories must receive `organization_id` from server-validated Organization context or an equivalent validated source.
- Include `organization_id` in tenant-specific uniqueness constraints when appropriate.
- Cover cross-tenant isolation with automated tests.
- User is a global platform identity and must not contain `organization_id`.
- OrganizationMembership connects Users to Organizations; organization-specific roles belong there.
- PlatformAdmin is global and independent from OrganizationMembership; Organization roles must
  never grant Platform Admin access, and Platform Admin access does not imply tenant membership.
- New customer Organizations are provisioned only by Platform Admin. Invitation emails never
  create placeholder Users, and acceptance must match the authenticated User's verified email.
- Business-module entitlements remain separate from invitations. Any future Organization access
  groups are tenant-owned and do not grant Platform Admin access.
- Keep authentication identities and provider-specific fields separate from User.
- Key external identities by provider and stable provider subject, never by email.
- Never persist or log raw session tokens; server-side sessions store only token hashes.
- Authentication resolves User only; tenant selection is a separate concern.
- Keep provider-specific authentication code out of User and OrganizationMembership.
- External OIDC providers authenticate User only; provider code must not resolve Organizations or
  depend on business modules.
- OAuth/OIDC redirect targets must come from trusted configuration. Never persist, log, or expose
  authorization codes, provider tokens, or platform session tokens in URLs.
- Frontend authentication state must be resolved through `/auth/me`; never store authentication or
  provider tokens in browser storage.
- Frontend tenant or authorization assumptions must never replace backend enforcement.
