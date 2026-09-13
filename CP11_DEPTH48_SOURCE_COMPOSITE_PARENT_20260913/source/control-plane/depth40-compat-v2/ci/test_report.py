"""Capture actual regression output and source hashes; no invented runtime PASS."""
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import platform
import sys
import unittest

root=Path(__file__).resolve().parents[1]
suite=unittest.defaultTestLoader.discover(str(root/'tests'))
stream=io.StringIO()
result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
text=stream.getvalue()
sys.stdout.write(text)
out=root/'evidence';out.mkdir(exist_ok=True)
(out/'UNIT_RAW.log').write_text(text)
sources={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
         for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and 'evidence' not in p.relative_to(root).parts}
report={'timestamp_utc':datetime.now(timezone.utc).isoformat(),'platform':platform.platform(),'python':platform.python_version(),
        'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
        'result':'PASS' if result.wasSuccessful() else 'FAIL','scope':'PYTHON_CRYPTO_FILESYSTEM_WITH_SIMULATED_DOCKER',
        'docker_execution':False,'hk_execution':'NOT_RUN','production':'HOLD','sources_sha256':sources}
(out/'LOCAL_RESULTS.json').write_text(json.dumps(report,indent=2)+'\n')
sys.exit(0 if result.wasSuccessful() else 1)
