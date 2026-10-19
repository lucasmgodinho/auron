---
name: auron-diagnose
description: Diagnose an Auron defect or engineering-readiness gap using repository evidence and bounded checks before proposing changes.
---

Read AGENTS.md, its mandatory rules and the source index in docs/AI_FIRST_WORKFLOW.md.
Record the Git root, HEAD and dirty/untracked scope before investigation. Treat
conversation diagnoses as hypotheses; trace the actual imports/callers and tests.
If delegation was requested, assign one bounded read-only task to auron_explorer.
Keep baseline reproduction separate from proposed remediation. Do not run startup,
migrations, live providers or benchmark writers as diagnostic checks.
Return prioritized findings with file/symbol evidence, reproduction, affected
invariant, smallest viable change, acceptance tests and unmet prerequisites.
Do not present inspected tests as executed tests or unavailable metrics as zero.
