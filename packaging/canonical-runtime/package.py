"""Build and independently restore the fixed canonical runtime; never deploy."""
import argparse
import hashlib
import json
import pathlib
import subprocess
import tarfile
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = 'c6ea4dd670db36e71f3839fb31e656a5c8806858'
TREE = '995d0d83faf883bec980c896fe8a17b0f12360fa'
DIGEST = '1c4d78c3c1bb5f448d0ebdb99d16a2d76419bbc663cc9ed8fae831e1d18c10c4'
FILES = 1332
IMAGE_EXCLUSIONS = {
    '.pytest_cache/.gitignore', '.pytest_cache/CACHEDIR.TAG',
    '.pytest_cache/README.md', '.pytest_cache/v/cache/nodeids',
}
TAG = 'go-hotel:canonical-995d0d83-20260914'
CONTRACT_BLOBS = {
    'README.md': '6ff3ba8863c40b991d748c2b6572402a776ff89d',
    'RUNTIME_ENV_CONTRACT.md': 'e14134d44c14328533108802354e7c887818376e',
    'docker-compose.business-runtime.yml': '32f947b5c48344aa75e6381408fb20cef173480a',
}


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def extract(archive, dest):
    with tarfile.open(archive) as tf:
        names = {}
        for m in tf.getmembers():
            p = pathlib.PurePosixPath(m.name)
            if p.is_absolute() or '..' in p.parts or not p.parts or p in names or not (m.isfile() or m.isdir()):
                raise ValueError('unsafe archive member: ' + m.name)
            names[p] = m.isfile()
        for p in names:
            if any(names.get(parent) for parent in p.parents):
                raise ValueError('file is archive parent: ' + str(p))
        tf.extractall(dest, filter='data')


def check_contract(source):
    folder = source / 'deploy/hk-staging'
    if {p.name for p in folder.iterdir()} != set(CONTRACT_BLOBS):
        raise ValueError('unexpected deployment contract paths')
    result = {}
    for name, expected in CONTRACT_BLOBS.items():
        data = (folder / name).read_bytes()
        actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if actual != expected:
            raise ValueError('deployment contract mismatch: ' + name)
        result[name] = hashlib.sha256(data).hexdigest()
    return result


def fingerprint(app):
    result = {}
    for p in sorted(app.rglob('*')):
        if p.is_symlink():
            raise ValueError('symlink in source')
        if p.is_file():
            result[p.relative_to(app).as_posix()] = sha(p)
    digest = hashlib.sha256(''.join(f'{p}\0{h}\n' for p, h in sorted(result.items())).encode()).hexdigest()
    if len(result) != FILES or digest != DIGEST:
        raise ValueError('source fingerprint mismatch')
    return result


def inspect(image):
    return json.loads(run('docker', 'image', 'inspect', image))[0]


