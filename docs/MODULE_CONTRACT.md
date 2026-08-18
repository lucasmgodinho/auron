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

## Module isolation and frontend

Modules must use this shared tenancy, entitlement, and authorization foundation instead of creating
ad-hoc alternatives. Future cross-module Analytics must not query another module's models directly.
A module may later participate through an AnalyticsProvider contract, but that contract belongs to
Milestone 2 and is not defined here.

Module UI supports desktop/mobile, light/dark/system themes, semantic design tokens, and pt-BR plus
English i18n. Backend entitlement and permission metadata may guide UX, but frontend visibility is
never authorization.

## Testing

Every module must cover tenant isolation, enabled and disabled entitlement, allowed and denied
permission, owner bypass with entitlement, and cross-tenant access attempts using PostgreSQL-backed
tests where persistence behavior matters.
