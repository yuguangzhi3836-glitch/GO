"""Exact two-file operator maintenance; not a Task executor or deployment."""
import datetime, hashlib, json, os, pathlib, shutil, stat, subprocess, sys

ROOT = pathlib.Path('/opt/go-hk-agent-rebuilt/hk_agent')
EXPECTED = {
    'test_pr.py': ('d1c454fc4b4c3066cbd6e8195b686de4ec676c2b6f67d4cf33d332ad4cedf1f0', 'dda3a4410b43d35d6bbc95c3492728eb5851cd51bcebb1122d74865fe59275f6'),
    'transport.py': ('af8261568fb7158f3bd6f620f3a405118b1ae77d3d662b764e62c3fe260e5fcb', 'c48bf32f8cddfdc2d577df04f61a87b35d14f4cdf0cc2c8e45a7b517117e724a'),
}
def run(args, check=True):
    return subprocess.run(args, capture_output=True, text=True, check=check, timeout=30)
def digest(data):
    return hashlib.sha256(data).hexdigest()
def info(p):
    s = p.lstat()
    assert stat.S_ISREG(s.st_mode) and not p.is_symlink(), str(p)
    return dict(sha256=digest(p.read_bytes()), size=s.st_size, uid=s.st_uid,
                gid=s.st_gid, mode=stat.S_IMODE(s.st_mode))
def protected():
    paths = sorted(p for p in ROOT.glob('*.py') if p.name not in EXPECTED)
    paths += [pathlib.Path(p) for p in [
        '/usr/local/libexec/go-hk-test-pr/Dockerfile.go-application-python-v2',
        '/etc/go-hk-agent/agent.json',
        '/etc/systemd/system/go-hk-agent.service', '/etc/systemd/system/go-hk-agent.timer']]
    return {str(p): info(p) for p in paths}
def runtime():
    lines = sorted(run(['docker','ps','--no-trunc','--format','{{.ID}}|{{.Image}}|{{.Names}}']).stdout.splitlines())
    return dict(containers=lines, sha256=digest(('\n'.join(lines)+'\n').encode()))
def active(unit):
    return run(['systemctl','is-active',unit], check=False).stdout.strip()

payload = json.load(sys.stdin)
assert set(payload) == set(EXPECTED)
data = {n: payload[n].encode('utf-8') for n in EXPECTED}
for n, content in data.items():
    assert digest(content) == EXPECTED[n][1], n + ': approved bytes mismatch'
    compile(content, str(ROOT/n), 'exec')
before = {n: info(ROOT/n) for n in EXPECTED}
assert all(before[n]['sha256'] == EXPECTED[n][0] for n in EXPECTED), 'live baseline moved'
assert all(before[n]['uid'] == 0 and before[n]['gid'] == 0 and before[n]['mode'] == 0o644 for n in EXPECTED)
assert active('go-hk-agent.timer') == 'active', 'timer not active'
assert active('go-hk-agent.service') == 'inactive', 'agent busy; no change'
stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backup = pathlib.Path('/var/backups')/('HK-CHANGE-'+stamp+'-issue184')
backup.mkdir(mode=0o700)
receipt = dict(schema='issue184-host-install-v1', candidate_sha='9c76fc579383fa2270af90bc67b67a17454d37bd',
               started_at=stamp, backup=str(backup), before=before, protected_before=protected(),
               runtime_before=runtime(), deployment_performed=False, migration_performed=False,
               task_or_ledger_mutated=False, cc_changed=False)
def save():
    (backup/'receipt.json').write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
save()
staged = {}
for n in EXPECTED:
    shutil.copy2(ROOT/n, backup/(n+'.before'))
    assert info(backup/(n+'.before')) == before[n]
    p = ROOT/(n+'.issue184-'+stamp)
    with p.open('xb') as f:
        f.write(data[n]); f.flush(); os.fsync(f.fileno())
    os.chown(p, before[n]['uid'], before[n]['gid']); os.chmod(p, before[n]['mode'])
    assert digest(p.read_bytes()) == EXPECTED[n][1]
    staged[n] = p
replaced = []
try:
    run(['systemctl','stop','go-hk-agent.timer'])
    assert active('go-hk-agent.service') == 'inactive', 'agent became busy; no replacement'
    assert {n:info(ROOT/n) for n in EXPECTED} == before, 'baseline changed during staging'
    for n in EXPECTED:
        os.replace(staged[n], ROOT/n); replaced.append(n)
    smoke = run(['python3','-B','-c',
        "import sys,json;sys.path.insert(0,'/opt/go-hk-agent-rebuilt');from hk_agent import test_pr,transport;"
        "assert test_pr.STANDARD_DEPENDENCY_PROFILE_SHA256=='c3140ecf1e38bf7f635ff6a80758677441a56866d0aa18727a2f6193adc707e1';"
        "assert 'TEST_PR_DEPENDENCY_ENVIRONMENT_REJECT' in transport.FAILURE_REASON_CODES;"
        "print(json.dumps({'agent_version':transport.VERSION,'executor_version':test_pr.EXECUTOR_VERSION,'failure_reason_count':len(transport.FAILURE_REASON_CODES)}))"])
    receipt['import_smoke'] = json.loads(smoke.stdout)
    receipt['after'] = {n:info(ROOT/n) for n in EXPECTED}
    assert all(receipt['after'][n]['sha256'] == EXPECTED[n][1] for n in EXPECTED)
    receipt['protected_after'] = protected(); receipt['runtime_after'] = runtime()
    assert receipt['protected_before'] == receipt['protected_after'], 'protected file changed'
    assert receipt['runtime_before'] == receipt['runtime_after'], 'business container changed'
    receipt['result'] = 'INSTALLED'
except BaseException as e:
    for n in reversed(replaced):
        p = ROOT/(n+'.rollback-'+stamp); shutil.copy2(backup/(n+'.before'),p); os.replace(p,ROOT/n)
        assert info(ROOT/n) == before[n]
    receipt['result'] = 'ROLLED_BACK' if replaced else 'NOT_INSTALLED'
    receipt['error'] = type(e).__name__+': '+str(e)
    raise
finally:
    for p in staged.values():
        if p.exists(): p.unlink()
    run(['systemctl','start','go-hk-agent.timer'])
    receipt['timer_after'] = active('go-hk-agent.timer')
    receipt['finished_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save()
    print(json.dumps(receipt,sort_keys=True))
assert receipt['timer_after'] == 'active'
