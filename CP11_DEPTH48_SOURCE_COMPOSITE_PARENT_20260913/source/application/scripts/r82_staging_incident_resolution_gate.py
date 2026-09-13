#!/usr/bin/env python3
from __future__ import annotations
import importlib.util, json, os, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def load(name,path):
    sp=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(sp); sp.loader.exec_module(m); return m
inc=load('inc',ROOT/'scripts'/'r82_staging_incident_controller.py')
res=load('res',ROOT/'scripts'/'r82_staging_incident_resolution_controller.py')
dep=load('dep',ROOT/'scripts'/'r82_staging_deployment_controller.py')

def req(v,msg):
    if not v: raise SystemExit('R8.2_RC17_5_INCIDENT_RESOLUTION_REENTRY_GATE: FAIL '+msg)

def source_no_go(td:Path):
    body={'type':'POSTDEPLOY_ACCEPTANCE','decision':'NO_GO','blockers':['API_CONTAINER_NOT_HEALTHY'],'checks':[],'postdeploy_acceptance_go':False,'does_not_advance_rc17':True,'schema':'go.r8.2-staging-postdeploy-verification.v1','generated_at':'2026-08-24T00:00:00+00:00','deployed_parent':inc.DEPLOYED_PARENT,'candidate_not_deployed':True,'production_live':False}
    body['artifact_sha256']=inc.sha(body); p=td/'POSTDEPLOY_ACCEPTANCE.no_go.json'; p.write_text(json.dumps(body,sort_keys=True)); return p

with tempfile.TemporaryDirectory() as d:
    td=Path(d); inc.STATE_DIR=td; res.STATE_DIR=td; res.incident.STATE_DIR=td; dep.STATE_DIR=td
    p=source_no_go(td); req(inc.correlate(p)==0,'correlate failed')
    iid=json.loads((td/'POSTDEPLOY_INCIDENT.sealed.json').read_text())['incident_id']
    valid,records=inc.read_incident_ledger(); req(valid and records and records[0]['event']=='OPEN','OPEN ledger required')
    req(dep.execution_freeze_state()['frozen'] is True,'incident must freeze execution')

    # Deleting ABORT alone must not unfreeze.
    (td/'ABORT.sealed.json').unlink(); req(dep.execution_freeze_state()['frozen'] is True,'deleting ABORT must not bypass freeze')
    req(dep.execution_freeze_state()['reason'] in {'UNRESOLVED_INCIDENT','INCIDENT_HISTORY_NOT_RESOLVED'},'unexpected deletion freeze reason')
    # Deleting ledger is also fail closed while archived incident remains.
    ledger=td/'INCIDENT_LEDGER.jsonl'; saved=ledger.read_text(); ledger.unlink(); req(dep.execution_freeze_state()['frozen'] is True,'deleting ledger must fail closed')
    req(dep.execution_freeze_state()['reason']=='INCIDENT_HISTORY_WITHOUT_LEDGER','missing ledger must be explicit')
    ledger.write_text(saved)
    # Re-correlate recreates historical ABORT idempotently without duplicate OPEN.
    req(inc.correlate(p)==0,'re-correlate failed')

    req(res.add_remediation(iid,'ops','fix','evidence://fix')!=0,'remediation before root cause must fail')
    req(res.add_root_cause(iid,'ops','bad image config','evidence://rca')==0,'root cause failed')
    req(res.add_remediation(iid,'ops','immutable image corrected','evidence://fix')==0,'remediation failed')

    original_run=res.run
    def fake_run(cmd):
        if any('r82_staging_deployment_controller.py' in str(x) for x in cmd):
            (td/'PREDEPLOY_PREFLIGHT.sealed.json').write_text('{}')
            return {'command':cmd,'exit_code':0,'stdout':'','stderr':''}
        if any('r82_staging_postdeploy_controller.py' in str(x) for x in cmd):
            (td/'POSTDEPLOY_ACCEPTANCE.sealed.json').write_text('{}')
            return {'command':cmd,'exit_code':0,'stdout':'','stderr':''}
        return {'command':cmd,'exit_code':1,'stdout':'','stderr':'unexpected'}
    res.run=fake_run
    try:
        req(res.reentry_preflight(iid)==0,'reentry preflight failed')
        req(res.reentry_postdeploy(iid)==0,'reentry postdeploy failed')
    finally:
        res.run=original_run
    req(res.approve(iid,'alice','maker')==0,'maker approval failed')
    req(res.approve(iid,'alice','checker')!=0,'same actor checker must fail')
    req(res.approve(iid,'bob','checker')==0,'checker approval failed')
    req(res.resolve(iid,'release-manager')==0,'resolve failed')
    st=inc.incident_resolution_state(iid); req(st['ledger_valid'] and st['unresolved'] is False,'incident must resolve')
    req((td/'ABORT.sealed.json').exists(),'historical ABORT must be preserved')
    req((td/'POSTDEPLOY_INCIDENT.sealed.json').exists(),'historical incident must be preserved')
    req((td/'REENTRY_RELEASE.sealed.json').exists(),'reentry release required')
    req(dep.execution_freeze_state()['frozen'] is False,'resolved automatic abort must allow controlled re-entry')
    valid,records=inc.read_incident_ledger(); req(valid,'ledger chain must remain valid')
    events=[r['event'] for r in records if r.get('incident_id')==iid]
    for e in ['OPEN','ROOT_CAUSE','REMEDIATION','REENTRY_PREFLIGHT_GO','REENTRY_POSTDEPLOY_GO','REENTRY_APPROVAL_MAKER','REENTRY_APPROVAL_CHECKER','RESOLVED']:
        req(e in events,'missing event '+e)

text=(ROOT/'scripts'/'r82_staging_deployment_controller.py').read_text()
req('execution_freeze_state' in text and 'UNRESOLVED_INCIDENT' in text,'deployment controller must consume ledger freeze')
req("(STATE_DIR / 'ABORT.sealed.json').exists(): blockers.append('EXECUTION_ABORTED')" not in text,'legacy ABORT-only bypass logic must be removed')
for fn in ['r82_staging_incident_resolution_controller.py','r82_staging_incident_controller.py']:
    t=(ROOT/'scripts'/fn).read_text().lower(); req('alembic downgrade' not in t and 'alembic stamp' not in t,'resolution must not execute DB downgrade/stamp')
print('R8.2_RC17_5_INCIDENT_RESOLUTION_REENTRY_GATE: PASS')
