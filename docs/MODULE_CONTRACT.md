# Auron Module Contract

This contract defines the minimum integration boundary for future Auron business modules.

## Identity and registration

Every module has a stable, lowercase `module_key` matching `^[a-z][a-z0-9_]*$`. A key may use
snake case, is registered explicitly in the code-defined Module Registry, and must not be renamed
casually after production use. The registry contains the module's translation `name_key` and its
immutable permission definitions; it does not contain pricing, plans, import paths, or runtime
plugin metadata.

## Tenancy and entitlement

Every tenant-owned record includes `organization_id`. Module repositories receive the Organization
ID from validated Organization Context and never treat a raw client-supplied ID as authorization.
Every module endpoint requires an enabled `OrganizationModule`; absence means disabled.

Authentication, Organization Context, module entitlement, and operational permission are separate
checks. PlatformAdmin may configure entitlements but receives no tenant access. Organization owner
bypasses Access Group permission grants only and never bypasses a disabled entitlement.

## Permissions and Access Groups

Protected actions use stable code-defined keys in `module.resource.action` form. Resource and action
segments are lowercase stable identifiers; CRUD actions normally use `read`, `create`, `update`, and
`delete`, while concrete domain actions may add other verbs. Translated labels are never persisted.

Access Groups belong to one Organization and attach to OrganizationMemberships, never directly to
Users. Groups grant only positive permissions. A membership's effective permissions are the union
of its groups' registered permission keys filtered to currently enabled modules. Effective
permissions are resolved per request and are not persisted in User, AuthSession, or browser storage.
Disabling a module preserves group grants so re-enabling restores them.

The standard endpoint pipeline is:

```text
Authentication
→ Organization Context
→ OrganizationModule enabled
→ owner bypass or effective Access Group permission
→ business behavior
```

## AnalyticsProvider

A business module may optionally expose one code-defined `AnalyticsProvider` through its
`ModuleDefinition`. Provider metric keys use stable `module.metric_name` identifiers. Each metric
declares its i18n name key, semantic format, supported dimensions, explicit typed filters, and a
mandatory `required_permission` from the same source module. Modules without a provider remain
valid and contribute no metrics.

Analytics queries never accept `organization_id`, SQL, table names, columns, joins, or arbitrary
expressions. Analytics Core validates the metric, declared `group_by`, filter keys, basic filter
types, source-module entitlement, and current effective permission before invoking the provider.
Owner bypasses the metric permission only when the source module is enabled. PlatformAdmin alone
does not grant tenant Analytics access.

Providers receive the existing request-scoped SQLAlchemy Session and a trusted context containing
the server-validated Organization ID. They own their module-specific queries and must scope every
repository call by that ID. Core can validate that a domain filter is a UUID, but the provider must
verify that the referenced domain record belongs to the validated Organization.

Analytics Core never queries business-module tables. A provider may query only its own module's
models/repositories; future composite Analytics calls providers independently so every metric is
authorized against its own source module. Results support scalar and grouped data without chart
metadata. Values use `Decimal` internally and serialize as exact decimal strings. Currency uses an
explicit uppercase currency code, percentage uses the `0..1` convention, and duration uses an
explicit supported unit.

## Module isolation and frontend

Modules must use this shared tenancy, entitlement, authorization, and Analytics foundation instead
of creating ad-hoc alternatives. A provider must not query another module's models directly.

Module UI supports desktop/mobile, light/dark/system themes, semantic design tokens, and pt-BR plus
English i18n. Backend entitlement and permission metadata may guide UX, but frontend visibility is
never authorization.

## Testing

Every module must cover tenant isolation, enabled and disabled entitlement, allowed and denied
permission, owner bypass with entitlement, and cross-tenant access attempts using PostgreSQL-backed
tests where persistence behavior matters.

## Engineering tools

With the provisioned backend Python, from the repository root:

```powershell
python scripts/create_module.py --key <key> --name <name> --dry-run
python scripts/create_module.py --key <key> --name <name>
python scripts/validate_module.py <key>
```

The scaffold updates the explicit production registry. Add only real domain code;
define stable permissions before protected endpoints. `--analytics` scaffolds the
provider declaration; implement concrete metrics/queries before use. Do not add
placeholder modules or frontend navigation. Keep routers thin and run focused tests
plus the shared verification gates after module validation.
