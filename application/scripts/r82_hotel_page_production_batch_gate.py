#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
svc=(ROOT/'src/go_hotel/services/hotel_page_production_acceptance.py').read_text(encoding='utf-8')
cli=(ROOT/'scripts/r82_hotel_page_production_batch_acceptance.py').read_text(encoding='utf-8')
release=(ROOT/'scripts/release_gate_r82.sh').read_text(encoding='utf-8')
manifest=(ROOT/'CURRENT_RELEASE_MANIFEST.json').read_text(encoding='utf-8')
checks={
 'levels_1_100_1000':'LEVELS = (1, 100, 1000)' in svc,
 'staging_only':'RC13_ACCEPTANCE_STAGING_ONLY' in svc and 'RC13_ACCEPTANCE_STAGING_ONLY' in cli,
 'previous_level_gate':'RC13_ACCEPTANCE_LEVEL_LOCKED_PREVIOUS_' in svc,
 'before_after_stats':'"before": before' in svc and '"after_run": after_run' in svc,
 'idempotent_replay':'idempotent_replay' in svc and 'replay_counts' in svc,
 'duplicate_guard':'no_duplicate_entities' in svc and 'external_identity_exactly_one_canonical' in svc and '_batch_identity_audit' in svc,
 'snapshot_check':'source_snapshot_present' in svc,
 'rights_fail_closed':'rights_fail_closed' in svc and 'RIGHTS_UNKNOWN' in svc and 'rights_checked_count == level' in svc and 'blocked_media_count == level' in svc,
 'page_rebuild':'page_rebuild_idempotent' in svc,
 'claim_takeover':'claim_takeover_same_entity' in svc,
 'go_direct_preserved':'go_direct_upgrade_preserved' in svc,
 'orphan_check':'no_new_orphans' in svc and 'orphan_rows' in svc,
 'retry_recovery':'failure_retry_recovery' in svc and '_exercise_failure_retry_recovery' in svc and 'retry_job' in svc,
 'cleanup_baseline':'cleanup_baseline_restored' in svc and '"seed_count"' in svc and '"retry_count"' in svc and '"failed_count"' in svc,
 'explicit_confirmation':'RUN-RC13-' in cli,
 'release_gate_wired':'r82_hotel_page_production_batch_gate.py' in release,
 'manifest_slice3':'SLICE_3_BATCH_ACCEPTANCE' in manifest,
 'no_migration_claim':'"revision_count": 112' in manifest and '0112_ti_p0_20260829' in manifest,
}
failed=[k for k,v in checks.items() if not v]
for k,v in checks.items(): print(f'{k}={"PASS" if v else "FAIL"}')
if failed: raise SystemExit('R8.2_HOTEL_PAGE_PRODUCTION_BATCH_GATE: FAIL '+','.join(failed))
print('R8.2_HOTEL_PAGE_PRODUCTION_BATCH_GATE: PASS')
