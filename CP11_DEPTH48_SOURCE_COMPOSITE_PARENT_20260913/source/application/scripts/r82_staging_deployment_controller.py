#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = Path(os.getenv('R82_STAGING_STATE_DIR', str(ROOT / 'var' / 'staging-execution')))
EXPECTED_HEAD = '0112_ti_p0_20260829'
EXPECTED_REVISIONS = 112
DEPLOYED_PARENT = 'V6.1-R8.2-rc.11+20260823T211759+CST'
CANDIDATE = 'V6.1-R8.2-rc.17.5'
SCHEMA = 'go.r8.2-staging-deployment-control.v1'


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(v: Any) -> bytes:
    return json.dumps(v, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str).encode('utf-8')


def sha(v: Any) -> str:
    return hashlib.sha256(canonical(v)).hexdigest()


def write_artifact(name: str, payload: dict[str, Any]) -> dict[str, str]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / name
    body = dict(payload)
    body.setdefault('schema', SCHEMA)
    body.setdefault('generated_at', now_iso())
    body.setdefault('deployed_parent', DEPLOYED_PARENT)
    body.setdefault('candidate_not_deployed', True)
    body.setdefault('production_live', False)
    body['artifact_sha256'] = sha(body)
    raw = json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + '\n'
    path.write_text(raw, encoding='utf-8')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    sidecar = Path(str(path) + '.sha256')
    sidecar.write_text(f'{digest}  {path.name}\n', encoding='utf-8')
    return {'path': str(path), 'sha256_path': str(sidecar), 'file_sha256': digest}


def run(cmd: list[str], env: dict[str, str] | None = None) -> dict[str, Any]:
    cp = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, env=env or os.environ.copy())
    return {'command': cmd, 'exit_code': cp.returncode, 'stdout': cp.stdout[-12000:], 'stderr': cp.stderr[-12000:]}


def verify_preflight_artifact() -> tuple[bool, dict[str, Any] | None]:
    path = STATE_DIR / 'PREDEPLOY_PREFLIGHT.sealed.json'
    if not path.exists():
        return False, None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return False, None
    embedded = data.pop('artifact_sha256', None)
    valid = embedded == sha(data)
    data['artifact_sha256'] = embedded
    valid = valid and data.get('decision') == 'GO' and data.get('expected_head') == EXPECTED_HEAD and data.get('expected_revision_count') == EXPECTED_REVISIONS
    return bool(valid), data


def preflight() -> int:
    checks = []
    release = run([sys.executable, 'scripts/r82_manifest_consistency_gate.py'])
    checks.append({'name': 'manifest', **release})
    checksum = run([sys.executable, 'scripts/r82_source_checksum_gate.py'])
    checks.append({'name': 'source_checksum', **checksum})
    migration = run([sys.executable, 'scripts/r82_migration_lineage_gate.py'])
    checks.append({'name': 'migration_lineage', **migration})
    nostamp = run([sys.executable, 'scripts/r82_no_stamp_gate.py'])
    checks.append({'name': 'no_stamp', **nostamp})
    rc17 = run([sys.executable, 'scripts/r82_staging_execution_evidence_gate.py'])
    checks.append({'name': 'rc17_evidence_orchestrator', **rc17})
    rc171 = run([sys.executable, 'scripts/r82_staging_operator_gate.py'])
    checks.append({'name': 'rc17_1_operator', **rc171})
    if not os.getenv('DATABASE_URL', '').strip():
        checks.append({'name': 'rds_lineage', 'exit_code': 2, 'stdout': '', 'stderr': 'DATABASE_URL missing'})
    else:
        rds = run([sys.executable, 'scripts/r82_rds_lineage_probe.py'])
        checks.append({'name': 'rds_lineage', **rds})
    blockers = [c['name'] for c in checks if c.get('exit_code') != 0]
    payload = {
        'type': 'PREDEPLOY_PREFLIGHT',
        'decision': 'GO' if not blockers else 'NO_GO',
        'expected_revision_count': EXPECTED_REVISIONS,
        'expected_head': EXPECTED_HEAD,
        'alembic_stamp_forbidden': True,
        'blockers': blockers,
        'checks': checks,
    }
    name = 'PREDEPLOY_PREFLIGHT.sealed.json' if not blockers else 'PREDEPLOY_PREFLIGHT.no_go.json'
    result = write_artifact(name, payload)
    print(json.dumps({'decision': payload['decision'], 'blockers': blockers, **result}, indent=2))
    return 0 if not blockers else 10


def operator_status() -> dict[str, Any]:
    cp = run([sys.executable, 'scripts/r82_staging_operator.py', 'status'])
    if cp['exit_code'] != 0:
        return {'operator_status_error': cp, 'production_live': False}
    try:
        return json.loads(cp['stdout'])
    except Exception:
        return {'operator_status_error': 'INVALID_JSON', 'raw': cp['stdout'], 'production_live': False}



