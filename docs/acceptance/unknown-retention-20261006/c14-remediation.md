# C14-CC-001 correction and bounded PostgreSQL evidence plan

Prior candidate: 538ba2898621e9d47fe54e0900bb6be0b4308746.
Prior review: issue532, run37475658020 attempt1, job112310267932.
C14_ROOT: faa9be238d6adf90c57cba5ad6237fd33ee644cb12b8e9f24f859d61cd55440b.
Verdict: FAIL, remediation OPEN. The original opinion remains immutable.
Artifact11419920601 ZIP SHA256: 4413c7b0a9dac556bacec73bfbbcabba52cb1187b04e9bcf91a0201919d669d1.

## Correct semantic classification

Applicable classes for the complete PR are PRODUCT_FEATURE, PRODUCT_FIX,
MIGRATION, BUILD, TEST_ONLY, and DOCUMENTATION. This is not merely a bug fix:
relative to main it adds a new internally observable recovery capability,
two HTTP operations, and application authorization enforcement.

Application authority boundary change: the new open/resolve HTTP operations
require an active database-backed finance user/session and a reserved operations
grant for the reservation's actual hotel. Global admin identity alone is
insufficient. A grant for another hotel or a revoked grant is denied. The
current public staff-role form cannot create the reserved role. Checks run in
the same transaction as recovery. Existing administrative operations are not
retroactively tightened by this PR. Trusted internal Python service callers
retain the historical actor-ID calling convention, but remain isolated-only.
No new control-plane signing, deployment authority, runtime task authority or
real-hotel delegation provisioner is added. These application checks do not
constitute authorization to migrate, merge, deploy or execute real payments.

## Remediation and new evidence scope

The classification and authority description above correct C14-CC-001. Only a
new independent opinion can close that finding; this document does not claim
review PASS. Original application implementation/test bytes are unchanged.
The prior 22 local SQLite test results remain bound to their recorded file
hashes, not falsely relabeled as a PostgreSQL or new independent review result.

A dedicated PR CI workflow now uses disposable PostgreSQL18.4 and a narrowly
loaded pytest plugin. After the legacy conftest selects SQLite, the plugin
explicitly selects only go_unknown_isolated on loopback5432 with go_ci,
requires the disposable-mode flag, and aborts if application DB/config has
already been imported. Before any test fixture schema reset it reads actual
server_version_num=180004 and current_database(), and verifies the application
engine uses that connection. Its artifact records the actual dialect/version,
source SHA, application tree, migration and pytest exit codes, logs and JUnit.
The job upgrades the fresh disposable database through the current migration
head and then runs only the 15 UNKNOWN/funding cases. It does not run ABBA,
capacity testing, the historical suites, or live endpoints. The 7 migration
history cases in ordinary C13 remain explicitly SQLite; they are not counted
as PostgreSQL cases. PostgreSQL status is NOT_RUN until raw CI is read back.

Offline guard check: an explicit SQLite URL is rejected with
UNKNOWN_DISPOSABLE_DATABASE_REQUIRED before DB import/reset. Real-provider
reconciliation, real hotel delegation, full R8-15/business day and original18
complete acceptance remain UNPROVEN/BLOCKED. No model-budget increase.
