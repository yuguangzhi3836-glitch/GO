# HK DEPTH10 one-shot acceptance sequence

Run only on Hong Kong Staging against the sealed DEPTH10 candidate. Do not run on production.

## Fail-closed order

1. Confirm candidate SHA and source-tree manifest. Abort on mismatch.
2. Confirm application DB dialect is PostgreSQL and record `select version()` plus current Alembic head. Do not mutate schema in this gate.
3. Ensure `GO_HOTEL_ALLOW_LEGACY_REDIS_REGIONAL_WORKER` is unset/false. Import `production_bindings.production_authorities()` and require:
   - regional_queue = POSTGRES_DURABLE_LEASE_ACK
   - legacy_redis_default = false
   - media_metadata = POSTGRES_DURABLE_MEDIA_LEDGER
   - media_local_json_authority = false
   - release_safe = true
4. Run `acceptance/release_static_legacy_guard.py` against the assembled production source tree. Any RedisQueue production import, old regional enqueue or old MediaHarvester authority => HOLD.
5. Run `acceptance/run_postgres_crash_recovery.py`. Preserve stdout JSON, exit code and DB version. Any failed assertion => HOLD.
6. Run `acceptance/run_hyatt_10_real_e2e.py`. Preserve the official directory URL, snapshot SHA, automatically selected ten-property cohort and durable task IDs. No manual cohort substitution.
7. Drain exactly the cohort tasks through deployed chain workers. Force-kill at least one worker after LEASED and before ACK; demonstrate expiry/reclaim and one terminal ACK.
8. For all ten hotels capture official-room catalog parity, room facts, room-specific media, hotel-wide scene media, durable media ledger records, idempotent rerun evidence and last-known-good protection.
9. Run real browser validation at 375/390/430 CSS px and representative desktop. Attach screenshots and visual/a11y/task-step evidence.
10. Only if all prior gates PASS may `HOTEL_REPLICATION_GATE` advance. `FINAL_RELEASE_GATE` remains separate.

## Evidence bundle minimum

`candidate.json`, `postgres_crash_recovery.json`, `hyatt_10_cohort.json`, `task_history.json`, `hotel_results/*.json`, `browser/*`, `production_authorities.json`, `legacy_guard.json`, exact commands, UTC timestamps and exit codes.

No test order may be skipped and no HOLD may be converted to PASS manually.
