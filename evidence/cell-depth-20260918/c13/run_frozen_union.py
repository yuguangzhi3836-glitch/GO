"""C13 executes only after final C14 source-bound review is available."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

repo = Path('/workspace/scratch/a682af655fba/cell-depth-20260918')
output = Path(__file__).parent
expected_sha, gate_path = sys.argv[1:]
gate = Path(gate_path)

def git(*args):
    return subprocess.check_output(['git', *args], cwd=repo).decode().strip()

def binding():
    head = git('rev-parse', 'HEAD')
    if head != expected_sha:
        raise RuntimeError(f'Candidate moved: {head}')
    tracked = sorted(git('ls-files', 'application').splitlines(), key=lambda x:x.encode())
    manifest = []
    fingerprint = hashlib.sha256()
    for path in tracked:
        content = subprocess.check_output(['git', 'show', f'{head}:{path}'], cwd=repo)
        actual = (repo / path).read_bytes()
        if actual != content:
            raise RuntimeError(f'Working file differs from frozen source: {path}')
        digest = hashlib.sha256(content).hexdigest()
        manifest.append({'path': path, 'sha256': digest, 'bytes': len(content)})
        fingerprint.update((path+'\0'+digest+'\n').encode())
    return {'candidate_sha':head, 'application_tree':git('rev-parse','HEAD:application'),
        'application_file_count':len(manifest), 'application_fingerprint_sha256':fingerprint.hexdigest()},manifest

before, manifest = binding()
gate_bytes = gate.read_bytes()
gate_text = gate_bytes.decode()
if before['application_tree'] not in gate_text or 'PASS' not in gate_text:
    raise RuntimeError('C14 document does not state a passing verdict for frozen application tree')
evidence = repo / 'evidence/cell-depth-20260918'
selected = set()
for document in evidence.rglob('*.json'):
    if document.name == 'SHA256SUMS.json':
        continue
    for path in re.findall(r'(?:application/)?tests/[A-Za-z0-9_./-]+\.py', document.read_text()):
        path = path.removeprefix('application/')
        if (repo / 'application' / path).is_file():
            selected.add(path)
tests = sorted(selected)
if len(tests) < 55:
    raise RuntimeError('Unexpectedly small affected test union')
command = [sys.executable,'-m','pytest',*tests,'-q','-p','no:cacheprovider','--tb=short',
    f'--junitxml={output / "final-union.xml"}']
environment = os.environ.copy()
environment.update(APP_ENV='test',PYTHONDONTWRITEBYTECODE='1',
    GO_TEST_DB_PATH=str(Path(tempfile.mkdtemp(prefix='c13_union_')) / 'isolated.sqlite'))
record = {'source':before,'c14_path':str(gate),
    'c14_sha256':hashlib.sha256(gate_bytes).hexdigest(),
    'c14_review_read_before_test_start':True,
    'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'cwd':str(repo/'application'),'argv':command,'test_files':tests,
    'test_file_count':len(tests),'environment':{k:environment[k] for k in ['APP_ENV','PYTHONDONTWRITEBYTECODE','GO_TEST_DB_PATH']}}
(output/'FINAL_COMMAND.json').write_text(json.dumps(record,indent=2)+'\n')
(output/'APPLICATION_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'started':True,'test_file_count':len(tests),'source':before}),flush=True)
with (output/'final-union.log').open('w') as log:
    result=subprocess.run(command,cwd=repo/'application',env=environment,stdout=log,stderr=subprocess.STDOUT)
record['exit_code']=result.returncode
record['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
after,_=binding()
record['source_unchanged_after_execution']=after==before
tree=ET.parse(output/'final-union.xml')
cases=tree.findall('.//testcase')
record['junit']={'tests':len(cases),'unique_cases':len({(c.get('classname'),c.get('name')) for c in cases}),
    'failures':len(tree.findall('.//failure')),'errors':len(tree.findall('.//error')),
    'skipped':len(tree.findall('.//skipped')),
    'declared_tests':sum(int(s.get('tests',0)) for s in tree.findall('.//testsuite'))}
record['raw_sha256']={name:hashlib.sha256((output/name).read_bytes()).hexdigest()
    for name in ['final-union.xml','final-union.log','APPLICATION_MANIFEST.json']}
(output/'FINAL_COMMAND.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record['junit']),flush=True)
print('exit_code',record['exit_code'],flush=True)
