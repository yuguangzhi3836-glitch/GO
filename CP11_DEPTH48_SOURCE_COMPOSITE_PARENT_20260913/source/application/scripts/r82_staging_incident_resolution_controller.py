#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = Path(os.getenv('R82_STAGING_STATE_DIR', str(ROOT / 'var' / 'staging-execution')))
DEPLOYED_PARENT = 'V6.1-R8.2-rc.11+20260823T211759+CST'
CANDIDATE = 'V6.1-R8.2-rc.17.5'
SCHEMA = 'go.r8.2-staging-incident-resolution.v1'

spec = importlib.util.spec_from_file_location('incident', ROOT / 'scripts' / 'r82_staging_incident_controller.py')
incident = importlib.util.module_from_spec(spec)
spec.loader.exec_module(incident)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(v: Any) -> bytes:
    return json.dumps(v, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str).encode('utf-8')


def sha(v: Any) -> str:
    return hashlib.sha256(canonical(v)).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_artifact(name: str, payload: dict[str, Any]) -> dict[str, str]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = STATE_DIR / name
    body = dict(payload)
    body.setdefault('schema', SCHEMA)
    body.setdefault('generated_at', now_iso())
    body.setdefault('deployed_parent', DEPLOYED_PARENT)
    body.setdefault('candidate_not_deployed', True)
    body.setdefault('production_live', False)
    body['artifact_sha256'] = sha(body)
    p.write_text(json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + '\n', encoding='utf-8')
    digest = file_sha(p)
    Path(str(p)+'.sha256').write_text(f'{digest}  {p.name}\n', encoding='utf-8')
    return {'path': str(p), 'file_sha256': digest, 'artifact_sha256': body['artifact_sha256']}


def run(cmd: list[str]) -> dict[str, Any]:
    try:
        cp = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, env=os.environ.copy())
        return {'command': cmd, 'exit_code': cp.returncode, 'stdout': cp.stdout[-20000:], 'stderr': cp.stderr[-20000:]}
    except FileNotFoundError as exc:
        return {'command': cmd, 'exit_code': 127, 'stdout': '', 'stderr': 'COMMAND_NOT_FOUND:'+str(exc)}


def active_incident_id() -> str | None:
    valid, records = incident.read_incident_ledger()
    if not valid:
        return None
    opened: list[str] = []
    resolved: set[str] = set()
    for r in records:
        iid = r.get('incident_id')
        if r.get('event') == 'OPEN' and iid and iid not in opened:
            opened.append(iid)
        if r.get('event') == 'RESOLVED' and iid:
            resolved.add(iid)
    for iid in reversed(opened):
        if iid not in resolved:
            return iid
    return None


def records_for(iid: str) -> list[dict[str, Any]]:
    valid, records = incident.read_incident_ledger()
    if not valid:
        raise RuntimeError('INCIDENT_LEDGER_CHAIN_INVALID')
    return [r for r in records if r.get('incident_id') == iid]


def event_payload(iid: str, event: str) -> dict[str, Any] | None:
    for r in reversed(records_for(iid)):
        if r.get('event') == event:
            return r.get('payload') or {}
    return None


def require_active(iid: str) -> tuple[bool, str | None]:
    st = incident.incident_resolution_state(iid)
    if not st.get('ledger_valid'):
        return False, 'INCIDENT_LEDGER_CHAIN_INVALID'
    if not st.get('unresolved'):
        return False, 'INCIDENT_NOT_OPEN_OR_ALREADY_RESOLVED'
    return True, None


def add_root_cause(iid: str, actor: str, root_cause: str, evidence_reference: str) -> int:
    ok, err = require_active(iid)
    if not ok: print('NO_GO: '+str(err), file=sys.stderr); return 41
    if not actor.strip() or not root_cause.strip() or not evidence_reference.strip():
        print('NO_GO: ACTOR_ROOT_CAUSE_EVIDENCE_REQUIRED', file=sys.stderr); return 42
    payload={'actor':actor,'root_cause':root_cause,'evidence_reference':evidence_reference}
    rec=incident.append_incident_ledger('ROOT_CAUSE',iid,payload)
    res=write_artifact(f'{iid}.ROOT_CAUSE.sealed.json', {'type':'INCIDENT_ROOT_CAUSE','incident_id':iid,'correlation_id':iid,**payload,'ledger_entry_hash':rec['entry_hash']})
    print(json.dumps(res,indent=2)); return 0


