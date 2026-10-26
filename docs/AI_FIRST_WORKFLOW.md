# Auron agents: operation

Agent instructions live only in `.github/agents.md`; `AGENTS.md` points local Codex
sessions there. GitHub explicitly loads the same file through the official action.
Roles are independent executions, without local Skills/custom subagent profiles.
Product/architecture rules remain in the canonical engineering/module documents.

## Four manual stages

Open Actions > Auron agents > Run workflow, on the repository default branch.
Only the configured human may dispatch. Each run performs one stage and stops:

| Stage | Inputs | Result |
|---|---|---|
| audit | Bounded scope | Zero to three Issue proposals; no automatic planning |
| plan | Issue number | Sources, ACs, validation, risks and permitted paths |
| implement | Issue, approved plan run ID, permitted paths | Change, fresh fast gate, draft PR |
| review | PR, approved delivery run ID, browser checkbox | Independent review/tests, separate full, evidence |

Read the report before approving the next stage. Planning does not authorize coding;
a draft PR does not authorize review/merge. Merge is manual. Put requirements in
Issue title/body; consolidate discussion decisions there before planning. No comment
commands, automatic transitions, schedules or automatic model retries.

Copy the numeric run ID from the approved report's Actions URL; the workflow
resolves its exact revision. For implementation copy comma-separated permitted
paths from the plan. Prefer exact files; directory prefixes end /. Paths bound
publication mechanically; the human/reviewer still checks semantic scope.
For a correction within the same plan, dispatch implement with the last delivery's
run ID and the same Issue. It updates only that PR with unchanged head/base/Issue.
Then explicitly dispatch review using the new delivery run ID.

Changed requirements, base/default branch, foreign/expired/incomplete approvals or
unexpected PR heads block stale work. Reconcile/replan explicitly. The MVP does not
rebase, force-push, delete/reopen branches/PRs or recover partial publication.
After a failure inspect Actions/artifacts AND existing branches/PRs before a new
dispatch. Job reruns are refused, including paid jobs. No automatic recovery chain.

## Configuration in GitHub

After authorized reviewed publication, ensure agents.yml is on the default branch.
Actions variables: AURON_APPROVER (one exact human login), AURON_BASE_BRANCH (main
or develop, default: default branch), and finally AURON_AGENT_ENABLED=true. Missing/
false disables new requests; cancel running workflows separately. One operation at
a time, with one pending slot in GitHub; this is not a durable queue.

Store a dedicated personal OpenAI project key as secret OPENAI_API_KEY_LUCAS.
The workflow uses only this secret with the standard OpenAI endpoint, without
automatic fallback. OPENAI_API_KEY_GL is an institutional gateway credential
and is not used here; using that gateway requires a separate compatibility review.
Never paste keys into chat/source/.env/logs. Check Responses API/model access,
billing and GitHub minutes/storage separately. Timeouts are not a dollar cap.
Check Actions policies and permission to
create PRs. No PAT/App is required by design. PR CI may need Approve workflows to run;
verify its actual integration SHA. Account changes/publishing require authorization.

The workflow explicitly selects gpt-6-sol with high reasoning effort for every role.
The Codex step allows five minutes for audit and 20 minutes for other roles.
No automatic switch to a larger model is configured. Keep the first audit focused
on AGENTS.md, .github/agents.md and this guide, then inspect actual API usage.
High effort prioritizes analysis; there is no hard per-run token or dollar cap.
Model access and a real agent run remain to be verified with the selected key.

## Boundaries and evidence

The read-only request records human identity, Issue requirements and exact revisions.
A successful same-workflow/default-control-revision run and immutable handoff identify
approvals. A bot comment/label alone never authorizes work. The model has no GitHub
write token. Paid jobs prepare trusted control tools only, never execute candidate
before the protected action, and never restore candidate-writable caches. Fast/full
run in fresh jobs without API keys. The publisher only calls GitHub APIs; it never
executes delivered scripts/hooks. No service/state database/custom agent platform.

Maximum: 60 regular UTF-8 text files, 200 KB/file and 1 MB total. Controls/instructions,
scripts, dependencies, migrations, secrets and frozen benchmarks require manual work.
Symlinks/submodules/nonportable paths are refused. The host's permission profile and
drop-sudo enforce access; role text alone does not. Audit/plan command network is off.
Implement/review need TCP, but external egress is not technically filtered. Only
trusted revisions, synthetic data, disposable DBs, fake providers and loopback app
requests are authorized. Real authentication and server-side tenancy remain intact.

Raw evidence: seven days; handoffs: 30 days, subject to repo limits. Retain generated
tests, logs, PNG/traces before expiry. Passed review needs checks for every approved
AC ID, retained scripts, cleanup and browser evidence when selected. Humans assess
assertion quality: structural checks cannot establish semantic truth. Failed/full-
incomplete/inconclusive results never approve. Missing output leaves failed Actions
jobs plus available artifacts. Incomplete cleanup blocks report publication too;
inspect raw artifacts in that case. No permanent business harness/auth bypass is added.

## Local commands

Provision PowerShell 7, Python 3.14, Node 24 and project dependencies explicitly:

```powershell
./backend/.venv/Scripts/python.exe -m unittest discover -s .github/scripts -p test_agents.py -v
./scripts/verify.ps1 -Mode fast
# Healthy Docker + postgres:17-alpine; only owned disposable resources:
./scripts/verify-disposable.ps1 -ProvisionTokenizer
python scripts/create_module.py --key example --name Example --dry-run
python scripts/validate_module.py competitive_intelligence
```

Use -Python <absolute-python> to reuse a provisioned environment in a worktree.
Fast installs nothing/starts no services. Full adds all backend tests and frontend
build, with distinct disposable TEST_DATABASE_URL and real tokenizer assets. The
helper never uses normal Compose volumes. Do not delete normal volumes/reset Docker
to recover. Worktrees share Docker, ports, databases and credentials.
Existing regressions remain; new agent exploration stays in run evidence.

For an explicitly requested handoff, scripts/collect_context.py collects facts and
writes no snapshot. Export the report outside the checkout or as an ignored artifact,
never as canonical documentation. Its read-only Alembic current probe requires an
explicitly authorized database/environment. There is no automatic handoff.

Local tests do not prove the remote action/profile. Operational closure requires
authorized publication, real GitHub CI, a small real Issue through all human stages,
a correction/review cycle, evidence inspection and manual merge. One agent workflow;
no parallel legacy pilot.

References: [official Codex action](https://learn.chatgpt.com/docs/github-action),
[manual Actions dispatch](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).