def check_image(image, fp, out):
    # Verify all source bytes from the image, with no host source mount.
    if not IMAGE_EXCLUSIONS <= set(fp):
        raise ValueError('unexpected canonical cache set')
    runtime = {p: h for p, h in fp.items() if p not in IMAGE_EXCLUSIONS}
    code = 'import hashlib,json,pathlib; f,x=json.loads(input()); root=pathlib.Path("/app"); assert all(hashlib.sha256((root/p).read_bytes()).hexdigest()==h for p,h in f.items()); assert all(not (root/p).exists() for p in x); print(json.dumps({"image_source_files":len(f),"canonical_cache_exclusions":x,"status":"PASS"}))'
    result = run('docker', 'run', '--rm', '--network', 'none', '-i', '--entrypoint', 'python', image, '-c', code, input=json.dumps([runtime, sorted(IMAGE_EXCLUSIONS)]))
    (out / 'image-source.log').write_text(result + '\n')
    script = '''import importlib,json
from alembic.config import Config
from alembic.script import ScriptDirectory
heads=ScriptDirectory.from_config(Config('/app/alembic.ini')).get_heads()
assert heads==['0133_flight_change_plan'], heads
workers=['outbox','recovery','reconciliation','judgment','mobile_engagement','mobile_push','mobile_push_receipt']
for w in workers: importlib.import_module('go_hotel.workers.'+w+'_worker')
print(json.dumps({'migration_heads':heads,'worker_imports':workers,'status':'PASS_SCOPED'}))
'''
    (out / 'entrypoints.log').write_text(run('docker', 'run', '--rm', '--network', 'none', '-e', 'DATABASE_URL=sqlite:////tmp/probe.db', '--entrypoint', 'python', image, '-c', script) + '\n')
    (out / 'pip-freeze.txt').write_text(run('docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python', image, '-m', 'pip', 'freeze', '--all') + '\n')
    cmd = inspect(image)['Config']['Cmd']
    cid = run('docker', 'run', '-d', '--network', 'none', '-e', 'DATABASE_URL=sqlite:////tmp/probe.db', '-e', 'READINESS_REQUIRE_POSTGRES=false', '--entrypoint', 'sh', image, '-c', 'alembic upgrade head && exec "$@"', 'isolated-smoke', *cmd)
    try:
        health = ''
        for _ in range(45):
            p = subprocess.run(['docker', 'exec', cid, 'python', '-c', 'import urllib.request,json; d=json.load(urllib.request.urlopen("http://127.0.0.1:8000/health",timeout=2)); assert d.get("status")=="ok"; print(json.dumps(d))'], capture_output=True, text=True)
            if p.returncode == 0:
                health = p.stdout
                break
            time.sleep(1)
        if not health:
            raise RuntimeError('isolated image health failed')
        (out / 'health.json').write_text(health)
        (out / 'openapi.log').write_text(run('docker', 'exec', cid, 'python', '-c', 'import urllib.request,json; d=json.load(urllib.request.urlopen("http://127.0.0.1:8000/openapi.json",timeout=20)); assert len(d["paths"])>900; print(json.dumps({"openapi_paths":len(d["paths"]),"status":"PASS_SCOPED"}))') + '\n')
    finally:
        p = subprocess.run(['docker', 'logs', cid], capture_output=True, text=True)
        (out / 'container.log').write_text(p.stdout + p.stderr)
        subprocess.run(['docker', 'rm', '-f', cid], check=True)


def build(out):
    out.mkdir(parents=True, exist_ok=False)
    if run('git', 'rev-parse', SOURCE + ':application', cwd=ROOT) != TREE:
        raise ValueError('canonical Git tree mismatch')
    if run('git', 'rev-parse', 'HEAD:application', cwd=ROOT) != TREE:
        raise ValueError('builder changes application')
    bundle = out / 'bundle'
    bundle.mkdir()
    with tempfile.TemporaryDirectory() as d:
        work = pathlib.Path(d)
        archive = bundle / 'source.tar.gz'
        subprocess.run(['git', 'archive', '--format=tar.gz', '--output=' + str(archive), SOURCE, 'application', 'deploy/hk-staging'], cwd=ROOT, check=True)
        extract(archive, work)
        fp = fingerprint(work / 'application')
        write(bundle / 'DEPLOYMENT_CONTRACT_SHA256.json', check_contract(work))
        write(bundle / 'SOURCE_FINGERPRINT.json', fp)
        # Resolve the canonical floating base once; retain its actual identity.
        subprocess.run(['docker', 'pull', '--platform', 'linux/amd64', 'python:3.12-slim'], check=True)
        write(bundle / 'BASE_IMAGE_INSPECT.json', inspect('python:3.12-slim'))
        subprocess.run(['docker', 'build', '--platform', 'linux/amd64', '--pull=false', '-t', TAG, str(work / 'application')], check=True)
        info = inspect(TAG)
        if info['Architecture'] != 'amd64' or info['Os'] != 'linux':
            raise ValueError('wrong runtime architecture')
        check_image(info['Id'], fp, bundle)
        subprocess.run(['docker', 'save', '-o', str(bundle / 'image.tar'), TAG], check=True)
        with tarfile.open(bundle / 'image.tar') as tf:
            archive_files = {}
            for m in tf.getmembers():
                if m.isfile():
                    h = hashlib.sha256()
                    stream = tf.extractfile(m)
                    for part in iter(lambda: stream.read(1024 * 1024), b''):
                        h.update(part)
                    archive_files[m.name] = {'bytes': m.size, 'sha256': h.hexdigest()}
            if info['Id'].split(':', 1)[1] not in {v['sha256'] for v in archive_files.values()}:
                raise ValueError('image archive lacks expected config bytes')
            write(bundle / 'IMAGE_ARCHIVE_MANIFEST.json', archive_files)
        subprocess.run(['gzip', '-n', str(bundle / 'image.tar')], check=True)
        write(bundle / 'IMAGE_INSPECT.json', info)
        write(bundle / 'CANDIDATE.json', {'source_commit': SOURCE, 'builder_commit': run('git', 'rev-parse', 'HEAD', cwd=ROOT), 'application_git_tree': TREE, 'source_tree_sha256': DIGEST, 'source_files': FILES, 'image_id': info['Id'], 'repo_digests': info.get('RepoDigests', []), 'image_tag': TAG, 'topology_id': 'HK_STAGING_BUSINESS_TOPOLOGY', 'topology_version': 1, 'runtime_package_build': 'PASS_SCOPED', 'sealed_node': 'HOLD', 'full_release': 'HOLD', 'deployment': 'NOT_RUN', 'production': 'HOLD', 'limits': ['worker imports are not worker liveness', 'health is not a full business journey', 'SQLite smoke is not PostgreSQL acceptance', 'floating upstream build dependencies recorded, not frozen', 'no registry digest is invented']})
        write(bundle / 'SHA256.json', {p.name: sha(p) for p in sorted(bundle.iterdir()) if p.is_file()})
    with tarfile.open(out / 'runtime-package.tar.gz', 'w:gz') as tf:
        tf.add(bundle, arcname='bundle')
    (out / 'runtime-package.sha256').write_text(sha(out / 'runtime-package.tar.gz') + '  runtime-package.tar.gz\n')
    print((bundle / 'CANDIDATE.json').read_text(), flush=True)
    print((out / 'runtime-package.sha256').read_text(), flush=True)