def add_remediation(iid: str, actor: str, summary: str, evidence_reference: str) -> int:
    ok, err = require_active(iid)
    if not ok: print('NO_GO: '+str(err), file=sys.stderr); return 43
    if event_payload(iid,'ROOT_CAUSE') is None:
        print('NO_GO: ROOT_CAUSE_REQUIRED_FIRST', file=sys.stderr); return 44
    if not actor.strip() or not summary.strip() or not evidence_reference.strip():
        print('NO_GO: ACTOR_REMEDIATION_EVIDENCE_REQUIRED', file=sys.stderr); return 45
    payload={'actor':actor,'remediation_summary':summary,'evidence_reference':evidence_reference}
    rec=incident.append_incident_ledger('REMEDIATION',iid,payload)
    res=write_artifact(f'{iid}.REMEDIATION.sealed.json', {'type':'INCIDENT_REMEDIATION','incident_id':iid,'correlation_id':iid,**payload,'ledger_entry_hash':rec['entry_hash']})
    print(json.dumps(res,indent=2)); return 0


def reentry_preflight(iid: str) -> int:
    ok, err = require_active(iid)
    if not ok: print('NO_GO: '+str(err), file=sys.stderr); return 46
    if event_payload(iid,'REMEDIATION') is None:
        print('NO_GO: REMEDIATION_EVIDENCE_REQUIRED_FIRST', file=sys.stderr); return 47
    cp=run([sys.executable,'scripts/r82_staging_deployment_controller.py','preflight'])
    if cp['exit_code'] != 0:
        incident.append_incident_ledger('REENTRY_PREFLIGHT_NO_GO',iid,{'exit_code':cp['exit_code'],'stderr':cp['stderr']})
        print('NO_GO: REENTRY_PREFLIGHT_FAILED',file=sys.stderr); return 48
    p=STATE_DIR/'PREDEPLOY_PREFLIGHT.sealed.json'
    if not p.exists(): print('NO_GO: REENTRY_PREFLIGHT_SEAL_MISSING',file=sys.stderr); return 49
    payload={'source_path':str(p),'source_file_sha256':file_sha(p)}
    rec=incident.append_incident_ledger('REENTRY_PREFLIGHT_GO',iid,payload)
    write_artifact(f'{iid}.REENTRY_PREFLIGHT.sealed.json', {'type':'REENTRY_PREFLIGHT','decision':'GO','incident_id':iid,'correlation_id':iid,**payload,'ledger_entry_hash':rec['entry_hash']})
    print(json.dumps({'decision':'GO',**payload},indent=2)); return 0


def reentry_postdeploy(iid: str) -> int:
    ok, err = require_active(iid)
    if not ok: print('NO_GO: '+str(err), file=sys.stderr); return 50
    if event_payload(iid,'REENTRY_PREFLIGHT_GO') is None:
        print('NO_GO: REENTRY_PREFLIGHT_GO_REQUIRED_FIRST', file=sys.stderr); return 51
    cp=run([sys.executable,'scripts/r82_staging_postdeploy_controller.py','verify'])
    if cp['exit_code'] != 0:
        incident.append_incident_ledger('REENTRY_POSTDEPLOY_NO_GO',iid,{'exit_code':cp['exit_code'],'stderr':cp['stderr']})
        print('NO_GO: REENTRY_POSTDEPLOY_FAILED',file=sys.stderr); return 52
    p=STATE_DIR/'POSTDEPLOY_ACCEPTANCE.sealed.json'
    if not p.exists(): print('NO_GO: REENTRY_POSTDEPLOY_SEAL_MISSING',file=sys.stderr); return 53
    payload={'source_path':str(p),'source_file_sha256':file_sha(p)}
    rec=incident.append_incident_ledger('REENTRY_POSTDEPLOY_GO',iid,payload)
    write_artifact(f'{iid}.REENTRY_POSTDEPLOY.sealed.json', {'type':'REENTRY_POSTDEPLOY','decision':'GO','incident_id':iid,'correlation_id':iid,**payload,'ledger_entry_hash':rec['entry_hash']})
    print(json.dumps({'decision':'GO',**payload},indent=2)); return 0


def approve(iid: str, actor: str, role: str) -> int:
    ok, err = require_active(iid)
    if not ok: print('NO_GO: '+str(err), file=sys.stderr); return 54
    if event_payload(iid,'REENTRY_POSTDEPLOY_GO') is None:
        print('NO_GO: REENTRY_POSTDEPLOY_GO_REQUIRED_FIRST',file=sys.stderr); return 55
    if role not in {'maker','checker'} or not actor.strip(): return 2
    maker=event_payload(iid,'REENTRY_APPROVAL_MAKER')
    checker=event_payload(iid,'REENTRY_APPROVAL_CHECKER')
    if role=='maker':
        if maker is not None: print('NO_GO: MAKER_ALREADY_RECORDED',file=sys.stderr); return 56
        event='REENTRY_APPROVAL_MAKER'
    else:
        if maker is None: print('NO_GO: MAKER_REQUIRED_FIRST',file=sys.stderr); return 57
        if actor == maker.get('actor'): print('NO_GO: MAKER_CHECKER_MUST_DIFFER',file=sys.stderr); return 58
        if checker is not None: print('NO_GO: CHECKER_ALREADY_RECORDED',file=sys.stderr); return 59
        event='REENTRY_APPROVAL_CHECKER'
    payload={'actor':actor,'role':role}
    rec=incident.append_incident_ledger(event,iid,payload)
    write_artifact(f'{iid}.{event}.sealed.json', {'type':event,'decision':'APPROVED','incident_id':iid,'correlation_id':iid,**payload,'ledger_entry_hash':rec['entry_hash']})
    print(json.dumps({'decision':'APPROVED','incident_id':iid,**payload},indent=2)); return 0


