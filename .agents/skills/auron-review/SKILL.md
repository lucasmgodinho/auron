---
name: auron-review
description: Independently review a specified Auron change for correctness, tenant authorization, architecture, secret exposure and missing test coverage.
---

Read AGENTS.md and its source index. Obtain the explicit reviewed file list and
baseline; distinguish pre-existing dirty work from the assigned delta. Review
implementation, callers, tests and check evidence directly. Do not edit files.
Prioritize reproducible behavior/security defects over style: Organization context,
module entitlement, Access Groups, streaming cleanup, secrets, immutable benchmarks
and production/test divergence. Test doubles do not establish tokenizer parity.
Inspect verification scripts for failure propagation and unintended setup/DB work.
Return actionable findings with severity, file/line, failure scenario and missing
test. State no findings when appropriate, plus checks not run and residual risks.
The implementer owns fixes; independently recheck material corrections on request.
