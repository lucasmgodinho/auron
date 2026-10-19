# Auron working agreement

Read `docs/ENGINEERING_RULES.md` before edits; all its existing engineering,
security, tenancy and UI rules remain mandatory. Use `docs/ARCHITECTURE.md`
and `docs/MODULE_CONTRACT.md` as the architecture and module sources of truth.
See `docs/AI_FIRST_WORKFLOW.md` for the source index, workflow and acceptance gates.

- Verify Git root, HEAD and dirty/untracked files. Preserve existing work; isolate
  changes in a worktree when useful. Worktrees do not isolate ports, Compose or DBs.
- Keep the modular monolith, server-validated tenant authorization and streaming.
  Preserve benchmark artifacts under `backend/evaluation/benchmarks/v2/`.
- Do not commit, push, deploy, migrate/delete shared DB data or install costly
  dependencies without authorization. Never print secrets or copy `.env` to reports.
- Use `$auron-diagnose` for evidence-backed diagnosis, `$auron-implement-verify`
  for bounded fixes and `$auron-review` for independent review. Keep the existing
  `$auron-module` and explicit-only `$auron-handoff` workflows.
- When delegation is requested, use `auron_explorer` for read-only investigation
  and `auron_reviewer` for an independent final pass. Do not duplicate the same task.
  Role instructions restrict behavior; they do not create a separate sandbox.
- Run `scripts/verify.ps1 -Mode fast` and focused behavior checks. Use `-Mode full`
  only with an explicitly prepared disposable test DB and provisioned tokenizer.
  Missing prerequisites and skipped checks are not passing results.
- Define acceptance before editing; correct findings, rerun affected checks, and
  report commands, exit codes, evidence, remaining risks and the next useful step.

## Code Review Rules

Review only the assigned delta, identifying pre-existing changes separately.
Prioritize tenant isolation, permission/entitlement boundaries, secret exposure,
streaming/cancellation, production behavior and meaningful regression coverage.
A clean review is not a substitute for tests or real-browser evidence.
