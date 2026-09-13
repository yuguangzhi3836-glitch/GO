from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
svc=(ROOT/'src/go_hotel/services/hotel_discovery_orchestrator.py').read_text(encoding='utf-8')
routes=(ROOT/'src/go_hotel/api/routes/hotel_autopage_factory.py').read_text(encoding='utf-8')
models=(ROOT/'src/go_hotel/db/models.py').read_text(encoding='utf-8')

checks={
 'discovery_orchestrator': 'class HotelDiscoveryOrchestratorService' in svc,
 'seed_registry': 'def register_seed' in svc and 'DISCOVERY_SEED_REGISTERED' in svc,
 'multi_source_map': all(x in svc for x in ['OFFICIAL_WEBSITE','GROUP_OFFICIAL','OTA_DISCOVERY','SEARCH_RESULT','MAP_DIRECTORY','DATA_PROVIDER']),
 'safe_http_fetch': 'DISCOVERY_SOURCE_PRIVATE_OR_SPECIAL_BLOCKED' in svc and 'trust_env=False' in svc and 'follow_redirects=False' in svc,
 'structured_parser': '_extract_payload' in svc and 'application/ld+json' in svc,
 'entity_resolution_reuses_autopage': 'hotel_autopage_factory_service.ingest' in svc,
 'source_snapshot_existing_table': 'HotelContentSourceSnapshotRow' in svc and "__tablename__='hotel_content_source_snapshot'" in models,
 'snapshot_idempotency': "UniqueConstraint('source_key','external_hotel_id','payload_hash'" in models,
 'retry_events': 'DISCOVERY_JOB_RETRY_REQUESTED' in svc and 'DISCOVERY_SOURCE_FAILED' in svc,
 'media_candidate_only': 'media_candidates' in svc and 'RIGHTS_UNKNOWN' in svc and 'media_harvester_service.harvest' not in svc,
 'batch_entry': 'def run_batch' in svc and '/internal/v1/hotel-discovery/batches/run' in routes,
 'job_status': '/internal/v1/hotel-discovery/jobs/{job_id}' in routes and 'def job_status' in svc,
 'no_payment_in_slice': not re.search(r'payment(_|\s)*intent|capture\(|refund\(', svc, re.I),
 'no_new_discovery_model': 'class HotelDiscovery' not in models and 'class DiscoveryJob' not in models,
}
failed=[k for k,v in checks.items() if not v]
for k,v in checks.items(): print(f'{k}={"PASS" if v else "FAIL"}')
if failed: raise SystemExit('R8.2_HOTEL_DISCOVERY_SLICE1_GATE: FAIL '+','.join(failed))
print('R8.2_HOTEL_DISCOVERY_SLICE1_GATE: PASS')