def _incident_status() -> dict[str, Any]:
    p = STATE_DIR / 'POSTDEPLOY_INCIDENT.sealed.json'
    if not p.exists():
        return {'incident_present': False}
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
        return {
            'incident_present': True,
            'incident_id': data.get('incident_id'),
            'correlation_id': data.get('correlation_id'),
            'recommended_action': data.get('recommended_action'),
            'execution_frozen': data.get('execution_frozen') is True,
        }
    except Exception:
        return {'incident_present': True, 'invalid': True}



def _read_abort() -> dict[str, Any] | None:
    p = STATE_DIR / 'ABORT.sealed.json'
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return {'type':'INVALID_ABORT_ARTIFACT'}

def _incident_ledger_state() -> dict[str, Any]:
    import importlib.util
    sp = importlib.util.spec_from_file_location('incstate', ROOT/'scripts'/'r82_staging_incident_controller.py')
    mod = importlib.util.module_from_spec(sp); sp.loader.exec_module(mod); mod.STATE_DIR = STATE_DIR
    valid, records = mod.read_incident_ledger()
    if not valid:
        return {'ledger_valid':False,'unresolved':True,'incident_id':None}
    opened=[]; resolved=set()
    for r in records:
        iid=r.get('incident_id')
        if r.get('event')=='OPEN' and iid and iid not in opened: opened.append(iid)
        if r.get('event')=='RESOLVED' and iid: resolved.add(iid)
    unresolved=[iid for iid in opened if iid not in resolved]
    return {'ledger_valid':True,'unresolved':bool(unresolved),'incident_id':unresolved[-1] if unresolved else None,'unresolved_incidents':unresolved,'resolved_incidents':sorted(resolved),'record_count':len(records)}

def execution_freeze_state() -> dict[str, Any]:
    ledger = _incident_ledger_state()
    abort = _read_abort()
    history_present = (STATE_DIR/'POSTDEPLOY_INCIDENT.sealed.json').exists() or (STATE_DIR/'incidents').exists()
    if not ledger.get('ledger_valid'):
        return {'frozen':True,'reason':'INCIDENT_LEDGER_INVALID','ledger':ledger,'abort':abort}
    if history_present and int(ledger.get('record_count') or 0) == 0:
        return {'frozen':True,'reason':'INCIDENT_HISTORY_WITHOUT_LEDGER','ledger':ledger,'abort':abort}
    if ledger.get('unresolved'):
        return {'frozen':True,'reason':'UNRESOLVED_INCIDENT','ledger':ledger,'abort':abort}
    if abort:
        typ = str(abort.get('type',''))
        if typ == 'AUTOMATIC_POSTDEPLOY_ABORT':
            iid = abort.get('incident_id')
            if iid and iid in set(ledger.get('resolved_incidents') or []):
                # Historical automatic ABORT is preserved after a valid RESOLVED ledger event.
                return {'frozen':False,'reason':'RESOLVED_AUTOMATIC_ABORT_PRESERVED','ledger':ledger,'abort':abort}
            return {'frozen':True,'reason':'AUTOMATIC_ABORT_WITHOUT_RESOLUTION','ledger':ledger,'abort':abort}
        return {'frozen':True,'reason':'MANUAL_OR_UNCORRELATED_ABORT','ledger':ledger,'abort':abort}
    if history_present:
        # Deleting ABORT does not bypass an incident; a RESOLVED ledger record is required.
        resolved = set(ledger.get('resolved_incidents') or [])
        archived_ids = set()
        idir = STATE_DIR/'incidents'
        if idir.exists():
            archived_ids = {x.name for x in idir.iterdir() if x.is_dir()}
        current_id = None
        try:
            current_id = json.loads((STATE_DIR/'POSTDEPLOY_INCIDENT.sealed.json').read_text(encoding='utf-8')).get('incident_id')
        except Exception:
            pass
        required = archived_ids | ({current_id} if current_id else set())
        if required and not required.issubset(resolved):
            return {'frozen':True,'reason':'INCIDENT_HISTORY_NOT_RESOLVED','ledger':ledger,'abort':None}
    return {'frozen':False,'reason':None,'ledger':ledger,'abort':None}

