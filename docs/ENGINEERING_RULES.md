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
- User is authentication-provider independent; trusted authentication methods sharing a verified
  normalized email must converge on the same User.
- `User.email_verified_at` is the provider-independent email-ownership trust signal. Existing
  external `provider + subject` mappings are authoritative and must not be reassigned by email.
- Passwords must use a password-specific hash such as Argon2id. Raw passwords and raw email
  verification tokens must never be persisted or logged.
- Never create LocalCredential for an existing User without verified email or authenticated account
  control. Registration must not replace a credential or act as password reset.
- OrganizationInvitation acceptance requires `User.email_verified_at`; authentication method must
  not change OrganizationMembership or PlatformAdmin access.
- OrganizationMembership connects Users to Organizations; organization-specific roles belong there.
- PlatformAdmin is global and independent from OrganizationMembership; Organization roles must
  never grant Platform Admin access, and Platform Admin access does not imply tenant membership.
- New customer Organizations are provisioned only by Platform Admin. Invitation emails never
  create placeholder Users, and acceptance must match the authenticated User's verified email.
- A provisioned Organization may start with zero memberships. Under an Organization lock, the
  first accepted invitation establishes the initial owner; subsequent acceptances default to
  member, and an existing membership role is never overwritten.
- Expired, unaccepted Organization invitations may be reissued in place. Active invitations are
  not silently extended, and accepted invitations are never reopened.
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
- Frontend Organization selection comes from the route and must be validated by the backend on
  each Organization route load; never persist a selected Organization in authentication state,
  cookies, or browser storage.
- Normal `/app` Organization discovery must use membership-scoped APIs. Platform Admin listing and
  provisioning remain a separate `/admin` concern and do not grant tenant access.
- Global account settings must not depend on Organization context.
- User email remains immutable unless an explicit verified-email-change flow is implemented.
- Password changes require the current password, preserve the current session, and revoke the
  User's other active sessions.
- Authentication-method changes must not affect OrganizationMembership or PlatformAdmin.
- Account APIs must never expose password hashes, provider subjects, session tokens, or
  verification tokens.
- Business modules must use the explicit Auron Module Registry; never register fake or unimplemented
  production modules for UI completeness.
- Module keys are stable identifiers, and permission keys are stable `module.resource.action`
  identifiers defined by registered module code.
- Tenant module endpoints must enforce Organization Context, module entitlement, and required
  permission. Owners bypass Access Group permissions but never module entitlement.
- Access Groups belong to Organizations and attach to OrganizationMemberships, never Users.
- Only registered permission keys may be stored. Disabling a module must preserve its group grants.
- Effective permissions are resolved dynamically and must never be stored in AuthSession.
- Business modules may optionally expose code-defined metrics through `AnalyticsProvider`.
- Analytics metric keys use `module.metric_name` and require a permission from that same module.
- Analytics access must enforce source-module entitlement and current Access Group authorization.
- Analytics Core must never query business-module tables; providers query only their own module and
  scope every query to the validated Organization context.
- Providers must ownership-validate domain filter IDs. Analytics queries never accept
  `organization_id`, raw SQL, table names, columns, or arbitrary expressions.
- Analytics results are visualization-agnostic; do not add chart concepts to the Core contract.
- Use `docs/MODULE_CONTRACT.md` and `scripts/create_module.py` / `scripts/validate_module.py`
  when creating or materially extending business modules.
- Canonical architecture remains in `docs/`; agent instructions must reference, not duplicate,
  those contracts.
- Run the Auron module validator before completing module work.

## Frontend foundation

- All new user-visible frontend strings must use the existing i18n resources; `pt-BR` is the default locale.
- New UI must support light and dark themes through semantic design tokens and remain usable on desktop and mobile.
- Functional UI colors must satisfy accessibility requirements independently from brand artwork.
- Frontend Organization state and Platform Admin navigation are never authorization mechanisms.
- Browser storage may contain theme and locale preferences only, never authentication, verification, or tenant-access data.
- Do not add navigation for a business module before that module exists.
