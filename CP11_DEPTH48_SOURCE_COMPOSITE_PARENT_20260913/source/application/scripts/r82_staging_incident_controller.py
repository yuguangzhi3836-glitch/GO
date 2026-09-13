#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = Path(os.getenv('R82_STAGING_STATE_DIR', str(ROOT / 'var' / 'staging-execution')))
DEPLOYED_PARENT = 'V6.1-R8.2-rc.11+20260823T211759+CST'
CANDIDATE = 'V6.1-R8.2-rc.17.5'
SCHEMA = 'go.r8.2-staging-postdeploy-incident-correlation.v1'
DB_BLOCKERS = {'DATABASE_URL_MISSING', 'RDS_LINEAGE_RUNTIME_MISMATCH'}
LEDGER_NAME = 'INCIDENT_LEDGER.jsonl'
LEDGER_SCHEMA = 'go.r8.2-staging-incident-ledger.v1'

def _ledger_path() -> Path:
    return STATE_DIR / LEDGER_NAME

def read_incident_ledger() -> tuple[bool, list[dict[str, Any]]]:
    path = _ledger_path()
    if not path.exists():
        return True, []
    records: list[dict[str, Any]] = []
    prev = 'GENESIS'
    try:
        for raw in path.read_text(encoding='utf-8').splitlines():
            if not raw.strip():
                continue
            rec = json.loads(raw)
            entry_hash = rec.pop('entry_hash', None)
            if rec.get('previous_hash') != prev or entry_hash != sha(rec):
                return False, records
            rec['entry_hash'] = entry_hash
            records.append(rec)
            prev = entry_hash
    except Exception:
        return False, records
    return True, records

def append_incident_ledger(event: str, incident_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    valid, records = read_incident_ledger()
    if not valid:
        raise RuntimeError('INCIDENT_LEDGER_CHAIN_INVALID')
    previous_hash = records[-1]['entry_hash'] if records else 'GENESIS'
    rec = {
        'schema': LEDGER_SCHEMA,
        'event': event,
        'incident_id': incident_id,
        'correlation_id': incident_id,
        'created_at': now_iso(),
        'previous_hash': previous_hash,
        'deployed_parent': DEPLOYED_PARENT,
        'candidate_not_deployed': True,
        'production_live': False,
        'payload': payload,
    }
    rec['entry_hash'] = sha(rec)
    with _ledger_path().open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(rec, sort_keys=True, ensure_ascii=False) + '\n')
    return rec

def incident_resolution_state(incident_id: str | None = None) -> dict[str, Any]:
    valid, records = read_incident_ledger()
    if not valid:
        return {'ledger_valid': False, 'unresolved': True, 'incident_id': incident_id}
    ids = []
    for r in records:
        iid = r.get('incident_id')
        if iid and iid not in ids:
            ids.append(iid)
    target = incident_id or (ids[-1] if ids else None)
    if not target:
        return {'ledger_valid': True, 'unresolved': False, 'incident_id': None}
    events = [r for r in records if r.get('incident_id') == target]
    opened = any(r.get('event') == 'OPEN' for r in events)
    resolved = any(r.get('event') == 'RESOLVED' for r in events)
    return {'ledger_valid': True, 'unresolved': bool(opened and not resolved), 'incident_id': target, 'events': [r.get('event') for r in events]}

