# C08 round two execution evidence

Source anchor: `main fef9c748adb77d37ba5d4dc4fa4662eb668303a1`.
The root coordinator verified the materialized application file-by-file; this
local workspace has no `.git` object database. Per-command source SHA256 values
bind the actual executed files. Candidate is local and awaits C14 then C13.

## Result

The baseline left a request `ROUTING` when the successful final-audit transaction
failed before commit. `red.xml`: 2 tests, 1 failure and 1 pass. The minimal
candidate now makes one fresh transaction to mark an unresolved request
`FAILED / GO_AI_AUDIT_FINALIZATION_FAILED`. It never calls the provider again,
propagates the original error and preserves an already committed terminal audit
when only the acknowledgement failed.

`green.xml`: 14 passed, no skips/errors/failures. This covers 3 new transaction
failure boundaries, the 3 inherited synthesis-audit tests, and 8 existing
multi-model tests. The new tests use deterministic providers and real local
SQLite transactions; they are not live-provider or Hong Kong acceptance.

Persistent audit storage failure still leaves `ROUTING` and returns an error.
No recovery worker or process-interruption guarantee is claimed. Next C08 task:
process termination after request-audit persistence and restart-safe closure,
without re-executing external compute.

## Delivery state

Current finite task: code + local tests + evidence ready. Execution chain 4/6;
C14 and C13 remain unsigned and pending independent review. This is not a claim
of 100% C08 domain completion. `EXECUTION.json` contains the next assigned task.

`red_probe_source.py` retains the exact red test bytes before the additional
commit-acknowledgement boundary test was introduced. Command JSON files record
the distinct controller and test interpreter versions; test Python was 3.12.14.
