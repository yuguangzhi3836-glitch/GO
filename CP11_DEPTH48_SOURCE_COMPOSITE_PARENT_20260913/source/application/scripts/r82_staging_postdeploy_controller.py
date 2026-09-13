#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parents[1]
STATE_DIR=Path(os.getenv('R82_STAGING_STATE_DIR', str(ROOT/'var'/'staging-execution')))
EXPECTED_HEAD='0112_ti_p0_20260829'; EXPECTED_REVISIONS=112
DEPLOYED_PARENT='V6.1-R8.2-rc.11+20260823T211759+CST'
SCHEMA='go.r8.2-staging-postdeploy-verification.v1'
REQUIRED_SERVICES=['api','outbox-worker','regional-hotel-build-worker','recovery-worker','reconciliation-worker','judgment-worker','mobile-engagement-worker','mobile-push-worker','mobile-push-receipt-worker']

def now(): return datetime.now(timezone.utc).isoformat()
def canonical(v:Any)->bytes:return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()
def digest(v:Any)->str:return hashlib.sha256(canonical(v)).hexdigest()
def run(cmd, env=None):
    try:
        cp=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True,env=env or os.environ.copy())
        return {'command':cmd,'exit_code':cp.returncode,'stdout':cp.stdout[-16000:],'stderr':cp.stderr[-16000:]}
    except FileNotFoundError as exc:
        return {'command':cmd,'exit_code':127,'stdout':'','stderr':'COMMAND_NOT_FOUND:'+str(exc)}
def write(payload,name):
    STATE_DIR.mkdir(parents=True,exist_ok=True); p=STATE_DIR/name
    body=dict(payload); body.update({'schema':SCHEMA,'generated_at':now(),'deployed_parent':DEPLOYED_PARENT,'candidate_not_deployed':True,'production_live':False})
    body['artifact_sha256']=digest(body); p.write_text(json.dumps(body,indent=2,sort_keys=True,ensure_ascii=False)+'\n')
    fsha=hashlib.sha256(p.read_bytes()).hexdigest(); Path(str(p)+'.sha256').write_text(f'{fsha}  {p.name}\n')
    return {'path':str(p),'file_sha256':fsha}
def docker_health():
    cp=run(['docker','compose','-f','docker-compose.staging.yml','-f','docker-compose.staging.rc172.override.yml','ps','--format','json'])
    blockers=[]; observed=[]
    if cp['exit_code']!=0:return ['DOCKER_COMPOSE_PS_FAILED'], {'command':cp}
    try:
        rows=[]
        for line in cp['stdout'].splitlines():
            line=line.strip()
            if line: rows.append(json.loads(line))
    except Exception:return ['DOCKER_COMPOSE_PS_INVALID_JSON'], {'raw':cp['stdout']}
    by={r.get('Service'):r for r in rows}
    for svc in REQUIRED_SERVICES:
        r=by.get(svc)
        if not r: blockers.append(f'CONTAINER_MISSING:{svc}'); continue
        state=str(r.get('State','')).lower(); health=str(r.get('Health','')).lower()
        observed.append({'service':svc,'state':state,'health':health})
        if state!='running': blockers.append(f'CONTAINER_NOT_RUNNING:{svc}')
        if svc=='api' and health!='healthy': blockers.append('API_CONTAINER_NOT_HEALTHY')
    return blockers, {'services':observed}
def runtime_lineage():
    if not os.getenv('DATABASE_URL','').strip(): return ['DATABASE_URL_MISSING'], {}
    cp=run([sys.executable,'scripts/r82_rds_lineage_probe.py'])
    return ([] if cp['exit_code']==0 else ['RDS_LINEAGE_RUNTIME_MISMATCH']), {'probe':cp,'expected_revision_count':EXPECTED_REVISIONS,'expected_head':EXPECTED_HEAD}
def https_check():
    cp=run(['sh','deploy/https_verify.sh'])
    return ([] if cp['exit_code']==0 else ['HTTPS_THREE_SURFACE_FAILED']), {'verification':cp}
def browser_check():
    cp=run(['sh','deploy/browser_verify.sh'])
    return ([] if cp['exit_code']==0 else ['BROWSER_RENDER_OR_CONSOLE_FAILED']), {'verification':cp}
def rc17_status():
    cp=run([sys.executable,'scripts/r82_staging_operator.py','status'])
    if cp['exit_code']!=0:return ['RC17_OPERATOR_STATUS_FAILED'], {'command':cp}
    try: data=json.loads(cp['stdout'])
    except Exception:return ['RC17_OPERATOR_STATUS_INVALID_JSON'], {'raw':cp['stdout']}
    blockers=[]
    if data.get('chain_valid') is not True:blockers.append('RC17_EVIDENCE_CHAIN_INVALID')
    return blockers, {'operator':data,'current_checkpoint':data.get('current_checkpoint'),'next_checkpoint':data.get('next_checkpoint')}
def verify():
    checks=[]; blockers=[]
    for name,fn in [('container_health',docker_health),('migration_runtime',runtime_lineage),('https_three_surface',https_check),('browser_console',browser_check),('rc17_checkpoint',rc17_status)]:
        b,o=fn(); checks.append({'name':name,'decision':'GO' if not b else 'NO_GO','blockers':b,'observed':o}); blockers.extend(b)
    blockers=sorted(set(blockers)); decision='GO' if not blockers else 'NO_GO'
    payload={'type':'POSTDEPLOY_ACCEPTANCE','decision':decision,'blockers':blockers,'checks':checks,'postdeploy_acceptance_go':decision=='GO','does_not_advance_rc17':True}
    res=write(payload,'POSTDEPLOY_ACCEPTANCE.sealed.json' if decision=='GO' else 'POSTDEPLOY_ACCEPTANCE.no_go.json')
    correlation=None
    if decision!='GO':
        corr=run([sys.executable,'scripts/r82_staging_incident_controller.py','correlate','--no-go-artifact',res['path']])
        correlation={'exit_code':corr['exit_code'],'stdout':corr['stdout'],'stderr':corr['stderr']}
    print(json.dumps({**payload,**res,'incident_correlation':correlation},indent=2,ensure_ascii=False)); return 0 if decision=='GO' else 20
def status():
    p=STATE_DIR/'POSTDEPLOY_ACCEPTANCE.sealed.json'; valid=False; data=None
    if p.exists():
        try:
            data=json.loads(p.read_text()); emb=data.pop('artifact_sha256',None); valid=emb==digest(data) and data.get('decision')=='GO'; data['artifact_sha256']=emb
        except Exception: pass
    print(json.dumps({'postdeploy_seal_valid':valid,'artifact':data,'production_live':False,'deployed_parent':DEPLOYED_PARENT},indent=2,ensure_ascii=False)); return 0
def main():
    p=argparse.ArgumentParser(); p.add_argument('cmd',choices=['verify','status']); a=p.parse_args(); return verify() if a.cmd=='verify' else status()
if __name__=='__main__': raise SystemExit(main())