def resolve(iid: str, actor: str) -> int:
    ok, err = require_active(iid)
    if not ok: print('NO_GO: '+str(err), file=sys.stderr); return 60
    required=['ROOT_CAUSE','REMEDIATION','REENTRY_PREFLIGHT_GO','REENTRY_POSTDEPLOY_GO','REENTRY_APPROVAL_MAKER','REENTRY_APPROVAL_CHECKER']
    missing=[e for e in required if event_payload(iid,e) is None]
    if missing:
        print('NO_GO: RESOLUTION_PREREQUISITES_MISSING:'+','.join(missing),file=sys.stderr); return 61
    maker=event_payload(iid,'REENTRY_APPROVAL_MAKER'); checker=event_payload(iid,'REENTRY_APPROVAL_CHECKER')
    if not maker or not checker or maker.get('actor')==checker.get('actor'):
        print('NO_GO: DUAL_CONTROL_INVALID',file=sys.stderr); return 62
    payload={'actor':actor,'maker':maker.get('actor'),'checker':checker.get('actor'),'old_abort_preserved':(STATE_DIR/'ABORT.sealed.json').exists(),'old_incident_preserved':(STATE_DIR/'POSTDEPLOY_INCIDENT.sealed.json').exists()}
    rec=incident.append_incident_ledger('RESOLVED',iid,payload)
    res=write_artifact('REENTRY_RELEASE.sealed.json', {'type':'CONTROLLED_REENTRY_RELEASE','decision':'GO','incident_id':iid,'correlation_id':iid,**payload,'ledger_entry_hash':rec['entry_hash'],'production_live':False})
    print(json.dumps({'decision':'GO','incident_id':iid,**res},indent=2)); return 0


def status(iid: str | None) -> int:
    target=iid or active_incident_id()
    valid, records=incident.read_incident_ledger()
    events=[r.get('event') for r in records if target and r.get('incident_id')==target]
    out={'ledger_valid':valid,'incident_id':target,'events':events,'unresolved':incident.incident_resolution_state(target).get('unresolved') if target else False,'production_live':False,'deployed_parent':DEPLOYED_PARENT}
    print(json.dumps(out,indent=2,ensure_ascii=False)); return 0 if valid else 63


def main() -> int:
    p=argparse.ArgumentParser(description='GO R8.2 RC17.5 Incident Resolution + Controlled Re-Entry Gate')
    sub=p.add_subparsers(dest='cmd',required=True)
    s=sub.add_parser('status'); s.add_argument('--incident-id')
    r=sub.add_parser('root-cause'); r.add_argument('--incident-id',required=True); r.add_argument('--actor',required=True); r.add_argument('--root-cause',required=True); r.add_argument('--evidence-reference',required=True)
    m=sub.add_parser('remediation'); m.add_argument('--incident-id',required=True); m.add_argument('--actor',required=True); m.add_argument('--summary',required=True); m.add_argument('--evidence-reference',required=True)
    rp=sub.add_parser('reentry-preflight'); rp.add_argument('--incident-id',required=True)
    rd=sub.add_parser('reentry-postdeploy'); rd.add_argument('--incident-id',required=True)
    a=sub.add_parser('approve'); a.add_argument('--incident-id',required=True); a.add_argument('--actor',required=True); a.add_argument('--role',choices=['maker','checker'],required=True)
    z=sub.add_parser('resolve'); z.add_argument('--incident-id',required=True); z.add_argument('--actor',required=True)
    args=p.parse_args()
    if args.cmd=='status': return status(args.incident_id)
    if args.cmd=='root-cause': return add_root_cause(args.incident_id,args.actor,args.root_cause,args.evidence_reference)
    if args.cmd=='remediation': return add_remediation(args.incident_id,args.actor,args.summary,args.evidence_reference)
    if args.cmd=='reentry-preflight': return reentry_preflight(args.incident_id)
    if args.cmd=='reentry-postdeploy': return reentry_postdeploy(args.incident_id)
    if args.cmd=='approve': return approve(args.incident_id,args.actor,args.role)
    if args.cmd=='resolve': return resolve(args.incident_id,args.actor)
    return 2

if __name__=='__main__':
    raise SystemExit(main())
