#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, pathlib, subprocess, sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
rr=ROOT/'gate_runtime'/'python'
manifest=ROOT/'gate_runtime'/'RUNTIME_MANIFEST.json'
source_file=ROOT/'gate_runtime'/'RUNTIME_SOURCE.json'
lock_file=ROOT/'gate_runtime'/'requirements.lock'
wheel_sums=ROOT/'gate_runtime'/'WHEELHOUSE_SHA256SUMS.txt'
def block(msg): print('R8.2_GATE_RUNTIME: BLOCK'); print(msg); raise SystemExit(1)
for p,label in [(rr,'RUNTIME_ROOT_MISSING'),(manifest,'RUNTIME_MANIFEST_MISSING'),(source_file,'RUNTIME_SOURCE_MISSING'),(lock_file,'REQUIREMENTS_LOCK_MISSING'),(wheel_sums,'WHEELHOUSE_CHECKSUMS_MISSING')]:
    if not p.exists(): block(label)
py=rr/'bin'/'python3'
if not py.is_file(): block('PYTHON_MISSING')
try:
    d=json.loads(manifest.read_text()); s=json.loads(source_file.read_text())
except Exception as e: block('RUNTIME_METADATA_INVALID:'+repr(e))
if d.get('runtime_release')!='R3.1.7': block('RUNTIME_RELEASE_MISMATCH')
if d.get('python_version')!='3.13.5': block('PYTHON_VERSION_MANIFEST_MISMATCH')
if d.get('target_glibc_max')!='2.35': block('GLIBC_TARGET_MISMATCH')
runtime_sha=s.get('expected_sha256')
if not isinstance(runtime_sha,str) or len(runtime_sha)!=64 or any(c not in '0123456789abcdef' for c in runtime_sha): block('RUNTIME_SOURCE_SHA_CONTRACT_INVALID')
if d.get('source_sha256')!=s.get('expected_sha256'): block('RUNTIME_SOURCE_SHA_MANIFEST_MISMATCH')
if d.get('source_artifact')!=s.get('artifact_name'): block('RUNTIME_SOURCE_ARTIFACT_MISMATCH')
if d.get('requirements_lock_sha256')!=hashlib.sha256(lock_file.read_bytes()).hexdigest(): block('REQUIREMENTS_LOCK_SHA_MISMATCH')
if d.get('wheelhouse_checksums_sha256')!=hashlib.sha256(wheel_sums.read_bytes()).hexdigest(): block('WHEELHOUSE_CHECKSUMS_SHA_MISMATCH')
expected=d.get('tree_sha256')
if not isinstance(expected,str) or len(expected)!=64: block('TREE_SHA256_MISSING')
h=hashlib.sha256()
for p in sorted(x for x in rr.rglob('*') if x.is_file() and '__pycache__' not in x.parts and x.suffix not in {'.pyc','.pyo'}):
    rel=p.relative_to(rr).as_posix().encode(); h.update(rel+b'\0'); h.update(hashlib.sha256(p.read_bytes()).digest())
actual=h.hexdigest()
if actual!=expected: block('TREE_SHA256_MISMATCH expected='+expected+' actual='+actual)
# Verify the three frozen root package versions from the installed runtime.
code='import importlib.metadata as m; print(m.version("pytest")); print(m.version("fastapi")); print(m.version("SQLAlchemy"))'
r=subprocess.run([str(py),'-c',code],capture_output=True,text=True)
if r.returncode: block('LOCKED_ROOT_IMPORT_FAILED:'+r.stderr.strip())
if r.stdout.splitlines()!=['9.0.2','0.128.2','2.0.50']: block('LOCKED_ROOT_VERSION_MISMATCH:'+repr(r.stdout.splitlines()))
print('R8.2_GATE_RUNTIME: PASS')
print('runtime_release=R3.1.7')
print('python=3.13.5')
print('runtime_source_sha256='+s['expected_sha256'])
print('tree_sha256='+actual)
