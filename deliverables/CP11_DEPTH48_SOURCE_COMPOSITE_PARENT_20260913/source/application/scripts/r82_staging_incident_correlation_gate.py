#!/usr/bin/env python3
from __future__ import annotations
import importlib.util, json, os, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('inc', ROOT/'scripts'/'r82_staging_incident_controller.py')
inc=importlib.util.module_from_spec(spec); spec.loader.exec_module(inc)

def require(v,msg):
    if not v: raise SystemExit('R8.2_RC17_4_POSTDEPLOY_INCIDENT_CORRELATION_GATE: FAIL '+msg)

def source_no_go(td:Path, blockers:list[str])->Path:
    body={
      'type':'POSTDEPLOY_ACCEPTANCE','decision':'NO_GO','blockers':blockers,'checks':[],
      'postdeploy_acceptance_go':False,'does_not_advance_rc17':True,
      'schema':'go.r8.2-staging-postdeploy-verification.v1','generated_at':'2026-08-24T00:00:00+00:00',
      'deployed_parent':inc.DEPLOYED_PARENT,'candidate_not_deployed':True,'production_live':False,
    }
    body['artifact_sha256']=inc.sha(body)
    p=td/'POSTDEPLOY_ACCEPTANCE.no_go.json'; p.write_text(json.dumps(body,sort_keys=True))
    return p

with tempfile.TemporaryDirectory() as d:
    td=Path(d); inc.STATE_DIR=td
    os.environ['GO_PREVIOUS_STAGING_IMAGE']='registry/go:sha256-prev'
    p=source_no_go(td,['API_CONTAINER_NOT_HEALTHY','HTTPS_THREE_SURFACE_FAILED'])
    require(inc.correlate(p)==0,'app NO-GO correlation failed')
    incident=json.loads((td/'POSTDEPLOY_INCIDENT.sealed.json').read_text())
    abort=json.loads((td/'ABORT.sealed.json').read_text())
    rec=json.loads((td/'ROLLBACK_RECOMMENDATION.sealed.json').read_text())
    require(incident['execution_frozen'] is True,'incident must freeze execution')
    require(incident['resume_allowed'] is False and incident['deploy_allowed'] is False,'freeze must block resume/deploy')
    require(incident['recommended_action']=='APPLICATION_ROLLBACK_RECOMMENDED','app failure recommendation wrong')
    require(rec['rollback_scope']=='APPLICATION_ONLY','application rollback scope required')
    require(rec['automatic_rollback_executed'] is False,'must not auto rollback')
    require(rec['database_downgrade_executed'] is False and rec['alembic_stamp_forbidden'] is True,'DB rollback/stamp must remain forbidden')
    ids={incident['correlation_id'],abort['correlation_id'],rec['correlation_id']}
    require(len(ids)==1,'correlation id must be shared across artifacts')

with tempfile.TemporaryDirectory() as d:
    td=Path(d); inc.STATE_DIR=td
    p=source_no_go(td,['RDS_LINEAGE_RUNTIME_MISMATCH'])
    require(inc.correlate(p)==0,'RDS NO-GO correlation failed')
    incident=json.loads((td/'POSTDEPLOY_INCIDENT.sealed.json').read_text())
    rec=json.loads((td/'ROLLBACK_RECOMMENDATION.sealed.json').read_text())
    require(incident['recommended_action']=='HALT_AND_INVESTIGATE_DATABASE_LINEAGE','RDS mismatch must halt/investigate')
    require(rec['rollback_recommended'] is False,'RDS mismatch must not recommend automatic rollback')
    require(rec['database_rollback_recommended'] is False,'DB rollback must not be recommended')
    require(rec['automatic_rollback_executed'] is False and rec['database_downgrade_executed'] is False,'no rollback may execute')

text=(ROOT/'scripts'/'r82_staging_postdeploy_controller.py').read_text()
require('r82_staging_incident_controller.py' in text and "decision!='GO'" in text,'postdeploy NO-GO must auto-trigger correlation controller')
require('alembic downgrade' not in (ROOT/'scripts'/'r82_staging_incident_controller.py').read_text().lower(),'incident controller must not execute alembic downgrade')
require('alembic stamp' not in (ROOT/'scripts'/'r82_staging_incident_controller.py').read_text().lower(),'incident controller must not execute alembic stamp')
print('R8.2_RC17_4_POSTDEPLOY_INCIDENT_CORRELATION_GATE: PASS')

# End-to-end: RC17.3 NO-GO automatically invokes RC17.4 and freezes RC17.2.
import importlib.util as _iu
with tempfile.TemporaryDirectory() as d:
    td=Path(d)
    os.environ['R82_STAGING_STATE_DIR']=str(td)
    ps=_iu.spec_from_file_location('post', ROOT/'scripts'/'r82_staging_postdeploy_controller.py')
    post=_iu.module_from_spec(ps); ps.loader.exec_module(post); post.STATE_DIR=td
    originals=(post.docker_health,post.runtime_lineage,post.https_check,post.browser_check,post.rc17_status)
    try:
        post.docker_health=lambda: (['API_CONTAINER_NOT_HEALTHY'],{})
        post.runtime_lineage=lambda: ([],{})
        post.https_check=lambda: (['HTTPS_THREE_SURFACE_FAILED'],{})
        post.browser_check=lambda: ([],{})
        post.rc17_status=lambda: ([],{'operator':{'chain_valid':True}})
        require(post.verify()==20,'postdeploy NO-GO exit expected')
        require((td/'POSTDEPLOY_INCIDENT.sealed.json').exists(),'incident must be auto-created')
        require((td/'ABORT.sealed.json').exists(),'automatic abort must be auto-created')
        ds=_iu.spec_from_file_location('dep', ROOT/'scripts'/'r82_staging_deployment_controller.py')
        dep=_iu.module_from_spec(ds); ds.loader.exec_module(dep); dep.STATE_DIR=td
        # No preflight is needed to prove incident-ledger freeze: deploy-plan must explicitly include EXECUTION_FROZEN.
        require(dep.deploy_plan('registry/go:sha256-abc')!=0,'deploy must remain blocked after automatic abort')
        plan=json.loads((td/'DEPLOY_PLAN.json').read_text())
        require(any(str(x).startswith('EXECUTION_FROZEN:') for x in plan['blockers']),'RC17.2 must consume incident-ledger freeze')
    finally:
        post.docker_health,post.runtime_lineage,post.https_check,post.browser_check,post.rc17_status=originals
        os.environ.pop('R82_STAGING_STATE_DIR',None)
print('R8.2_RC17_4_END_TO_END_FREEZE_GATE: PASS')
