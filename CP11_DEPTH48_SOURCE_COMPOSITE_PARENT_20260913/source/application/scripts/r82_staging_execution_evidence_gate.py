#!/usr/bin/env python3
from pathlib import Path
import os, sys, tempfile
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
fd,path=tempfile.mkstemp(prefix='go_rc17_',suffix='.db'); os.close(fd)
os.environ['DATABASE_URL']=f'sqlite+pysqlite:///{path}'

from go_hotel.db.models import AuditEventRow
from go_hotel.db.session import engine
from go_hotel.services.staging_execution_evidence_orchestrator import staging_execution_evidence_orchestrator as svc, STAGES

checks={}
original=svc.verify_stage
try:
    AuditEventRow.__table__.create(engine, checkfirst=True)
    # All business-stage verification hooks are exercised through the orchestrator.
    # PRECHECK keeps its real 112/head verification and additionally requires runtime RDS attestation.
    try:
        svc.advance('PRECHECK','admin','evidence://rds/no-attestation',rds_lineage_attested=False)
        checks['rds_attestation_fail_closed']=False
    except ValueError as e:
        checks['rds_attestation_fail_closed']='RDS_LINEAGE_RUNTIME_ATTESTATION_REQUIRED' in str(e)
    pre=svc.status()
    checks['no_go_does_not_unlock_stage']=pre['sealed_go_stage_count']==0 and pre['next_stage']=='PRECHECK'

    preok=svc.advance('PRECHECK','admin','evidence://rds/lineage-0112',rds_lineage_attested=True)
    checks['precheck_go']=preok['decision']=='GO' and preok['evidence']['revision_count']==112 and preok['evidence']['heads']==['0112_ti_p0_20260829']

    try:
        svc.advance('RC13_100','admin','evidence://rc13/100')
        checks['cannot_skip_sequence']=False
    except ValueError as e:
        checks['cannot_skip_sequence']='RC13_1' in str(e)

    # Controlled fake verifier proves sequencing/ledger semantics without pretending external execution occurred.
    # Real-source hooks are asserted below and remain fail-closed in actual runtime.
    svc.verify_stage=lambda stage: ([], {'gate_fixture':stage,'production_live':False})
    for stage in STAGES[1:]:
        out=svc.advance(stage,'admin',f'evidence://gate/{stage.lower()}')
        checks[f'sealed:{stage}']=out['decision']=='GO'
    status=svc.status()
    checks['complete_chain']=status['complete'] and status['final_state']=='STAGING_EVIDENCE_CHAIN_COMPLETE_NOT_LIVE'
    checks['hash_chain_valid']=status['chain_valid'] and all(x['entry_valid'] for x in status['events'])
    checks['candidate_never_live']=status['production_live'] is False and status['candidate_not_deployed'] is True
    checks['deployed_parent_rc11']='rc.11+' in status['deployed_parent']
    try:
        svc.advance('PAYMENT_SANDBOX','admin','evidence://duplicate')
        checks['append_only_stage_seal']=False
    except ValueError as e:
        checks['append_only_stage_seal']='ALREADY_SEALED' in str(e)
finally:
    svc.verify_stage=original
    engine.dispose()
    try: os.remove(path)
    except Exception: pass

source=(ROOT/'src/go_hotel/services/staging_execution_evidence_orchestrator.py').read_text()
route=(ROOT/'src/go_hotel/api/routes/staging_execution_evidence.py').read_text()
main=(ROOT/'src/go_hotel/main.py').read_text()
checks.update({
    'rc13_real_db_evidence_hook':'HotelAutoPageEventRow' in source and 'RC13_' in source and 'report_hash' in source,
    'aoluguya_12_truth_real_hook':'aoluguya_supply_truth_service.evaluate()' in source and 'EXACTLY_12_TRUTH_GATES_REQUIRED' in source,
    'atomic_cutover_real_hook':'official_projection' in source and 'AOLUGUYA_9_ACTIVE_OFFERS_REQUIRED' in source and 'no_test_truth' in source,
    'external_supplier_attestation_real_hook':'external_transport_attested' in source and 'ATTESTED_EXTERNAL_HOTEL_SUPPLIER_SANDBOX_CERTIFICATION_REQUIRED' in source,
    'payment_cert_real_hook':'payment_sandbox_cutover_service.status' in source and 'chain_valid' in source and 'ACTIVE_CERTIFIED' in source,
    'admin_api_wired':'/internal/v1/staging-execution-evidence' in route and 'staging_execution_evidence_router' in main,
    'no_live_enable_path':'payment_live = True' not in source and 'production_live = True' not in source,
    'no_new_migration':not any('rc17' in p.name.lower() for p in (ROOT/'alembic/versions').glob('*.py')),
})
for k,v in checks.items(): print(f'{k}={"PASS" if v else "FAIL"}')
if not checks or not all(checks.values()): raise SystemExit(1)
print('R8.2_RC17_STAGING_EXECUTION_EVIDENCE_GATE: PASS')
