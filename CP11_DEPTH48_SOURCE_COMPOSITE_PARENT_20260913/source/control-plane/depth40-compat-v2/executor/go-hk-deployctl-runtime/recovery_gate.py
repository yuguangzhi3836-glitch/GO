"""Verify preparation evidence before DEPLOY; never execute recovery or sign tasks."""
import base64
import hashlib
import json
import math
from pathlib import Path
import time
from cryptography.hazmat.primitives import serialization


def verify_plan(site, *, key='/etc/go-hk-agent/keys/task-verify.pub', now=None):
    binding = site['recovery_plan']
    path = Path(binding['path'])
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1048576:
        raise ValueError('RECOVERY_PLAN_MISSING')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != binding['sha256']:
        raise ValueError('RECOVERY_PLAN_INTEGRITY')
    p = json.loads(raw)
    unsigned = {k: v for k, v in p.items() if k != 'signature'}
    try:
        pub = serialization.load_ssh_public_key(Path(key).read_bytes())
        pub.verify(base64.b64decode(p['signature'], validate=True),
                   json.dumps(unsigned, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode())
    except Exception as exc:
        raise ValueError('RECOVERY_PLAN_SIGNATURE') from exc
    if (p.get('purpose'), p.get('environment'), p.get('authority'), p.get('status')) != (
            'DEPLOY_FAILURE_RECOVERY_PREPARATION', 'HK-STAGING-01', 'GO-COMMAND-CENTER', 'APPROVED'):
        raise ValueError('RECOVERY_PLAN_AUTHORITY')
    for name in ('candidate', 'previous'):
        if p.get(name) != site[name]:
            raise ValueError('RECOVERY_PLAN_PROFILE_BINDING')
    when = time.time() if now is None else now
    if isinstance(p.get('valid_until'), bool) or not isinstance(p.get('valid_until'), (int, float)) or not math.isfinite(p['valid_until']) or p['valid_until'] <= when:
        raise ValueError('RECOVERY_PLAN_EXPIRED')
    if p.get('automatic_recovery') is not False or p.get('fresh_recovery_authorization_required') is not True:
        raise ValueError('RECOVERY_PLAN_BOUNDARY')
    if p.get('failure_modes') != ['partial_recreate', 'readiness_failure', 'postcheck_failure']:
        raise ValueError('RECOVERY_PLAN_COVERAGE')
    for name in ('backup_restore_evidence', 'stop_restore_procedure'):
        item = p.get(name, {})
        target = Path(item.get('path', ''))
        if not target.is_absolute() or target.is_symlink() or not target.is_file():
            raise ValueError('RECOVERY_PLAN_EVIDENCE_MISSING')
        if hashlib.sha256(target.read_bytes()).hexdigest() != item.get('sha256'):
            raise ValueError('RECOVERY_PLAN_EVIDENCE_INTEGRITY')
    return {'plan_sha256': binding['sha256'], 'automatic_recovery': False}
