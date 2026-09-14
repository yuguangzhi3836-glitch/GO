# C13 next-depth independent acceptance preparation

Task `V70-R2-C13-02`; agent `/root/c13_independent`.
Main lineage `fef9c748adb77d37ba5d4dc4fa4662eb668303a1`; inherited PR73 commit `a274f77e4c1479fb143cdc7ef45d63b9c4f8cc1b`. The inherited 1341 application files were independently checked against the preserved PR73 manifest and `../pr73-baseline/application`; every SHA256 matched. No final-candidate acceptance test has run.

## Entry conditions and independent execution

1. Root supplies a frozen next-depth candidate manifest with full source SHA256, application Git tree and paths/modes/blob hashes. Check all inherited modifications/new files/deletions, including exclusion of accidental `application/application/`, caches and runtime databases.
2. Root updates Draft PR73 with the frozen candidate, executes all five required CI jobs including PostgreSQL 18.4, and reads back the actual source-bound originals. Inspect original logs/JUnit/exit status and process records, not a status badge or artifact metadata alone. Failed CI must be corrected before final review; missing/skipped PostgreSQL remains HOLD.
3. C14 reviews that precise candidate and the actual CI originals, then supplies its final review record, checksum and actual completion time. Root explicitly authorizes C13 to execute after that final C14 record. This document is a proposed acceptance plan, not C14 or C13 PASS.
4. C13 checks exact source and evidence identities before execution, then runs only selected new-depth risks and necessary adjacent regressions. Use the available Python3.12 interpreter, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=src`, `-p no:cacheprovider`, a distinct `/tmp` SQLite database and unchanged default worker settings. Cross-process tests must preserve real process IDs/exits and checkpoint facts.
5. Record command/cwd/environment/start/end/raw log/JUnit and before/after source hashes. Tests, CI and reviews keep distinct timestamps and roles. No borrowed upstream run is described as C13 execution.

## Risk-selected independent checks

| Cell | Independent focus | Evidence or test boundary |
| --- | --- | --- |
| C01 | Unknown mixed-credit/cash outcome remains recoverable without restoring forfeiture or extending original expiry | Inspect new fault injection and precise persisted accounting assertions; select the new three cases only |
| C02 | Partial passenger/coupon planning preserves explicit allocation, unselected identity and receipt mapping | Pure planner cases only. HTTP integration, persistence, supplier execution and settlement are unproved |
| C03 | Payment/expiry ordering and exhausted target inventory cannot double-allocate or authorize an unsupported supplement | New deterministic race cases and resulting SQL inventory/payment facts; actual concurrency claims require PG original |
| C04 | Historical rental refund assessment never changes state or moves money | Read-only SQL guard, foreign-owner denial and exact frozen-plan receipt diagnostics |
| C05 | Self-consistent rehashed UNKNOWN evidence with wrong supplier reference or missing actor/evidence still cannot restore a ride phase | New independent corruption cases augment existing chain/payload/phase cases; state and evidence count remain unchanged |
| C06 | A supplier-confirmed date change continues using the original frozen timezone policy even if the live catalog changes | Independent combined date-change/catalog-drift case; retained half-open time boundary, refund exclusion and missing-contract guards |
| C07 | Withdrawal is ordered against reads/writes; committed data survives actual process death, uncommitted changes do not | Distinct process records, gate release ordering and an expiry/read boundary selected after final process helpers freeze. PG and SQLite evidence kept separate |
| C08 | Abrupt death leaves ROUTING unresolved; read-only assessment never repeats compute or invents completion | Three real hard-exit checkpoints. This establishes inspection, not automatic recovery |
| C09 | Rejected derived-field override preserves existing truth; first invalid request must not accidentally bootstrap state; same-hotel locks and hook result bindings retain one current judgment | C14 requested a focused bootstrap regression. Original/replayed hook result identity and new concurrency evidence. Transaction-external event delivery remains separate |
| C10 | Batched current-state projection keys by vertical, owner and order together | Independent mixed-vertical same-order-ID projection case; retain ownership/membership/fallback behavior and bounded query count evidence |
| C11 | Failed recovery validation cannot release the original uncertain claim; wrong returned payment receipt cannot fabricate success or duplicate money on retry | Independent opted-in wrapper boundary case and real flight checkout receipt corruption/retry. Include exact two-flight post-commit cases, safe/token/legacy tests and PG source-bound evidence |
| C12 | Local ACK/start/output admission cannot turn mismatched or unbound metadata into worker authentication/liveness | Independent wrong-task or tampered-output receipt check; scheduler source gate and actual dispatch records audited separately |
| C13/C14 | Exact lineage, evidence integrity, scope and review order | No self-issued future gate; final review uses the requested machine-readable schema and each Cell's exact finite denominator |

## Mandatory remaining denominators

- C02 remains an isolated plan/preview. It does not accept partial-passenger HTTP booking changes.
- C08's `assess_recovery` is read-only. ROUTING ownership, dead-worker proof, resumable output and automatic recovery remain HOLD.
- C11 is opted into FLIGHT_CHECKOUT and FLIGHT_EXECUTE_CHANGE only. The other 35 generic callsites and original generic 2 FAIL remain separate. Hard-killed RUNNING claim recovery is deliberately unproved; no timeout takeover is inferred.
- C09 canonical judgment/hook concurrency does not prove durable transaction-external event delivery.
- C06 real suppliers without a verified policy remain LEGACY_UNVERIFIED. Synthetic frozen-policy tests do not establish a real vendor policy.
- C10 query batching does not establish pagination, bounded result memory or Hong Kong load capacity.
- C12 verifies local record consistency; strings and checksums are not authenticated worker identity or a heartbeat.
- PostgreSQL CI passes count only after reading the actual source-bound originals; no local PostgreSQL execution is claimed.
- No image, browser/physical-device, real supplier/funds or HK/Production deployment gate is implied.

## Final result form

Use `reviewer`, `reviewer_cell`, `status`, actual `completed_at`, `source_anchor`, `parent_candidate_commit`, `application_git_tree`, `source_tree_sha256`, exact `candidate_manifest`, exact `c14_record`, and `cell_outcomes` C01–C14. Every outcome supplies `task_id`, PASS_SCOPED or HOLD, actual finite `scope`, explicit `holds`, and a concrete `next_task`. Additional run/JUnit/identity and known-failure records remain separate. No final verdict is issued during preparation.
