"""Separate fixed-runtime 4-vCPU ABBA; never changes original 2-vCPU acceptance."""
from pathlib import Path
import hashlib
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = '4048cbe64d0551130618d5d028204f770143aab7'
APP_TREE = 'b77840d31f0e31b046d8f3359c35630c75b8a02d'
FROZEN_WORKFLOW_SHA = '160720754942621bdff87dbf2a96e90395444567c7c932d3bb799d0622160330'


def validate_capacity(count, affinity, quota, machine):
    if machine != 'x86_64' or count != 4 or affinity != 4:
        raise ValueError('Requires a dedicated Linux x86_64 runner with exactly 4 visible/allowed vCPUs')
    if quota is not None and quota < 4:
        raise ValueError('CPU quota is below 4 vCPUs; a runner label is not capacity evidence')


def capacity():
    if platform.system() != 'Linux':
        raise ValueError('Linux required')
    # Fail closed on unknown cgroup layouts rather than silently ignoring quota.
    lines = Path('/proc/self/cgroup').read_text().splitlines()
    unified = [line.split(':', 2)[2] for line in lines if line.startswith('0::')]
    if len(unified) != 1:
        raise ValueError('Only an inspectable cgroup v2 environment is supported')
    cgroup = (Path('/sys/fs/cgroup') / unified[0].lstrip('/')).resolve()
    root = Path('/sys/fs/cgroup')
    if not cgroup.is_relative_to(root) or not cgroup.is_dir():
        raise ValueError('Cannot resolve cgroup quota; use a dedicated runner VM')
    quotas = []
    current = cgroup
    while True:
        file = current / 'cpu.max'
        if file.exists():
            limit, period = file.read_text().split()
            quotas.append({'path': str(file), 'value': limit + ' ' + period,
                           'cores': None if limit == 'max' else int(limit) / int(period)})
        if current == root:
            break
        current = current.parent
    if not quotas:
        raise ValueError('No inspectable CPU quota')
    effective = min((v['cores'] for v in quotas if v['cores'] is not None), default=None)
    memory = Path('/proc/meminfo').read_text()
    total_kib = int(next(line.split()[1] for line in memory.splitlines() if line.startswith('MemTotal:')))
    if total_kib < 7_800_000:
        raise ValueError('At least the observed 8-GiB-class baseline memory is required')
    count = os.cpu_count()
    affinity = sorted(os.sched_getaffinity(0))
    validate_capacity(count, len(affinity), effective, platform.machine())
    return {'cpu_count': count, 'affinity': affinity, 'quota': quotas,
            'cpuinfo': Path('/proc/cpuinfo').read_text(),
            'meminfo': memory,
            'platform': platform.platform(), 'original_2vcpu_acceptance': 'FAIL',
            'scope': 'Dedicated isolated 4-vCPU comparison; not production acceptance'}


def qualify(out):
    workflow = ROOT / '.github/workflows/multi-instance-transactions.yml'
    assert hashlib.sha256(workflow.read_bytes()).hexdigest() == FROZEN_WORKFLOW_SHA
    # Reuse the exact frozen regression selection, without shell evaluation.
    import yaml
    steps = yaml.safe_load(workflow.read_text())['jobs']['isolated']['steps']
    step = next(s for s in steps if s.get('name') == 'Payment recovery and payment-inventory boundary regressions')
    line = next(s.strip() for s in step['run'].splitlines() if s.strip().startswith('python -m pytest '))
    original = shlex.split(line)[3:]
    original = [s for s in original if not s.startswith('--junitxml=')]
    selections = [('original', original, 250), ('transaction', [
        'tests/test_capacity_atomic_order.py', 'tests/test_capacity_atomic_checkout.py',
        'tests/test_capacity_money_replay.py', '-q'], 24)]
    env = dict(os.environ, GO_TEST_DATABASE_URL=os.environ['GO_MULTI_DATABASE_URL'], APP_ENV='test',
               MODEL_GATEWAY_EXTERNAL_EGRESS_ENABLED='false', TRAVEL_INTELLIGENCE_ENABLED='false')
    for name, args, expected in selections:
        xml = out / (name + '.xml')
        subprocess.run([sys.executable, '-m', 'pytest', *args, '--junitxml=' + str(xml)],
                       cwd=ROOT / 'application', env=env, check=True)
        suite = ET.parse(xml).getroot().find('testsuite')
        assert int(suite.get('tests')) == expected
        assert all(int(suite.get(k, '0')) == 0 for k in ('failures', 'errors', 'skipped'))


def execute():
    evidence = capacity()  # Reject wrong hardware before any database operation.
    if sys.argv[1:] == ['--preflight-only']:
        print(json.dumps(evidence, indent=2))
        return 0
    assert not sys.argv[1:], 'Only --preflight-only is supported'
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(['git', 'rev-parse', 'HEAD:application'], cwd=ROOT, text=True).strip()
    assert tree == APP_TREE, 'Application changed: requires a new explicitly reviewed experiment binding'
    assert os.environ['GO_MULTI_DATABASE_URL'].startswith('postgresql+psycopg://')
    out = ROOT / 'four-vcpu-qualification'
    out.mkdir(exist_ok=False)
    evidence.update(head=head, application_tree=tree)
    (out / 'hardware.json').write_text(json.dumps(evidence, indent=2) + '\n')
    qualify(out)
    os.environ['EXPECTED_HEAD'] = head
    sys.path.insert(0, str(ROOT / 'ci'))
    import cpu_candidate
    code = cpu_candidate.main()
    # Keep the same comparison implementation/configuration. Caller archives its
    # output under a distinct four-vCPU artifact name alongside hardware evidence.
    after = capacity()
    assert after['cpu_count'] == evidence['cpu_count'] and after['affinity'] == evidence['affinity']
    assert after['quota'] == evidence['quota'], 'CPU allocation changed during experiment'
    return code


def main():
    global ROOT
    capacity()  # Fail before checkout/DB work on unsupported hardware.
    if sys.argv[1:] == ['--preflight-only']:
        return execute()
    assert not sys.argv[1:]
    original = ROOT
    checkout = original / 'four-vcpu-fixed-worktree'
    subprocess.run(['git', 'worktree', 'add', '--detach', str(checkout), CANDIDATE], cwd=original, check=True)
    try:
        ROOT = checkout
        return execute()
    finally:
        ROOT = original
        for name in ('four-vcpu-qualification', 'cpu-candidate-evidence'):
            source = checkout / name
            if source.exists():
                shutil.copytree(source, original / name)  # refuse to mix runs
        subprocess.run(['git', 'worktree', 'remove', '--force', str(checkout)], cwd=original, check=True)


if __name__ == '__main__':
    raise SystemExit(main())
