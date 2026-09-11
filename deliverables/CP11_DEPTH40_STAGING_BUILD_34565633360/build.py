"""Build a dependency-complete context, with immutable source and separate tooling."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ap = argparse.ArgumentParser()
for name in ('source', 'fingerprint', 'wheelhouse', 'lock', 'output'):
    ap.add_argument('--'+name, required=True, type=Path)
a = ap.parse_args()
here = Path(__file__).resolve().parent
base = here.parent/'depth40-runtime'
subprocess.run([sys.executable, '-B', str(base/'build_rootfs.py'), '--source', str(a.source),
    '--fingerprint', str(a.fingerprint), '--wheelhouse', str(a.wheelhouse), '--lock', str(a.lock),
    '--tooling', str(base), '--output', str(a.output)], check=True)
root = a.output/'rootfs'
shutil.rmtree(root/'opt/go/tooling')
(root/'opt/go/staging').mkdir()
for name in ('launch.py', 'preflight.py'):
    shutil.copy2(here/name, root/'opt/go/staging'/name)
(root/'etc/ssl/certs').mkdir(parents=True)
shutil.copy2('/etc/ssl/certs/ca-certificates.crt', root/'etc/ssl/certs/ca-certificates.crt')
shutil.copy2(here/'Dockerfile', a.output/'Dockerfile')
binding = json.loads((a.output/'ROOTFS_BINDING.json').read_text())
binding.update(runtime_scope='STAGING_EIGHT_SERVICE_POSTGRES_REVIEW',
    source_modified=False, required_database_head='0132_rail_runtime_field_widths',
    migration_authorized=False, hk_execution='NOT_RUN',
    rootfs_bytes=sum(p.stat().st_size for p in root.rglob('*') if p.is_file()))
(a.output/'ROOTFS_BINDING.json').write_text(json.dumps(binding, indent=2)+'\n')
# Complete build input ledger, including interpreter, wheels and system ELF bytes.
ledger={p.relative_to(root).as_posix():
        ({'symlink':str(p.readlink())} if p.is_symlink() else
         {'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'size':p.stat().st_size})
        for p in root.rglob('*') if p.is_symlink() or p.is_file()}
(a.output/'ROOTFS_FILES.json').write_text(json.dumps(ledger,sort_keys=True)+'\n')
print(json.dumps(binding))
