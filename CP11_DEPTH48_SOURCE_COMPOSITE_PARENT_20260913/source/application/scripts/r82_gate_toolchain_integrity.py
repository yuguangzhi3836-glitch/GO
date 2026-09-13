#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,subprocess,sys,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def block(msg): print('R8.2_GATE_TOOLCHAIN: BLOCK'); print(msg); raise SystemExit(1)
try:
 src=json.loads((ROOT/'gate_toolchain/NODE_SOURCE.json').read_text())
 man=json.loads((ROOT/'gate_toolchain/NODE_MANIFEST.json').read_text())
except Exception as e: block('NODE_MANIFEST_INVALID:'+repr(e))
node=ROOT/'gate_toolchain/node/bin/node'
if not node.is_file(): block('SEALED_NODE_MISSING')
resolved=shutil.which('node')
if resolved is not None and Path(resolved).resolve()!=node.resolve():
    block('HOST_NODE_PRECEDENCE_DETECTED:'+resolved)
if src.get('version')!='v22.22.0' or man.get('node_version')!='v22.22.0': block('NODE_VERSION_CONTRACT_MISMATCH')
if src.get('platform')!='linux-x64' or man.get('platform')!='linux-x64': block('NODE_PLATFORM_CONTRACT_MISMATCH')
if src.get('target_glibc_max')!='2.35' or man.get('target_glibc_max')!='2.35': block('NODE_GLIBC_CONTRACT_MISMATCH')
if src.get('expected_sha256')!=man.get('upstream_sha256'): block('NODE_UPSTREAM_SHA_CONTRACT_MISMATCH')
try: ver=subprocess.check_output([str(node),'--version'],text=True).strip()
except Exception as e: block('SEALED_NODE_CANNOT_START:'+repr(e))
if ver!='v22.22.0': block('SEALED_NODE_VERSION_MISMATCH:'+ver)
h=hashlib.sha256(); root=ROOT/'gate_toolchain/node'
for p in sorted(x for x in root.rglob('*') if x.is_file()):
 rel=p.relative_to(root).as_posix().encode(); h.update(rel+b'\0'); h.update(hashlib.sha256(p.read_bytes()).digest())
actual=h.hexdigest()
if actual!=man.get('node_tree_sha256'): block('NODE_TREE_SHA_MISMATCH')
# Re-scan Node binary GLIBC requirements. The provisioner already scanned all .so files too.
try:
 out=subprocess.check_output(['readelf','--version-info',str(node)],stderr=subprocess.DEVNULL,text=True)
except Exception as e: block('READELF_NODE_FAILED:'+repr(e))
import re
vers=[tuple(map(int,m.split('.'))) for m in re.findall(r'GLIBC_([0-9]+\.[0-9]+)',out)]
maxv=max(vers,default=(0,0))
if maxv>(2,35): block('NODE_GLIBC_EXCEEDS_2_35:'+('.'.join(map(str,maxv))))
print('R8.2_GATE_TOOLCHAIN: PASS')
print('node_version='+ver)
print('node_tree_sha256='+actual)
print('node_max_required_glibc='+'.'.join(map(str,maxv)))
