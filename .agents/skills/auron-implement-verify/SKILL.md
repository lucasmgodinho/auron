---
name: auron-implement-verify
description: Implement a bounded Auron fix with acceptance criteria, targeted regression checks, deterministic verification and an independent review loop.
---

Read AGENTS.md and docs/AI_FIRST_WORKFLOW.md. Reconfirm the baseline and isolate
your delta from existing work. State observable acceptance and side effects first.
Read the relevant architecture/module contract and use auron-module for material
module changes. Preserve production semantics, tenancy, streaming and frozen data.
Add regression tests for meaningful failure paths and behavior; use real tokenizer
assets for token/chunk parity, never substitute approximate tokenization.
Run focused tests and scripts/verify.ps1 -Mode fast. Run full only with its explicit
prerequisites; never bootstrap DBs, install packages or call providers to make a
verification gate appear green. A failed gate keeps the change unverified.
When authorized and available, give auron_reviewer the scope and raw evidence,
without an intended verdict. Correct actionable findings and rerun affected gates.
Report the final delta, commands/exit codes, review disposition and limitations.
