"""Fixed-source Node toolchain overlay, never application deployment."""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tarfile
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = 'c6ea4dd670db36e71f3839fb31e656a5c8806858'
TREE = '995d0d83faf883bec980c896fe8a17b0f12360fa'
DIGEST = '1c4d78c3c1bb5f448d0ebdb99d16a2d76419bbc663cc9ed8fae831e1d18c10c4'


def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def write(p, data):
    p.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def extract(archive, dest):
    """Allow relative links to regular members, never links as parents."""
    if dest.exists() and any(dest.iterdir()):
        raise ValueError('extraction requires empty destination')
    with tarfile.open(archive) as tf:
        members = {}
        for m in tf.getmembers():
            p = pathlib.PurePosixPath(m.name)
            if p.is_absolute() or not p.parts or '..' in p.parts or p in members:
                raise ValueError('unsafe or duplicate archive path')
            if not (m.isfile() or m.isdir() or m.issym()):
                raise ValueError('unsupported archive member')
            members[p] = m
        for p, m in members.items():
            if any(a in members and not members[a].isdir() for a in p.parents):
                raise ValueError('non-directory archive parent')
            if m.issym():
                link = pathlib.PurePosixPath(m.linkname)
                if link.is_absolute() or not link.parts:
                    raise ValueError('unsafe link')
                parts = list(p.parent.parts)
                for part in link.parts:
                    if part == '..':
                        if not parts:
                            raise ValueError('escaping link')
                        parts.pop()
                    else:
                        parts.append(part)
                target = pathlib.PurePosixPath(*parts)
                if target not in members or not members[target].isfile():
                    raise ValueError('link must target archived regular file')
                if any(a in members and not members[a].isdir() for a in target.parents):
                    raise ValueError('link target has non-directory parent')
        tf.extractall(dest, filter='data')


def inventory(root):
    rows = {}
    for p in sorted(root.rglob('*')):
        rel = p.relative_to(root).as_posix()
        if p.is_symlink():
            rows[rel] = {'link': os.readlink(p)}
        elif p.is_file():
            rows[rel] = {'sha256': sha(p), 'mode': p.stat().st_mode & 0o777}
    return rows


def fingerprint(app):
    rows = inventory(app)
    if any('link' in x for x in rows.values()):
        raise ValueError('unexpected source link')
    fp = {p: v['sha256'] for p, v in rows.items()}
    digest = hashlib.sha256(''.join(f'{p}\0{h}\n' for p, h in sorted(fp.items())).encode()).hexdigest()
    if len(fp) != 1332 or digest != DIGEST:
        raise ValueError('source mismatch')
    return fp


def logged(args, path, **kwargs):
    with path.open('w') as out:
        result = subprocess.run(args, stdout=out, stderr=subprocess.STDOUT, **kwargs)
    print(path.read_text(), flush=True)
    result.check_returncode()


def gate(app, path):
    env = dict(os.environ, PATH=str(app / 'gate_toolchain/node/bin') + ':/usr/bin:/bin', PYTHONDONTWRITEBYTECODE='1')
    logged(['/usr/bin/python3', str(app / 'scripts/r82_gate_toolchain_integrity.py')], path, env=env)


def unchanged(app, fp):
    if any(sha(app / p) != h for p, h in fp.items()):
        raise ValueError('provision changed canonical source')


def verify_upstream(bundle, source):
    spec = json.loads((source / 'gate_toolchain/NODE_SOURCE.json').read_text())
    if sha(bundle / spec['artifact_name']) != spec['expected_sha256']:
        raise ValueError('official archive mismatch')
    return spec


def compare_official_overlay(bundle, spec):
    with tempfile.TemporaryDirectory() as d:
        root = pathlib.Path(d)
        extract(bundle / spec['artifact_name'], root)
        official = root / 'node-v22.22.0-linux-x64'
        if inventory(official) != inventory(bundle / 'overlay/gate_toolchain/node'):
            raise ValueError('overlay differs from pinned official archive')


