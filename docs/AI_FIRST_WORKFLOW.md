# AI-first engineering with native Codex

This is a supervised repository workflow, not an orchestration service. Auron's
architecture remains authoritative. Instructions guide decisions; Skills package
reusable procedures; subagents perform bounded work; deterministic gates execute
checks and return failures independently of an agent's judgment.

## Source index and reading order

1. `AGENTS.md`: working agreement and review rules.
2. `docs/ENGINEERING_RULES.md`: mandatory detailed rules preserved from the prior
   AGENTS.md, including identity, tenancy, authorization, Analytics and frontend.
3. `docs/ARCHITECTURE.md` and `docs/MODULE_CONTRACT.md`: system/module contracts.
4. `README.md`, `docs/DEBUG_TOOLKIT.md` and
   `docs/COMPETITIVE_INTELLIGENCE_OBSERVABILITY.md`: setup and diagnosis.
5. Actual implementation, tests, `backend/pyproject.toml`, requirements and
   `frontend/package.json`: executable evidence. Report documentation drift.

Existing `.agents/skills/auron-module` supplies module scaffolding/validation.
`auron-handoff` is only for explicitly requested cross-AI handoffs; generated
snapshots never replace this source index. Retrieval metrics and human benchmark
review are distinct from software regression checks. Never regenerate frozen V2
artifacts as a side effect of verification.

## Activate in Codex

Open the intended checkout/worktree as the Codex working directory, or launch
`codex -C <absolute-checkout-path>`. Confirm its Git root and current changes.
Project skills live in `.agents/skills/<name>/SKILL.md`. Mention `$auron-diagnose`,
`$auron-implement-verify`, or `$auron-review`; use `/skills` to inspect discovery.

Two project roles live in `.codex/agents/*.toml`: `auron_explorer` gathers evidence
and plans; `auron_reviewer` reviews security, tests and architecture independently.
They inherit model and permissions; no extra agent is needed for implementation.
Project configuration may require repository trust in the Codex UI. Start a fresh
session after changing agent configuration and confirm discovery. If a host does
not expose custom-role selection, explicitly read the role file into a native
subagent task and disclose this fallback. Do not claim automatic loading occurred.

Example request:

```text
Use $auron-diagnose. Delegate a bounded investigation to auron_explorer.
Define acceptance, then use $auron-implement-verify for the smallest justified fix.
Have auron_reviewer use $auron-review on our delta, correct findings and report
test evidence and limitations. Preserve pre-existing work. No commit or deployment.
```

Native `/review` is another independent review entry point. Specify the base and
file scope; an uncommitted review can otherwise include unrelated dirty files.
Do not run overlapping reviewers unless distinct risks justify them.

## One incremental cycle

1. Capture HEAD, status and relevant file hashes; preserve existing dirty work.
   A worktree starts at committed HEAD: copy needed local changes deliberately,
   record their ownership and never use reset/clean/stash to hide them.
2. Explorer diagnoses a concrete failure read-only and returns sources, a
   reproduction, prioritized scope and acceptance. Parent decides the bounded fix.
3. Implementer changes only that scope and adds meaningful regression coverage.
4. Run focused checks and fast verification. Record command, exit code, counts,
   missing prerequisites and side effects. Correct failures before expanding checks.
5. Independent reviewer receives the delta and evidence, not a desired conclusion.
   Implementer resolves actionable findings, reruns affected checks and requests a
   focused recheck when needed.
6. Report what changed, evidence, unresolved risks and next priority. Improve
   instructions only from observed friction; keep reusable guidance concise.

Human decisions remain required for architecture/domain/benchmark label changes,
new costly dependencies, shared DB operations, commits, publishing and deployment
when not already authorized. Worktrees share Compose project names, ports and
possibly runtimes; they do not establish database isolation.

## Verification and acceptance

