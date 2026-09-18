"""Read-only, fixed-workspace graph checks for an explicitly non-migrating image.

No database connection, migration command, caller path, or caller program.
Both immutable images must have the exact same complete migration source graph.
"""
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import stat

PROGRAM_SHA256 = '4db9cba95c05cb5f5d0ad661aa2686f237206b9b5bdf18d8736983d35392c88c'
PENDING = Path('/var/lib/go-hk-deployctl/migrations-v1/pending.json')

class Reject(ValueError):
    pass

def require_clear():
    if PENDING.exists() or PENDING.is_symlink():
        raise Reject('E_MIGRATION_UNRESOLVED_ATTEMPT')

def program():
    path = Path(__file__).with_name('same_revision_program.py')
    if not stat.S_ISREG(path.lstat().st_mode): raise Reject('E_SAME_SOURCE_PROGRAM_TYPE')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROGRAM_SHA256: raise Reject('E_SAME_SOURCE_PROGRAM_HASH')
    return raw.decode() + '\nentry()\n'

def check_images(runner, contract):
    if (contract.get('schema') not in ('go.hk-candidate-contract.v2', 'go.hk-candidate-contract.v3')
        or contract.get('migration_required') is not False
        or contract['baseline_revision'] != contract['target_revision']
        or contract['migration_source_digest'] != contract['baseline_migration_source_digest']):
        raise Reject('E_SAME_SOURCE_CONTRACT')
    if contract.get('schema') == 'go.hk-candidate-contract.v3':
        topology = contract.get('topology')
        if (not isinstance(topology, dict)
            or set(topology) != {'topology_id','topology_version','topology_sha256','baseline_topology_version','media_rollback_compatible'}
            or topology.get('topology_id') != 'HK_STAGING_BUSINESS_TOPOLOGY'
            or type(topology.get('topology_version')) is not int or topology['topology_version'] != 2
            or topology.get('topology_sha256') != '3efa422ebcfeee97528e829228a5f1c78a91151c88c50c606bab95479f3fddb1'
            or type(topology.get('baseline_topology_version')) is not int or topology['baseline_topology_version'] not in (1,2)
            or topology.get('media_rollback_compatible') is not True):
            raise Reject('E_SAME_SOURCE_TOPOLOGY')
    elif 'topology' in contract:
        raise Reject('E_SAME_SOURCE_TOPOLOGY_SCHEMA')
    spec = json.dumps({'revision':contract['target_revision'],
                       'graph_sha256':contract['migration_source_digest']},sort_keys=True,separators=(',',':'))
    expected = {'source':'PASS','revision':contract['target_revision'],
                'graph_sha256':contract['migration_source_digest'],'migration_required':False}
    for image in (contract['expected_current_image_id'], contract['candidate']['image_id']):
        name = 'go-same-revision-' + secrets.token_hex(12)
        argv = ['/usr/bin/docker','run','--name',name,'--network','none','--read-only',
                '--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','64',
                '--memory','256m','--cpus','0.50','--tmpfs','/tmp:rw,nosuid,nodev,size=64m',
                '--workdir','/workspace','--env','HOME=/tmp','--env','PYTHONPYCACHEPREFIX=/tmp/pycache',
                '--entrypoint','/usr/local/bin/python',image,'-c',program(),'source',spec]
        try:
            result = runner.run(argv)
            if result.returncode: raise Reject('E_SAME_SOURCE_FAILED')
            try: value = json.loads(result.stdout)
            except (ValueError,TypeError) as exc: raise Reject('E_SAME_SOURCE_OUTPUT') from exc
            if value != expected: raise Reject('E_SAME_SOURCE_MISMATCH')
        except subprocess.TimeoutExpired as exc:
            raise Reject('E_SAME_SOURCE_TIMEOUT') from exc
        finally:
            cleaned = runner.run(['/usr/bin/docker','rm','-f',name])
            if cleaned.returncode: raise Reject('E_SAME_SOURCE_CLEANUP')
