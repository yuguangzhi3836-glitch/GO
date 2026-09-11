"""Package verified source + frozen wheels + CI Python and ELF dependencies.

FROM scratch: no mutable Docker base image and no package installation on HK.
This prepares a new build context; it never deploys or modifies candidate files.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

TREE = '64f5d78a17b2fa2194b18f9bc1ba0cafbf0f2547f0171a859dd4300c75e37667'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    for name in ('source', 'fingerprint', 'wheelhouse', 'lock', 'tooling', 'output'):
        ap.add_argument('--' + name, required=True, type=Path)
    a = ap.parse_args()
    assert sys.version_info[:3] == (3, 13, 5), 'PINNED_PYTHON_REQUIRED'
    assert not a.output.exists(), 'NEW_BUILD_DIRECTORY_REQUIRED'
    fp = json.loads(a.fingerprint.read_text())
    actual = {p.relative_to(a.source).as_posix(): sha(p) for p in a.source.rglob('*') if p.is_file()}
    assert actual == fp and len(fp) == 1271
    assert not any(p.is_symlink() for p in a.source.rglob('*'))
    assert hashlib.sha256(''.join(f'{k}\0{v}\n' for k, v in sorted(fp.items())).encode()).hexdigest() == TREE
    root = a.output.resolve() / 'rootfs'; go = root / 'opt/go'
    go.mkdir(parents=True)
    shutil.copytree(a.source, go / 'source')
    shutil.copy2(a.fingerprint, go / 'SOURCE_FINGERPRINT.json')
    shutil.copytree(Path(sys.base_prefix), go / 'python', symlinks=True)
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-index', '--no-deps', '--no-compile',
                    '--find-links', str(a.wheelhouse), '--target', str(go / 'site'), '-r', str(a.lock)], check=True)
    (go / 'tooling').mkdir()
    for name in ('serve.py', 'probe.py'):
        shutil.copy2(a.tooling / name, go / 'tooling' / name)
    # Copy the transitive runtime ELF closure, preserving each loader lookup path.
    libs = {}
    bundled_lib_dirs = [str(p) for p in (go / 'site').rglob('*')
                        if p.is_dir() and p.name.endswith('.libs')]
    loader_path = ':'.join([str(go / 'python/lib'), *bundled_lib_dirs])
    for p in list((go / 'python').rglob('*')) + list((go / 'site').rglob('*')):
        if not p.is_file(): continue
        with p.open('rb') as stream:
            if stream.read(4) != b'\x7fELF': continue
        result = subprocess.run(['ldd', str(p)], text=True, capture_output=True,
                                env={**os.environ, 'LD_LIBRARY_PATH': loader_path})
        if 'not found' in result.stdout:
            raise RuntimeError('MISSING_ELF_DEPENDENCY:' + str(p) + ':' + result.stdout)
        for path in re.findall(r'(?:=>\s+)?(/[^\s]+)', result.stdout):
            lib = Path(path)
            if go in lib.parents or str(lib).startswith(str(go)): continue
            destination = root / str(lib).lstrip('/')
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(lib.resolve(), destination)
            libs[str(lib)] = sha(destination)
    (root / 'etc').mkdir(exist_ok=True)
    (root / 'etc/passwd').write_text('go:x:10001:10001:GO:/state:/nonexistent\n')
    (root / 'etc/group').write_text('go:x:10001:\n')
    (root / 'tmp').mkdir(mode=0o1777)
    (a.output / 'empty-state').mkdir()
    (a.output / 'empty-state/.keep').write_text('No runtime state or credentials are included.\n')
    shutil.copy2(a.tooling / 'Dockerfile', a.output / 'Dockerfile')
    binding = {'source_tree_sha256': TREE, 'verified_source_files': 1271,
               'python': sys.version, 'python_provenance': 'actions/setup-python 3.13.5 on ubuntu-22.04',
               'system_elf_libraries': libs, 'rootfs_bytes': sum(p.stat().st_size for p in root.rglob('*') if p.is_file()),
               'runtime_scope': 'ISOLATED_SQLITE_HTTP', 'deployment_authorized': False}
    (a.output / 'ROOTFS_BINDING.json').write_text(json.dumps(binding, indent=2) + '\n')
    print(json.dumps({'source_tree_sha256': TREE, 'libraries': len(libs), 'rootfs_bytes': binding['rootfs_bytes']}))


if __name__ == '__main__':
    main()
