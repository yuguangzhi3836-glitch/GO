#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,pathlib,subprocess,sys,zipfile,email.parser
ROOT=pathlib.Path(__file__).resolve().parents[1]
def block(m): print('R3.1.7_FINAL_SEAL_DEBT_CLOSURE: BLOCK'); print(m); raise SystemExit(1)
# 1 runtime source identity
src=json.loads((ROOT/'gate_runtime/RUNTIME_SOURCE.json').read_text())
expected=src.get('expected_sha256')
if not isinstance(expected,str) or len(expected)!=64 or any(c not in '0123456789abcdef' for c in expected): block('RUNTIME_SHA_INVALID')
if src.get('artifact_name')!='gate_runtime_python_cpython-3.13.5_ubuntu-22.04-x86_64_r3.1.7.tar.gz': block('RUNTIME_ARTIFACT_NOT_FIXED')
# 2 exact lock + wheelhouse
lock=(ROOT/'gate_runtime/requirements.lock').read_text().splitlines()
required={
'annotated-doc==0.0.4',
'annotated-types==0.7.0',
'anyio==4.13.0',
'certifi==2026.5.20',
'cffi==2.0.0',
'cryptography==46.0.4',
'fastapi==0.128.2',
'greenlet==3.5.1',
'h11==0.16.0',
'httpcore==1.0.9',
'httpx==0.28.1',
'idna==3.17',
'iniconfig==2.3.0',
'packaging==25.0',
'Pillow==12.3.0',
'pluggy==1.6.0',
'pycparser==3.0',
'pydantic==2.13.4',
'pydantic_core==2.46.4',
'pydantic-settings==2.14.1',
'Pygments==2.20.0',
'PyJWT==2.13.0',
'pytest==9.0.2',
'pytest-asyncio==1.3.0',
'python-dotenv==1.2.2',
'SQLAlchemy==2.0.50',
'starlette==0.50.0',
'typing_extensions==4.16.0',
'typing-inspection==0.4.2',
}
if set(lock)!=required or len(lock)!=29: block('LOCK_CLOSURE_MISMATCH')
wh=ROOT/'gate_runtime/wheelhouse'; sums=ROOT/'gate_runtime/WHEELHOUSE_SHA256SUMS.txt'
if not wh.is_dir() or not sums.is_file(): block('WHEELHOUSE_MISSING')
entries={}
for line in sums.read_text().splitlines():
    h,n=line.split('  ',1); entries[n]=h
wheels=sorted(p.name for p in wh.glob('*.whl'))
if set(entries)!=set(wheels) or len(wheels)!=29: block('WHEELHOUSE_SET_MISMATCH')
for n,h in entries.items():
    a=hashlib.sha256((wh/n).read_bytes()).hexdigest()
    if a!=h: block('WHEEL_SHA_MISMATCH:'+n)
# Exact one-to-one lock <-> wheel METADATA identity; no extra or missing distribution is allowed.
locked={}
for spec in lock:
    name,ver=spec.split('==',1); locked[name.lower().replace('_','-')]=ver
wheel_meta={}
for wp in wh.glob('*.whl'):
    with zipfile.ZipFile(wp) as z:
        metas=[x for x in z.namelist() if x.endswith('.dist-info/METADATA')]
        if len(metas)!=1: block('WHEEL_METADATA_INVALID:'+wp.name)
        msg=email.parser.Parser().parsestr(z.read(metas[0]).decode('utf-8'))
        name=(msg.get('Name') or '').lower().replace('_','-'); ver=msg.get('Version') or ''
        if not name or not ver: block('WHEEL_METADATA_IDENTITY_MISSING:'+wp.name)
        if name in wheel_meta: block('DUPLICATE_WHEEL_DISTRIBUTION:'+name)
        wheel_meta[name]=ver
if wheel_meta!=locked:
    block('LOCK_WHEEL_IDENTITY_MISMATCH locked='+repr(locked)+' wheels='+repr(wheel_meta))
# 3 release identity
for fn in ('CURRENT_RELEASE_MANIFEST.json','RELEASE_CANDIDATE_MANIFEST.json'):
 d=json.loads((ROOT/fn).read_text()); rel=d.get('release',{}); base=d.get('base_code_release',{})
 if rel.get('release_id')!='R3.1.7': block(fn+':R317_ID_MISSING')
 if rel.get('base_code_release_id')!='V6.1-R8.2-rc.20.3+20260825T162900+CST': block(fn+':BASE_ID_MISMATCH')
 if base.get('release_id')!='V6.1-R8.2-rc.20.3+20260825T162900+CST': block(fn+':BASE_HISTORY_MISMATCH')
 if rel.get('runtime_contract',{}).get('sha256')!=expected: block(fn+':RUNTIME_SHA_MISMATCH')
 tc=rel.get('toolchain_contract',{})
 if tc.get('node_version')!='v22.22.0': block(fn+':NODE_VERSION_MISMATCH')
 if tc.get('platform')!='linux-x64': block(fn+':NODE_PLATFORM_MISMATCH')
 if tc.get('target_glibc_max')!='2.35': block(fn+':NODE_GLIBC_CONTRACT_MISMATCH')
 if tc.get('artifact_name')!='node-v22.22.0-linux-x64.tar.xz': block(fn+':NODE_ARTIFACT_MISMATCH')
 if tc.get('upstream_sha256')!='9aa8e9d2298ab68c600bd6fb86a6c13bce11a4eca1ba9b39d79fa021755d7c37': block(fn+':NODE_SHA_MISMATCH')
print('runtime_sha_fixed=PASS')
print('lock_packages=29')
print('wheelhouse_wheels=29')
print('wheelhouse_byte_hashes=PASS')
print('release_identity=R3.1.7')
print('node_toolchain_contract=PASS')
print('base_code_release=V6.1-R8.2-rc.20.3+20260825T162900+CST')
print('R3.1.7_FINAL_SEAL_DEBT_CLOSURE: PASS')
