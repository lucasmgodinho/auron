# Auron working agreement

Read `.github/agents.md` for shared instructions and the relevant engineering role.
It is the single agent instruction source for GitHub and local sessions.
Read `docs/ENGINEERING_RULES.md` before editing; architecture and module contracts
remain in `docs/ARCHITECTURE.md` and `docs/MODULE_CONTRACT.md`.

Confirm Git root/HEAD/dirty files and preserve unrelated work. No commit, push,
deploy, shared DB changes or costly installs without explicit authorization.
GitHub stages require the configured human's separate manual dispatch; only their
trusted publisher may perform the publishing authorized for that stage.

Run `scripts/verify.ps1 -Mode fast` and focused checks. Full requires an explicitly
prepared disposable DB/tokenizer; `scripts/verify-disposable.ps1` owns optional
local setup/cleanup. Missing prerequisites and skipped checks are not passes.
See `docs/AI_FIRST_WORKFLOW.md` for operation and commands.

## Code Review Rules

Review the assigned delta independently; distinguish pre-existing work. Prioritize
tenant/permission boundaries, secrets, streaming/cancellation and meaningful test
evidence. A clean review does not establish tests/browser behavior not executed.
