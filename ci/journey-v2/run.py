"""Run the real application on a fresh isolated database, then drive Chromium."""
import json, os, pathlib, shutil, subprocess, sys, time, urllib.request, uuid

root = pathlib.Path(__file__).resolve().parents[2]
evidence = root / 'journey-evidence'
binding = json.loads((evidence / 'source-binding.json').read_text())
state = pathlib.Path(os.environ['RUNNER_TEMP']) / ('go-journey-' + uuid.uuid4().hex)
env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
command = [sys.executable, str(root / 'application/scripts/acceptance_runtime.py'),
    '--source', str(root / 'application'), '--fingerprint', str(evidence / 'source-fingerprint.json'),
    '--expected-tree', binding['source_tree_sha256'], '--state', str(state), '--port', '4186', '--journey-suppliers', '--hotel-price-scenarios', '--operations-roles']
with (evidence / 'runtime.log').open('w') as log:
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env)
    try:
        for _ in range(120):
            if process.poll() is not None:
                raise RuntimeError('ISOLATED_RUNTIME_START_FAILED: inspect runtime.log')
            try:
                with urllib.request.urlopen('http://127.0.0.1:4186/__acceptance/binding', timeout=1) as response:
                    actual = json.load(response)
                assert actual['source_tree_sha256'] == binding['source_tree_sha256']
                break
            except OSError:
                time.sleep(.5)
        else:
            raise TimeoutError('ISOLATED_RUNTIME_NOT_READY')
        # Mocked-request widget tests are separate evidence, never HTTP journey proof.
        with (evidence / 'rental-widget.log').open('w') as widget_log:
            widget_log.write('Scope: isolated browser widget with mocked request; not real API journey evidence.\n')
            widget_log.flush()
            widget = subprocess.run(['node', '--test', str(root / 'ci/journey-v2/rental-operations-widget.mjs')],
                stdout=widget_log, stderr=subprocess.STDOUT, env=env)
        result = subprocess.run(['node', str(root / 'ci/journey-v2/browser.mjs')], env=dict(env,
            GO_JOURNEY_STATE=str(state), GO_JOURNEY_EVIDENCE=str(evidence)))
        capacity = subprocess.run([sys.executable, str(root / 'ci/journey-v2/capacity.py'),
            str(state), str(evidence)], env=env)
        audit = subprocess.run([sys.executable, str(root / 'ci/journey-v2/ledger.py'),
            str(state), str(evidence)], env=env)
        hotel_audit = subprocess.run([sys.executable, str(root / 'ci/journey-v2/hotel-ledger.py'),
            str(state), str(evidence)], env=env)
        operations_audit = subprocess.run([sys.executable, str(root / 'ci/journey-v2/operations-ledger.py'),
            str(state), str(evidence)], env=env)
        for name in ['runtime-binding.json', 'fixture-identities.json', 'hotel-price-fixtures.json']:
            shutil.copyfile(state / name, evidence / name)
        sys.exit(widget.returncode or result.returncode or capacity.returncode or audit.returncode or hotel_audit.returncode or operations_audit.returncode)
    finally:
        process.terminate()
        try: process.wait(timeout=15)
        except subprocess.TimeoutExpired: process.kill(); process.wait()
        # Do not archive the database, cookies, passwords, or authentication bodies.
        shutil.rmtree(state, ignore_errors=True)