def build(out):
    out.mkdir(parents=True, exist_ok=False)
    for ref in [SOURCE, 'HEAD']:
        actual = subprocess.check_output(['git', 'rev-parse', ref + ':application'], cwd=ROOT, text=True).strip()
        if actual != TREE:
            raise ValueError('Git source tree mismatch')
    bundle = out / 'bundle'
    bundle.mkdir()
    subprocess.run(['git', 'archive', '--format=tar.gz', '--output=' + str(bundle / 'source.tar.gz'), SOURCE, 'application'], cwd=ROOT, check=True)
    with tempfile.TemporaryDirectory() as d:
        work = pathlib.Path(d)
        extract(bundle / 'source.tar.gz', work / 'source')
        app = work / 'source/application'
        fp = fingerprint(app)
        write(bundle / 'SOURCE_FINGERPRINT.json', fp)
        env = dict(os.environ, R317_NODE_WORKDIR=str(work / 'provision'), PYTHONDONTWRITEBYTECODE='1')
        logged(['sh', str(app / 'scripts/r317_provision_node_toolchain.sh')], bundle / 'provision.log', env=env)
        unchanged(app, fp)
        gate(app, bundle / 'gate.log')
        spec = json.loads((app / 'gate_toolchain/NODE_SOURCE.json').read_text())
        shutil.copyfile(work / 'provision/download' / spec['artifact_name'], bundle / spec['artifact_name'])
        verify_upstream(bundle, app)
        overlay = bundle / 'overlay/gate_toolchain'
        overlay.mkdir(parents=True)
        shutil.copytree(app / 'gate_toolchain/node', overlay / 'node', symlinks=True)
        shutil.copyfile(app / 'gate_toolchain/NODE_MANIFEST.json', overlay / 'NODE_MANIFEST.json')
        compare_official_overlay(bundle, spec)
        write(bundle / 'OVERLAY_INVENTORY.json', inventory(bundle / 'overlay'))
        manifest = json.loads((overlay / 'NODE_MANIFEST.json').read_text())
        write(bundle / 'CANDIDATE.json', {'source_commit': SOURCE, 'application_git_tree': TREE, 'source_tree_sha256': DIGEST, 'source_files': 1332, 'builder_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(), 'node_version': manifest['node_version'], 'node_tree_sha256': manifest['node_tree_sha256'], 'node_toolchain_gate': 'PASS_SCOPED', 'artifact_role': 'SEPARATE_NODE_OVERLAY', 'full_release': 'HOLD', 'deployment': 'NOT_RUN', 'production': 'HOLD'})
    write(bundle / 'INVENTORY.json', inventory(bundle))
    with tarfile.open(out / 'node-seal.tar.gz', 'w:gz', dereference=False) as tf:
        tf.add(bundle, arcname='bundle')
    (out / 'node-seal.sha256').write_text(sha(out / 'node-seal.tar.gz') + '  node-seal.tar.gz\n')
    print((bundle / 'CANDIDATE.json').read_text(), flush=True)
    print((out / 'node-seal.sha256').read_text(), flush=True)


def restore(out):
    expected = (out / 'node-seal.sha256').read_text().split()[0]
    if sha(out / 'node-seal.tar.gz') != expected:
        raise ValueError('package checksum mismatch')
    logs = out / 'restore-evidence'
    logs.mkdir()
    with tempfile.TemporaryDirectory() as d:
        work = pathlib.Path(d)
        extract(out / 'node-seal.tar.gz', work / 'package')
        b = work / 'package/bundle'
        actual = inventory(b)
        actual.pop('INVENTORY.json')
        if actual != json.loads((b / 'INVENTORY.json').read_text()):
            raise ValueError('bundle inventory mismatch')
        meta = json.loads((b / 'CANDIDATE.json').read_text())
        if (meta['source_commit'], meta['application_git_tree'], meta['source_tree_sha256']) != (SOURCE, TREE, DIGEST):
            raise ValueError('candidate source mismatch')
        extract(b / 'source.tar.gz', work / 'source')
        app = work / 'source/application'
        fp = fingerprint(app)
        if fp != json.loads((b / 'SOURCE_FINGERPRINT.json').read_text()):
            raise ValueError('fingerprint mismatch')
        spec = verify_upstream(b, app)
        compare_official_overlay(b, spec)
        if inventory(b / 'overlay') != json.loads((b / 'OVERLAY_INVENTORY.json').read_text()):
            raise ValueError('overlay mismatch')
        toolchain = b / 'overlay/gate_toolchain'
        if set(p.name for p in toolchain.iterdir()) != {'node', 'NODE_MANIFEST.json'}:
            raise ValueError('unexpected overlay members')
        shutil.copytree(toolchain / 'node', app / 'gate_toolchain/node', symlinks=True)
        shutil.copyfile(toolchain / 'NODE_MANIFEST.json', app / 'gate_toolchain/NODE_MANIFEST.json')
        unchanged(app, fp)
        gate(app, logs / 'gate.log')
        manifest = json.loads((toolchain / 'NODE_MANIFEST.json').read_text())
        if manifest['node_tree_sha256'] != meta['node_tree_sha256'] or manifest['node_version'] != meta['node_version']:
            raise ValueError('candidate node identity mismatch')
        receipt = {'package_sha256': expected, 'source_commit': SOURCE, 'application_git_tree': TREE, 'source_tree_sha256': DIGEST, 'node_tree_sha256': manifest['node_tree_sha256'], 'node_version': manifest['node_version'], 'upstream_sha256': spec['expected_sha256'], 'node_toolchain_restore': 'PASS_SCOPED', 'download_or_provision_on_restore': False, 'full_release': 'HOLD', 'deployment': 'NOT_RUN', 'production': 'HOLD'}
        write(logs / 'RESTORE.json', receipt)
        print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['build', 'restore'])
    p.add_argument('output', type=pathlib.Path)
    a = p.parse_args()
    (build if a.mode == 'build' else restore)(a.output.resolve())
