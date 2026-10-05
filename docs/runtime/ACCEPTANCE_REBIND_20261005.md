# Acceptance source binding repair — candidate

Change classes: BUILD, TEST_ONLY, DOCUMENTATION.

## Confirmed cause

At PR425 head 21417bb6fc36b89320dcb6a922b66dd532bff5ff, all four failed workflows
first rejected the same six unexpected paths in ci/retention/verify_source.py:

- Canonical parent retention: run 37249559181 (all five executing jobs).
- V7 Cell scoped gap closure: run 37249559268.
- V7 next depth PostgreSQL recovery: run 37249559358 (C07/C09/C11).
- DEPTH48 ordered repair acceptance: run 37249559229 (browser/PostgreSQL).

The old manifest bound the September 14 application tree. A full tree comparison
found six added and eight changed paths, not merely six missing registrations.
Twelve paths came from current main ee4a0a4ea4c9a95b7017b8db991de7554962f42a;
two came from PR425. REBIND_20261005.json records their exact blobs and origins.

The repair additionally updates two stale current-head test expectations to0135.
A real test exposed a partial rail fixture using upgrade(head): it has no identity
schema and cannot exercise0135. That historical fixture now explicitly upgrades
to0134, preserving its original width/downgrade scope. The separate fresh-install
test still upgrades the entire chain to actual head0135. No migration code changed.
All16 deltas and the resulting1371-file tree are bound, not automatically accepted.

## Scope and non-transfer of old results

- Rebind three active manifests; retain inherited manifests and historical evidence.
- Preserve full file-set, per-file blob, application-tree and alignment checks.
- Record repository migration head0135; no live database claim or migration.
- Rename old current-delta fields to historical fields, record current exact delta.
- Replace canonical test !cancelled() conditions with success().
- Write outcome-only stage receipts even after failure, without step outputs/secrets.
  NO_PRIOR_STEP_FAILURE is explicitly not acceptance PASS.
- No API quota, permission, network, Runtime queue, business behavior or deployment change.

## Local validation

Python3.13.5; all37 repository-frozen wheels extracted and installed offline.
Exact source binding and inherited alignment PASS at source commit
97e871f48e3c89b7e0642104d141e7ce1c37d1d4.
Migration files:12 pytest cases PASS; stage receipt:2 unittest cases PASS.
Three modified-byte negative probes rejected, with original files restored.
All four workflow YAML structures parsed and step IDs are unique.
Evidence in evidence/acceptance-rebind-20261005 is LOCAL_ONLY and does not claim
GitHub CI, browser, PostgreSQL, C14/C13 or Builder sandbox acceptance.

## Independent review

A separate read-only reviewer examined PR425 exact head and this repair.
It found the two stale migration assertions and old current-delta metadata;
these were corrected. PR425 itself remains a controlled live-validation candidate.
Its sandbox smoke is prompt-required, not a machine-enforced attestation; dependency
preparation can fail before producing its structured host report. Single-task
validation must inspect the actual same-run agent log and evidence; unattended
batch remains HOLD until these evidence-enforcement gaps are addressed.
This code review is not formal Runtime C14/C13 acceptance.

## Next gate

Read CI on the exact final repair head. Do not merge without approval, do not
replay407–418, and do not transfer old acceptance to the rebound tree. After an
approved merge, read new main and issue one fresh bounded task only. The expected
chain remains Builder -> Draft PR -> C14 -> C13 -> original-task receipt.
No part of that new-main live chain has run in this repair.