def restore(out):
    expected = (out / 'runtime-package.sha256').read_text().split()[0]
    if sha(out / 'runtime-package.tar.gz') != expected:
        raise ValueError('package checksum mismatch')
    with tempfile.TemporaryDirectory() as d:
        dest = pathlib.Path(d)
        extract(out / 'runtime-package.tar.gz', dest)
        b = dest / 'bundle'
        hashes = json.loads((b / 'SHA256.json').read_text())
        if set(hashes) != {p.name for p in b.iterdir()} - {'SHA256.json'}:
            raise ValueError('unexpected bundle files')
        for name, digest in hashes.items():
            if sha(b / name) != digest:
                raise ValueError('bundle checksum mismatch: ' + name)
        meta = json.loads((b / 'CANDIDATE.json').read_text())
        if (meta['source_commit'], meta['application_git_tree'], meta['source_tree_sha256']) != (SOURCE, TREE, DIGEST):
            raise ValueError('candidate source mismatch')
        source = dest / 'source'
        source.mkdir()
        extract(b / 'source.tar.gz', source)
        fp = fingerprint(source / 'application')
        if check_contract(source) != json.loads((b / 'DEPLOYMENT_CONTRACT_SHA256.json').read_text()):
            raise ValueError('deployment contract fingerprint mismatch')
        if fp != json.loads((b / 'SOURCE_FINGERPRINT.json').read_text()):
            raise ValueError('fingerprint mismatch')
        subprocess.run(['docker', 'load', '-i', str(b / 'image.tar.gz')], check=True)
        if inspect(TAG)['Id'] != meta['image_id']:
            raise ValueError('loaded image mismatch')
        logs = out / 'restore-evidence'
        logs.mkdir()
        check_image(meta['image_id'], fp, logs)
        receipt = {'package_sha256': expected, 'image_id': meta['image_id'], 'application_git_tree': TREE, 'source_tree_sha256': DIGEST, 'offline_image_restore': 'PASS_SCOPED', 'image_execution_network': 'none', 'sealed_node': 'HOLD', 'full_release': 'HOLD', 'deployment': 'NOT_RUN', 'production': 'HOLD'}
        write(logs / 'RESTORE.json', receipt)
        print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['build', 'restore'])
    p.add_argument('output', type=pathlib.Path)
    args = p.parse_args()
    (build if args.mode == 'build' else restore)(args.output.resolve())
