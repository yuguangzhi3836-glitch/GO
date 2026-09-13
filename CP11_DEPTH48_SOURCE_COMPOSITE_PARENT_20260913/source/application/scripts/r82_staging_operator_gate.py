#!/usr/bin/env python3
from pathlib import Path
import json, os, sys, tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
fd,path=tempfile.mkstemp(prefix='go_rc171_',suffix='.db'); os.close(fd)
os.environ['DATABASE_URL']=f'sqlite+pysqlite:///{path}'

from go_hotel.db.models import AuditEventRow
from go_hotel.db.session import engine
from go_hotel.services.staging_execution_evidence_orchestrator import staging_execution_evidence_orchestrator as orch, STAGES
from go_hotel.services.staging_operator import staging_operator_service as op

checks={}
original=orch.verify_stage
try:
    AuditEventRow.__table__.create(engine, checkfirst=True)
    st=op.operator_status()
    checks['status_exposes_checkpoint']=st['next_checkpoint']=='PRECHECK' and st['current_checkpoint'] is None
    checks['status_exposes_blockers']='RDS_LINEAGE_RUNTIME_ATTESTATION_REQUIRED' in st['blockers']
    checks['status_exposes_missing_evidence']=any(x['blocker']=='RDS_LINEAGE_RUNTIME_ATTESTATION_REQUIRED' for x in st['missing_evidence'])
    try:
        op.seal_checkpoint('PRECHECK')
        checks['cannot_seal_unpassed_checkpoint']=False
    except ValueError as e:
        checks['cannot_seal_unpassed_checkpoint']='CHECKPOINT_NOT_GO_CANNOT_SEAL' in str(e)

    orch.advance('PRECHECK','admin','evidence://rds/actual-lineage',rds_lineage_attested=True)
    seal=op.seal_checkpoint('PRECHECK')
    checks['seal_is_go_only']=seal['decision']=='GO' and seal['stage']=='PRECHECK'
    checks['seal_bound_to_source_hash']=bool(seal['source_entry_hash']) and bool(seal['source_content_hash'])
    checks['seal_never_live']=seal['candidate_not_deployed'] is True and seal['production_live'] is False
    checks['seal_has_digest']=len(seal['artifact_sha256'])==64

    # Advance controlled fixtures only to prove export/seal mechanics; this is not external execution evidence.
    orch.verify_stage=lambda stage:([],{'gate_fixture':stage,'production_live':False})
    for stage in STAGES[1:]: orch.advance(stage,'admin',f'evidence://gate/{stage.lower()}')
    bundle=op.export_bundle()
    checks['bundle_complete']=bundle['chain']['complete'] and bundle['operator_status']['complete']
    checks['bundle_chain_valid']=bundle['chain']['chain_valid'] and bundle['operator_status']['chain_valid']
    checks['bundle_never_live']=bundle['production_live'] is False and bundle['candidate_not_deployed'] is True
    checks['bundle_digest']=len(bundle['bundle_sha256'])==64
    finalseal=op.seal_checkpoint('PAYMENT_SANDBOX')
    checks['final_seal_still_not_live']=finalseal['production_live'] is False
    with tempfile.TemporaryDirectory() as td:
        result=op.write_json_artifact(bundle,Path(td)/'bundle.json')
        checks['artifact_sidecar']=Path(result['artifact_path']).exists() and Path(result['sha256_path']).exists() and len(result['file_sha256'])==64
finally:
    orch.verify_stage=original
    engine.dispose()
    try: os.remove(path)
    except Exception: pass

source=(ROOT/'src/go_hotel/services/staging_operator.py').read_text()
route=(ROOT/'src/go_hotel/api/routes/staging_execution_evidence.py').read_text()
cli=(ROOT/'scripts/r82_staging_operator.py').read_text()
checks.update({
    'cli_status_export_seal': all(x in cli for x in ['"status"','"export"','"seal"']),
    'admin_api_operator_wired': all(x in route for x in ['/operator/status','/operator/export','/operator/checkpoints/{stage}/seal']),
    'seal_cannot_create_go': 'advance(' not in source,
    'no_new_migration': not any('rc17_1' in p.name.lower() or 'rc171' in p.name.lower() for p in (ROOT/'alembic/versions').glob('*.py')),
})
for k,v in checks.items(): print(f'{k}={"PASS" if v else "FAIL"}')
if not checks or not all(checks.values()): raise SystemExit(1)
print('R8.2_RC17_1_STAGING_OPERATOR_GATE: PASS')
