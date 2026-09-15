#!/usr/bin/env python3
"""Isolated verification: ephemeral keys, local Git fixtures, no runtime paths."""
import hashlib
import io
import json
import os
import pathlib
import sys
import unittest
from contextlib import redirect_stderr

ROOT = pathlib.Path(__file__).resolve().parent
OUT = pathlib.Path(sys.argv[1] if len(sys.argv)>1 else '/tmp/go-deploy-entry-checks').resolve()
OUT.mkdir(parents=True,exist_ok=True)

def audit(event,args):
    if event in ('socket.connect','socket.connect_ex','socket.getaddrinfo'):
        raise RuntimeError('isolated checks forbid network')
    if event=='subprocess.Popen':
        executable,argv,cwd,env=args
        if executable!='/usr/bin/git' or not env or env.get('GIT_ALLOW_PROTOCOL')!='file':
            raise RuntimeError('isolated checks allow only local fixture Git')
    if event=='open':
        path=args[0]
        if isinstance(path,(str,bytes)):
            path=os.fsdecode(path)
            if path.startswith(('/etc/go-command-center/','/var/lib/go-command-center/','/etc/go-hk-agent/')):
                raise RuntimeError('isolated checks forbid runtime credentials and state')

sys.addaudithook(audit)
sys.path.insert(0,str(ROOT/'tests'))
import test_deploy_entry
log=io.StringIO()
suite=unittest.defaultTestLoader.loadTestsFromModule(test_deploy_entry)
result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
with redirect_stderr(log): legacy_exit=test_deploy_entry.bridge.run_tests()
summary={'schema_version':'1','status':'PASS' if result.wasSuccessful() and not legacy_exit else 'FAIL',
    'new_tests':result.testsRun,'new_failures':len(result.failures),'new_errors':len(result.errors),'new_skips':len(result.skipped),
    'legacy_self_test_exit':legacy_exit,'legacy_tests':22,'network_access':'FORBIDDEN',
    'hong_kong':'NOT_ACCESSED','production':'NOT_ACCESSED','live_tasks_published':0,
    'crypto_keys':'EPHEMERAL_SYNTHETIC_ONLY','hk_executor':'ARCHIVED_ADAPTER_WITH_FAKE_EXECUTOR',
    'different_image_formal_hk_e2e':'NOT_PROVEN',
    'files':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ROOT.rglob('*'))
             if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}}
(OUT/'checks.log').write_text(log.getvalue())
(OUT/'summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
print(log.getvalue(),end=''); print(json.dumps({k:v for k,v in summary.items() if k!='files'},sort_keys=True))
sys.exit(0 if summary['status']=='PASS' else 1)