`scripts/verify.ps1 -Mode fast` is intended for lint, types, existing frontend
tests, backend collection, selected non-DB tests, module validation, Alembic heads
and immutable fixture checksums. It installs nothing and starts no services.
Pass `-Python <venv-python>` when reusing an existing backend environment in a
worktree. Frontend dependencies must already be installed for this checkout.
The runner supports PowerShell 7 on Windows and Linux. Its default Python path
uses this checkout's backend virtualenv; `-Python python` uses a prepared PATH.

`-Mode full -DisposableTestDatabase` adds the full backend suite and production frontend build. It must
fail when its dedicated test database or real tokenizer prerequisites are absent.
DB tests can commit setup/cleanup on separate connections: only use a prepared
disposable test DB, explicitly distinct from the application DB. Verification
does not create DBs or apply migrations. Provisioning is a separate human action.
The full-suite child process points its fallback application DATABASE_URL at an
unreachable loopback port, while retaining TEST_DATABASE_URL for fixture-managed
integration tests. This also protects subprocess tests without fixture overrides;
their audit persistence is not established by this mode. It performs TypeScript
checks and Vite build separately to avoid writing cache files in shared dependencies.

Tokenizer provisioning is explicit, from `backend/`:

```powershell
python -m app.scripts.provision_tokenizer          # Downloads validated assets if absent
python -m app.scripts.provision_tokenizer --check  # Cache validation; network forbidden
```

Use the chosen virtualenv's Python. Tiktoken validates its upstream asset checksum.
`TIKTOKEN_CACHE_DIR` can select a dedicated setup cache; use the same path when
running real chunking tests. Application imports and pure tests need no such cache.

For this first increment, accept only if:

- Cold-cache application import and pytest collection make no tokenizer/network
  acquisition. Pure non-tokenizer tests run without a DB/provider.
- Real chunking retains text-embedding-3-small's cl100k_base tokenizer, identical
  token counts/chunk boundaries/overlap and failure propagation; no fallback.
- Fast/full propagate failures and never provision, migrate or delete databases.
- Existing dirty files and frozen benchmark bytes remain unchanged; the delta has
  an independent review and exact executed evidence.

## Continuous integration

`.github/workflows/ci.yml` runs on pull requests, pushes to develop/main and manual
dispatch. It uses Ubuntu 24.04, Python 3.14, Node 24 and an ephemeral PostgreSQL 17
service with a dynamically assigned host port. It receives no application secrets
or production database URL. Checkout credentials are not persisted; token access
is limited to reading repository contents.

Setup installs declared dependencies with pip/npm ci, explicitly provisions the
tokenizer, and applies migrations plus `alembic check` only to that job's disposable
test DB. The final step calls the same `verify.ps1 -Mode full` used locally. Setup
and migration commands remain outside the verification script. Results belong to
the exact committed checkout; local dirty/untracked files are not part of CI.
The narrow `.gitattributes` rule for frozen V2 artifacts preserves their recorded
CRLF checkout bytes on Linux too. Their data, checksum inventory and Git blobs are
unchanged; never regenerate the benchmark to accommodate platform line endings.

After an authorized push, inspect the GitHub Actions job logs. A workflow file or
local fast pass does not establish a green remote run. Do not dispatch/push merely
to obtain evidence unless already authorized. PostgreSQL-backed full validation
still needs a prepared disposable DB locally when Docker is unavailable.

Real-browser E2E remains a follow-up. DOM tests do not establish browser cookies,
rendering or live streaming. Do not label full acceptance while required
DB/browser/provider checks remain unexecuted.

## Official format references

Verified against local Codex CLI 0.163.0-alpha.10.2 on 2026-10-19, with multi_agent
enabled. Project roles use standalone TOML with name, description and
developer_instructions, rather than legacy role-config indirection. Read-only
role wording is an instruction, not an enforced sandbox boundary.

- [Subagents and custom role schema](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Skills and repository discovery](https://learn.chatgpt.com/docs/build-skills)
- [AGENTS.md discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
