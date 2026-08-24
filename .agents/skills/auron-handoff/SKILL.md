---
name: auron-handoff
description: Generate a current, source-backed Auron repository handoff for another AI that cannot inspect the repository or prior conversations. Use only when explicitly requested.
---

# Auron AI Handoff

Generate `.ai/AURON_HANDOFF.md` only when the user explicitly requests an AI/project handoff.
Never reuse conversation memory as repository truth.

1. Run `scripts/collect_context.py` for deterministic Git, Alembic, registry, and path facts.
2. Read the current `AGENTS.md`, `README.md`, `docs/ARCHITECTURE.md`,
   `docs/MODULE_CONTRACT.md`, and the relevant implementation/tests.
3. Read [`references/handoff-outline.md`](references/handoff-outline.md) and write a concise
   2,500–4,000 word snapshot to `.ai/AURON_HANDOFF.md`.
4. Cross-check important claims against source paths and confirm that planned/deferred behavior is
   never presented as implemented.

Do not include `.env` contents, environment values, credentials, tokens, hashes, secrets, or large
source dumps. The snapshot is generated and non-canonical: do not commit it or replace canonical
documentation with it.
