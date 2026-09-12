"""Persist verified parent bytes as immutable Git objects. Never create or move any ref."""
import base64
import hashlib
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from verify_parent import require, sha

REPO = 'yuguangzhi3836-glitch/GO'
NAME = 'CP11_DEPTH41_UNIFIED_PARENT_V1_20260912'
PREFIX = 'deliverables/' + NAME


def api(path, body=None):
    request = Request('https://api.github.com/repos/' + REPO + '/' + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Authorization': 'Bearer ' + os.environ['GO_ARCHIVE_TOKEN'],
                 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json'})
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def main():
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('GITHUB_REPOSITORY') == REPO, 'GO_CI_ONLY')
    source = os.environ['GO_SOURCE_SHA']
    pr = api('pulls/47')
    require(pr['head']['sha'] == source and pr['head']['ref'] == 'fix/canonical-parent-retention-20260912'
            and pr['head']['repo']['full_name'] == REPO and pr['draft'] is True and pr['state'] == 'open', 'PR47_MOVED')
    delivery = Path('parent-delivery')
    report = json.loads((delivery / 'PARENT_BUILD_REPORT.json').read_text())
    manifest = json.loads((delivery / 'PARENT_MANIFEST.json').read_text())
    require(report['source_commit'] == manifest['source_commit'] == source, 'SOURCE_COMMIT')
    require(report['package_integrity'] == report['zip_restore'] == 'PASS', 'PACKAGE_NOT_VERIFIED')
    require(manifest['application_git_tree'] == 'a73b9b53a59c88ab995d0f9b123c9fb79e87e60d' and manifest['deployment_authorized'] is False, 'CANDIDATE_BINDING')
    archive = delivery / (NAME + '.zip')
    require(sha(archive) == report['zip_sha256'] and archive.stat().st_size == report['zip_bytes'], 'ZIP_MISMATCH')
    elements = []

    def blob(name, data):
        expected = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        result = api('git/blobs', {'content': base64.b64encode(data).decode(), 'encoding': 'base64'})
        require(result['sha'] == expected, 'GIT_BLOB_WRITE')
        stored = api('git/blobs/' + expected)
        require(stored['encoding'] == 'base64', 'GIT_BLOB_ENCODING')
        require(base64.b64decode(stored['content']) == data, 'GIT_BLOB_READBACK')
        elements.append({'path': PREFIX + '/' + name, 'mode': '100644', 'type': 'blob', 'sha': expected})
        return expected

    parts = []
    digest = hashlib.sha256()
    with archive.open('rb') as stream:
        while chunk := stream.read(20 * 1024 * 1024):
            name = archive.name + f'.part{len(parts):03d}'
            git_blob = blob(name, chunk)
            digest.update(chunk)
            parts.append({'name': name, 'bytes': len(chunk), 'sha256': hashlib.sha256(chunk).hexdigest(), 'git_blob': git_blob})
    require(digest.hexdigest() == report['zip_sha256'], 'ARCHIVE_STREAM_HASH')
    part_index = {'zip_file': archive.name, 'zip_bytes': archive.stat().st_size, 'zip_sha256': report['zip_sha256'],
                  'source_commit': source, 'parts': parts}
    blob('PARENT_PARTS.json', (json.dumps(part_index, indent=2) + '\n').encode())
    for path in sorted(delivery.iterdir()):
        if path.is_file() and path != archive:
            blob(path.name, path.read_bytes())
    for name in ('reconstruct_parent.py', 'README.md'):
        blob(name, (Path(__file__).parent / name).read_bytes())
    receipt = {'archive_readback': 'PASS', 'source_commit': source, 'zip_sha256': report['zip_sha256'],
               'zip_bytes': archive.stat().st_size, 'parts': len(parts), 'each_git_blob_read_back': True,
               'git_ref_modified': False, 'main_modified': False, 'deployment': 'NOT_RUN',
               'build_run_id': os.environ['GITHUB_RUN_ID']}
    blob('ARCHIVE_RECEIPT.json', (json.dumps(receipt, indent=2) + '\n').encode())
    base = api('git/commits/' + source)['tree']['sha']
    tree = api('git/trees', {'base_tree': base, 'tree': elements})
    result = {**receipt, 'base_tree': base, 'archive_tree': tree['sha'], 'path': PREFIX, 'entries': elements}
    Path('ARCHIVE_OBJECTS.json').write_text(json.dumps(result, indent=2) + '\n')
    print('ARCHIVE_OBJECTS=' + json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
