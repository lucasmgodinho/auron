---
name: auron-module
description: Create or materially extend an Auron business module using the repository's canonical module, tenancy, authorization, and optional Analytics contracts.
---

# Auron Module Development

Before changing a module, read `AGENTS.md` and `docs/MODULE_CONTRACT.md`, then inspect existing
module and Core conventions relevant to the work. Treat those files and current code as canonical.

For a new module, use the backend-virtualenv scaffold command in
[`references/workflow.md`](references/workflow.md); do not hand-build a competing layout. Read that
reference for the concise creation/evolution workflow.

Use the existing Organization Context, `OrganizationModule`, Access Groups, stable
`module.resource.action` permissions, and `require_module_permission`. When the module genuinely
provides metrics, integrate through the existing `AnalyticsProvider` contract. Never create ad-hoc
tenancy, permission, analytics, session, registry, or infrastructure systems.

Before completion, run the backend-virtualenv validator command from the workflow, focused module
tests, relevant cross-tenant/authorization regressions, and the repository's standard validators.
Do not register placeholder or unimplemented production modules.
