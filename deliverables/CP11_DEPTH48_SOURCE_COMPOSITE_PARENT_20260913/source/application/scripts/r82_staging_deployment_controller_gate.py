#!/usr/bin/env python3
from __future__ import annotations
import importlib.util, json, os, subprocess, tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('ctl', ROOT/'scripts'/'r82_staging_deployment_controller.py')
ctl=importlib.util.module_from_spec(spec); spec.loader.exec_module(ctl)

def require(v,msg):
    if not v: raise SystemExit('R8.2_RC17_2_STAGING_DEPLOYMENT_CONTROLLER_GATE: FAIL '+msg)

with tempfile.TemporaryDirectory() as td:
    ctl.STATE_DIR=Path(td)
    original_run=ctl.run
    original_status=ctl.operator_status
    try:
        ctl.run=lambda *a,**k: {'command':['mock'],'exit_code':0,'stdout':'PASS','stderr':''}
        os.environ['DATABASE_URL']='postgresql+psycopg://mock'
        require(ctl.preflight()==0,'mocked preflight should pass')
        ok,data=ctl.verify_preflight_artifact(); require(ok,'preflight seal should verify')
        require(data['expected_revision_count']==112 and data['expected_head']=='0112_ti_p0_20260829','frozen lineage missing')

        require(ctl.deploy_plan('latest')!=0,'latest tag must be rejected')
        require(ctl.deploy_plan('registry/go:sha256-abc')==0,'immutable tag plan should pass after preflight')
        plan=json.loads((Path(td)/'DEPLOY_PLAN.json').read_text())
        require(plan['migration_command_included'] is False,'deploy plan must exclude migration')
        require(plan['alembic_stamp_forbidden'] is True,'no-stamp must be explicit')
        require('docker-compose.staging.rc172.override.yml' in ' '.join(plan['commands']),'immutable-image compose override required')

        ctl.operator_status=lambda: {'current_checkpoint':'RC13_100','next_checkpoint':'RC13_1000','chain_valid':True,'blockers':[]}
        require(ctl.resume()==0,'resume should pass on valid seal/chain')
        resume=json.loads((Path(td)/'RESUME.sealed.json').read_text())
        require(resume['resume_from_checkpoint']=='RC13_1000','resume must use next checkpoint')

        require(ctl.abort('operator requested stop','codex')==0,'abort failed')
        require(ctl.resume()!=0,'resume must fail after abort')
        require(ctl.deploy_plan('registry/go:sha256-abc')!=0,'deploy plan must fail after abort')

        require(ctl.rollback_evidence('registry/go:sha256-prev','health regression','codex')==0,'rollback evidence failed')
        rb=json.loads((Path(td)/'ROLLBACK_EVIDENCE.sealed.json').read_text())
        require(rb['database_downgrade_executed'] is False,'rollback must never claim DB downgrade')
        require(rb['alembic_stamp_forbidden'] is True,'rollback evidence must retain no-stamp')
    finally:
        ctl.run=original_run; ctl.operator_status=original_status

cp=subprocess.run(['sh','-n',str(ROOT/'scripts'/'r82_staging_deploy.sh')])
require(cp.returncode==0,'POSIX shell syntax invalid')
text=(ROOT/'scripts'/'r82_staging_deploy.sh').read_text()
require('pipefail' not in text,'POSIX command pack must not require pipefail')
require((ROOT/'docker-compose.staging.rc172.override.yml').exists(),'compose immutable-image override missing')
print('R8.2_RC17_2_STAGING_DEPLOYMENT_CONTROLLER_GATE: PASS')
