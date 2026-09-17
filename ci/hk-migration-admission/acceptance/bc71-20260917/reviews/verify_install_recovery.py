"""Local fault injection only: all installation paths redirect into temporary dirs.

No subprocess, systemctl, Docker, network or real host installation is invoked.
Exercises each reviewed installer's actual exception/rollback/finally control flow.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def execute(kind):
    installer = ROOT / 'install' / ('install_' + kind + '.py')
    mod = load('review_install_' + kind, installer)
    package = json.loads((ROOT / 'install' / (
        'SOURCE_PACKAGE.json' if kind == 'source' else 'ADMISSION_PACKAGE.json')).read_text())
    with tempfile.TemporaryDirectory(prefix='c14-install-recovery-') as raw:
        temporary = Path(raw)

        def mapped(value):
            path = Path(value)
            if path == temporary or temporary in path.parents:
                return path
            if path.is_absolute():
                return temporary / str(path).lstrip('/')
            return path

        mod.pathlib = SimpleNamespace(Path=mapped)
        timers = {}

        def fake_run(argv, check=True):
            if argv[:2] == ['systemctl', 'stop']:
                timers[argv[2]] = 'inactive'
            elif argv[:2] == ['systemctl', 'start']:
                timers[argv[2]] = 'active'
            elif argv[:2] == ['docker', 'ps']:
                return SimpleNamespace(stdout=' '.join(sorted(mod.SERVICES)))
            elif argv[:2] == ['docker', 'inspect']:
                return SimpleNamespace(stdout=json.dumps([{
                    'Config': {'Labels': {'com.docker.compose.service': argv[2]}},
                    'Image': mod.LIVE_IMAGE}]))
            else:
                raise AssertionError('Unexpected external command: ' + repr(argv))
            return SimpleNamespace(stdout='', returncode=0)

        mod.run = fake_run
        mod.state = lambda unit: timers.get(unit, 'active') if unit.endswith('.timer') else 'inactive'
        mapped('/var/backups').mkdir(parents=True)
        injected = {'value': False}
        original_files = {}

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(sys, 'argv', [str(installer), 'hk-staging']))
            stack.enter_context(patch.object(sys, 'stdin', io.StringIO(json.dumps(package))))
            if kind == 'source':
                manifest = package['manifest']
                entries = [e for e in manifest['files'] if e['host'] == 'hk-staging']
                metadata = {e['target']: e['before'] for e in entries}
                metadata.update(manifest['guards']['hk-staging'])
                markers = {}
                for target, before in metadata.items():
                    p = mapped(target)
                    p.parent.mkdir(parents=True, exist_ok=True)
                    if before.get('exists') is not False:
                        marker = ('ORIGINAL:' + target).encode()
                        p.write_bytes(marker)
                        markers[marker] = before
                        original_files[p] = marker
                def fake_info(path):
                    p = mapped(path)
                    if not p.exists():
                        return {'exists': False}
                    content = p.read_bytes()
                    if content in markers:
                        return markers[content]
                    st = p.stat()
                    return {'sha256': hashlib.sha256(content).hexdigest(),
                            'mode': st.st_mode & 0o777, 'uid': 0, 'gid': 0, 'regular': True}
                mod.info = fake_info
                mod.safe_parent = lambda path: None
                mod.runtime = lambda: ['UNCHANGED_LOCAL_FIXTURE']
                mod.HOSTS['hk-staging']['ledger'] = str(mapped(mod.HOSTS['hk-staging']['ledger']))
                mapped(mod.HOSTS['hk-staging']['ledger']).mkdir(parents=True)
                mapped('/var/lib/go-hk-deployctl').mkdir(parents=True)
                first = mapped(entries[0]['target'])
                replacement = package['files'][entries[0]['source']].encode()
                def fault(path):
                    if not injected['value'] and first.read_bytes() == replacement:
                        injected['value'] = True
                        raise OSError('C14_INJECTED_DIRECTORY_FSYNC_AFTER_REPLACE')
                mod.sync_dir = fault
            else:
                mapped('/etc').mkdir(parents=True)
                module_dir = '/usr/local/libexec/go-hk-deployctl-runtime'
                module_path = mapped(module_dir) / 'hk_candidate_contract.py'
                module_path.parent.mkdir(parents=True)
                module_path.write_bytes((ROOT / 'review-bc71/hk-staging/source/executor/runtime/hk_candidate_contract.py').read_bytes())
                helper = load('c14_installed_contract', module_path)
                helper.HK_STORE = mapped(helper.HK_STORE)
                stack.enter_context(patch.dict(sys.modules, {'hk_candidate_contract': helper}))
                mod.safe = lambda path: None
                first = helper.HK_STORE / (mod.CONTRACT_SHA256 + '.json')
                def fault(path):
                    if not injected['value'] and first.exists():
                        injected['value'] = True
                        raise OSError('C14_INJECTED_DIRECTORY_FSYNC_AFTER_REPLACE')
                mod.sync = fault
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                try:
                    mod.main()
                except OSError as exc:
                    assert str(exc) == 'C14_INJECTED_DIRECTORY_FSYNC_AFTER_REPLACE'
                else:
                    raise AssertionError('Expected injected failure')
            assert injected['value']
            assert all(p.read_bytes() == original for p, original in original_files.items())
            assert timers and all(status == 'active' for status in timers.values())
            if kind == 'source':
                assert all(not mapped(e['target']).exists() for e in entries if e['before'].get('exists') is False)
                assert not mapped('/var/lib/go-hk-deployctl/migrations-v1').exists()
                expected = 'SOURCE_RESTORED'
            else:
                assert not first.exists()
                expected = 'ADMISSION_RESTORED'
            receipt = json.loads(output.getvalue().splitlines()[-1])
            assert receipt['result'] == expected
            return {'installer': kind, 'status': 'PASS', 'injected': 'FSYNC_AFTER_REPLACE',
                    'restoration': expected, 'timers_restored': True,
                    'installer_sha256': hashlib.sha256(installer.read_bytes()).hexdigest(),
                    'scope': 'LOCAL_TEMPORARY_FILES_AND_FAKE_EXTERNAL_COMMANDS_ONLY'}


if __name__ == '__main__':
    print(json.dumps([execute('source'), execute('admission')], indent=2, sort_keys=True))