APP_ROLLBACK_PREFIXES = (
    'DOCKER_COMPOSE_PS_FAILED', 'DOCKER_COMPOSE_PS_INVALID_JSON',
    'CONTAINER_MISSING:', 'CONTAINER_NOT_RUNNING:', 'API_CONTAINER_NOT_HEALTHY',
    'HTTPS_THREE_SURFACE_FAILED', 'BROWSER_RENDER_OR_CONSOLE_FAILED',
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(v: Any) -> bytes:
    return json.dumps(v, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str).encode('utf-8')


def sha(v: Any) -> str:
    return hashlib.sha256(canonical(v)).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_artifact(name: str, payload: dict[str, Any], schema: str = SCHEMA) -> dict[str, str]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / name
    body = dict(payload)
    body.setdefault('schema', schema)
    body.setdefault('generated_at', now_iso())
    body.setdefault('deployed_parent', DEPLOYED_PARENT)
    body.setdefault('candidate_not_deployed', True)
    body.setdefault('production_live', False)
    body['artifact_sha256'] = sha(body)
    path.write_text(json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + '\n', encoding='utf-8')
    digest = file_sha(path)
    sidecar = Path(str(path) + '.sha256')
    sidecar.write_text(f'{digest}  {path.name}\n', encoding='utf-8')
    return {'path': str(path), 'sha256_path': str(sidecar), 'file_sha256': digest, 'artifact_sha256': body['artifact_sha256']}


def verify_embedded(path: Path) -> tuple[bool, dict[str, Any] | None]:
    if not path.exists():
        return False, None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return False, None
    embedded = data.pop('artifact_sha256', None)
    valid = embedded == sha(data)
    data['artifact_sha256'] = embedded
    return valid, data


def incident_id_from(no_go: dict[str, Any]) -> str:
    basis = {
        'release': CANDIDATE,
        'deployed_parent': DEPLOYED_PARENT,
        'source_artifact_sha256': no_go.get('artifact_sha256'),
        'blockers': sorted(no_go.get('blockers') or []),
    }
    return 'GO-R82-INC-' + sha(basis)[:16].upper()


def blocker_matches(blocker: str, prefixes: tuple[str, ...]) -> bool:
    return any(blocker == p or blocker.startswith(p) for p in prefixes)


def correlate(no_go_path: Path | None = None) -> int:
    path = no_go_path or (STATE_DIR / 'POSTDEPLOY_ACCEPTANCE.no_go.json')
    valid, no_go = verify_embedded(path)
    if not valid or not no_go:
        print('NO_GO: VALID_POSTDEPLOY_NO_GO_ARTIFACT_REQUIRED')
        return 31
    if no_go.get('decision') != 'NO_GO':
        print('NO_GO: SOURCE_ARTIFACT_MUST_BE_NO_GO')
        return 32

    blockers = sorted(set(str(x) for x in (no_go.get('blockers') or [])))
    incident_id = incident_id_from(no_go)
    db_issue = any(b in DB_BLOCKERS for b in blockers)
    app_issue = any(blocker_matches(b, APP_ROLLBACK_PREFIXES) for b in blockers)
    previous_image = os.getenv('GO_PREVIOUS_STAGING_IMAGE', '').strip() or None

    if db_issue:
        action = 'HALT_AND_INVESTIGATE_DATABASE_LINEAGE'
        rollback_recommended = False
        rollback_scope = 'NONE_AUTOMATIC'
    elif app_issue:
        action = 'APPLICATION_ROLLBACK_RECOMMENDED'
        rollback_recommended = True
        rollback_scope = 'APPLICATION_ONLY'
    else:
        action = 'HALT_AND_OPERATOR_REVIEW'
        rollback_recommended = False
        rollback_scope = 'NONE_AUTOMATIC'

    source_ref = {
        'path': str(path),
        'file_sha256': file_sha(path),
        'artifact_sha256': no_go.get('artifact_sha256'),
    }

    incident = {
        'type': 'POSTDEPLOY_INCIDENT',
        'decision': 'EXECUTION_FROZEN',
        'incident_id': incident_id,
        'correlation_id': incident_id,
        'source_postdeploy_no_go': source_ref,
        'blockers': blockers,
        'automatic_abort_triggered': True,
        'execution_frozen': True,
        'rc17_advancement_allowed': False,
        'resume_allowed': False,
        'deploy_allowed': False,
        'recommended_action': action,
        'rollback_recommended': rollback_recommended,
        'rollback_scope': rollback_scope,
        'previous_image_tag': previous_image,
        'previous_image_required_for_application_rollback': bool(rollback_recommended and not previous_image),
        'database_rollback_recommended': False,
        'database_downgrade_executed': False,
        'alembic_stamp_forbidden': True,
    }
    incident_res = write_artifact('POSTDEPLOY_INCIDENT.sealed.json', incident)
    # RC17.5: persist an append-only OPEN event; deleting ABORT alone cannot clear this freeze.
    state_before = incident_resolution_state(incident_id)
    if 'OPEN' not in (state_before.get('events') or []):
        append_incident_ledger('OPEN', incident_id, {'source_postdeploy_no_go': source_ref, 'blockers': blockers, 'recommended_action': action})
    incident_dir = STATE_DIR / 'incidents' / incident_id
    incident_dir.mkdir(parents=True, exist_ok=True)
    immutable_open = incident_dir / 'OPEN.sealed.json'
    if not immutable_open.exists():
        immutable_open.write_text((STATE_DIR / 'POSTDEPLOY_INCIDENT.sealed.json').read_text(encoding='utf-8'), encoding='utf-8')
        Path(str(immutable_open)+'.sha256').write_text(f"{file_sha(immutable_open)}  {immutable_open.name}\n", encoding='utf-8')

    # RC17.2 watches ABORT.sealed.json. Writing this artifact freezes resume/deploy
    # without executing rollback or mutating the database.
    abort = {
        'schema': 'go.r8.2-staging-deployment-control.v1',
        'type': 'AUTOMATIC_POSTDEPLOY_ABORT',
        'decision': 'ABORT',
        'actor': 'RC17.4_POSTDEPLOY_CONTROLLER',
        'reason': 'POSTDEPLOY_NO_GO',
        'incident_id': incident_id,
        'correlation_id': incident_id,
        'trigger_artifact': source_ref,
        'automatic': True,
        'execution_frozen': True,
        'database_downgrade_executed': False,
        'alembic_stamp_forbidden': True,
    }
    abort_res = write_artifact('ABORT.sealed.json', abort, schema='go.r8.2-staging-deployment-control.v1')

    recommendation = {
        'type': 'ROLLBACK_RECOMMENDATION',
        'decision': 'RECOMMENDATION_ONLY',
        'incident_id': incident_id,
        'correlation_id': incident_id,
        'source_postdeploy_no_go': source_ref,
        'blockers': blockers,
        'recommended_action': action,
        'rollback_recommended': rollback_recommended,
        'rollback_scope': rollback_scope,
        'previous_image_tag': previous_image,
        'operator_action_required': True,
        'automatic_rollback_executed': False,
        'database_rollback_recommended': False,
        'database_downgrade_executed': False,
        'database_rollback_requires_separate_review': True,
        'alembic_stamp_forbidden': True,
    }
    rec_res = write_artifact('ROLLBACK_RECOMMENDATION.sealed.json', recommendation)

    out = {
        'decision': 'EXECUTION_FROZEN',
        'incident_ledger': incident_resolution_state(incident_id),
        'incident_id': incident_id,
        'correlation_id': incident_id,
        'blockers': blockers,
        'recommended_action': action,
        'incident_artifact': incident_res,
        'abort_artifact': abort_res,
        'rollback_recommendation_artifact': rec_res,
        'automatic_rollback_executed': False,
        'database_downgrade_executed': False,
        'production_live': False,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def status() -> int:
    iv, incident = verify_embedded(STATE_DIR / 'POSTDEPLOY_INCIDENT.sealed.json')
    av, abort = verify_embedded(STATE_DIR / 'ABORT.sealed.json')
    rv, recommendation = verify_embedded(STATE_DIR / 'ROLLBACK_RECOMMENDATION.sealed.json')
    correlation_ids = {x.get('correlation_id') for x in (incident, abort, recommendation) if x}
    correlation_consistent = len(correlation_ids) <= 1
    ledger_state = incident_resolution_state(incident.get('incident_id') if incident else None)
    out = {
        'incident_valid': iv,
        'incident_ledger': ledger_state,
        'abort_valid': av,
        'rollback_recommendation_valid': rv,
        'correlation_consistent': correlation_consistent,
        'correlation_id': next(iter(correlation_ids), None) if correlation_consistent else None,
        'execution_frozen': bool(iv and incident and incident.get('execution_frozen')),
        'resume_allowed': False if iv else None,
        'deploy_allowed': False if iv else None,
        'automatic_rollback_executed': False,
        'database_downgrade_executed': False,
        'production_live': False,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if correlation_consistent else 33


def main() -> int:
    p = argparse.ArgumentParser(description='GO R8.2 RC17.4 post-deploy incident/evidence correlation controller')
    sub = p.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('correlate'); c.add_argument('--no-go-artifact')
    sub.add_parser('status')
    args = p.parse_args()
    if args.cmd == 'correlate':
        return correlate(Path(args.no_go_artifact) if args.no_go_artifact else None)
    return status()


if __name__ == '__main__':
    raise SystemExit(main())
