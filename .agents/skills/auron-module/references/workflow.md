# Module workflow

## Create

1. From the repository root, run
   `.\backend\.venv\Scripts\python.exe .agents\skills\auron-module\scripts\create_module.py --key <key> --name <name>`.
2. Add only concrete domain files required by current behavior. Keep routers thin and business
   logic in services/repositories.
3. Replace the initially empty permission tuple with stable permissions before adding protected
   endpoints. Enforce Organization Context, entitlement, and permission on every tenant route.
4. Use `--analytics` only when the module will implement real metrics. Replace the empty provider
   declaration with explicit definitions and module-owned queries before shipping those metrics.
5. Add PostgreSQL-backed tenant-isolation and authorization tests where persistence matters.

The scaffold registers the definition in `backend/app/modules/registry.py`, the explicit
production composition point. Do not add filesystem discovery, entry points, or a second registry.

## Evolve

Inspect the module definition, permissions, routes, persistence, tests, and any AnalyticsProvider
before editing. Preserve stable identifiers and existing tenant boundaries. Add migrations only
for real metadata changes and update canonical documentation only when the contract changes.

## Frontend

Do not generate frontend files for backend-only modules. When real user-visible module UI exists,
follow the current React/i18n conventions, add pt-BR and English resources, and keep frontend state
non-authoritative. Do not add navigation before the module functionality exists.

## Validate

Run:

```powershell
.\backend\.venv\Scripts\python.exe `
  .agents\skills\auron-module\scripts\validate_module.py <module_key>
```

Then run focused tests, Ruff, the full backend suite when shared Core changed, Alembic checks for
metadata changes, and frontend validation only when frontend files changed.