def status() -> int:
    pf_ok, pf = verify_preflight_artifact()
    freeze = execution_freeze_state()
    aborted = bool(freeze.get('frozen'))
    st = operator_status()
    out = {
        'schema': SCHEMA,
        'preflight_sealed_valid': pf_ok,
        'aborted': aborted,
        'execution_frozen': aborted,
        'freeze_state': freeze,
        'incident_correlation': _incident_status(),
        'operator': st,
        'resume_from': None if aborted else (st.get('next_checkpoint') if pf_ok else 'PREDEPLOY_PREFLIGHT'),
        'deployed_parent': DEPLOYED_PARENT,
        'candidate_not_deployed': True,
        'production_live': False,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def resume() -> int:
    freeze = execution_freeze_state()
    if freeze.get('frozen'):
        print('NO_GO: EXECUTION_FROZEN:'+str(freeze.get('reason')), file=sys.stderr)
        return 11
    pf_ok, _ = verify_preflight_artifact()
    if not pf_ok:
        print('NO_GO: VALID_PREDEPLOY_PREFLIGHT_SEAL_REQUIRED', file=sys.stderr)
        return 12
    st = operator_status()
    if st.get('chain_valid') is not True:
        print('NO_GO: STAGING_EVIDENCE_CHAIN_INVALID', file=sys.stderr)
        return 13
    payload = {
        'type': 'RESUME_DECISION',
        'decision': 'GO',
        'resume_from_checkpoint': st.get('next_checkpoint'),
        'current_checkpoint': st.get('current_checkpoint'),
        'blockers': st.get('blockers') or [],
        'complete': st.get('complete'),
    }
    result = write_artifact('RESUME.sealed.json', payload)
    print(json.dumps({**payload, **result}, indent=2))
    return 0


def abort(reason: str, actor: str) -> int:
    if not reason.strip() or not actor.strip():
        print('reason and actor required', file=sys.stderr); return 2
    st = operator_status()
    payload = {
        'type': 'MANUAL_ABORT', 'decision': 'ABORT', 'actor': actor, 'reason': reason,
        'checkpoint_at_abort': st.get('current_checkpoint'), 'next_checkpoint': st.get('next_checkpoint'),
        'evidence_chain_valid': st.get('chain_valid'),
    }
    result = write_artifact('ABORT.sealed.json', payload)
    print(json.dumps({**payload, **result}, indent=2))
    return 0


def rollback_evidence(previous_image_tag: str, reason: str, actor: str) -> int:
    if not previous_image_tag.strip() or not reason.strip() or not actor.strip():
        print('previous-image-tag, reason and actor required', file=sys.stderr); return 2
    payload = {
        'type': 'ROLLBACK_EVIDENCE', 'decision': 'ROLLBACK_RECORDED', 'actor': actor, 'reason': reason,
        'previous_image_tag': previous_image_tag,
        'database_downgrade_executed': False,
        'database_rollback_requires_separate_review': True,
        'alembic_stamp_forbidden': True,
    }
    result = write_artifact('ROLLBACK_EVIDENCE.sealed.json', payload)
    print(json.dumps({**payload, **result}, indent=2))
    return 0


def deploy_plan(image_tag: str) -> int:
    pf_ok, _ = verify_preflight_artifact()
    blockers = []
    if not pf_ok: blockers.append('VALID_PREDEPLOY_PREFLIGHT_SEAL_REQUIRED')
    freeze = execution_freeze_state()
    if freeze.get('frozen'): blockers.append('EXECUTION_FROZEN:'+str(freeze.get('reason')))
    if not image_tag or image_tag in {'latest', 'main', 'master'} or ':' not in image_tag:
        blockers.append('IMMUTABLE_IMAGE_TAG_REQUIRED')
    payload = {
        'type': 'DEPLOY_PLAN', 'decision': 'GO' if not blockers else 'NO_GO', 'image_tag': image_tag,
        'blockers': blockers,
        'commands': [
            'docker pull "$GO_STAGING_IMAGE"',
            'docker compose -f docker-compose.staging.yml -f docker-compose.staging.rc172.override.yml up -d --no-build --no-deps api outbox-worker regional-hotel-build-worker recovery-worker reconciliation-worker judgment-worker mobile-engagement-worker mobile-push-worker mobile-push-receipt-worker',
            'python3 scripts/r82_staging_operator.py status',
            './scripts/r82_staging_postdeploy.sh verify',
        ] if not blockers else [],
        'migration_command_included': False,
        'database_downgrade_included': False,
        'alembic_stamp_forbidden': True,
    }
    result = write_artifact('DEPLOY_PLAN.json', payload)
    print(json.dumps({**payload, **result}, indent=2))
    return 0 if not blockers else 14


def main() -> int:
    p = argparse.ArgumentParser(description='GO R8.2 RC17.2 Staging Deployment Controller')
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('preflight')
    sub.add_parser('status')
    sub.add_parser('resume')
    a = sub.add_parser('abort'); a.add_argument('--reason', required=True); a.add_argument('--actor', required=True)
    r = sub.add_parser('rollback-evidence'); r.add_argument('--previous-image-tag', required=True); r.add_argument('--reason', required=True); r.add_argument('--actor', required=True)
    d = sub.add_parser('deploy-plan'); d.add_argument('--image-tag', required=True)
    args = p.parse_args()
    if args.cmd == 'preflight': return preflight()
    if args.cmd == 'status': return status()
    if args.cmd == 'resume': return resume()
    if args.cmd == 'abort': return abort(args.reason, args.actor)
    if args.cmd == 'rollback-evidence': return rollback_evidence(args.previous_image_tag, args.reason, args.actor)
    if args.cmd == 'deploy-plan': return deploy_plan(args.image_tag)
    return 2

if __name__ == '__main__':
    raise SystemExit(main())
