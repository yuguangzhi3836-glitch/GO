"""Persist one already-passed, immutable Actions artifact in its private repo."""
import base64
import hashlib
import io
import json
import os
from pathlib import PurePosixPath
import urllib.error
import urllib.request
import zipfile

REPO = 'yuguangzhi3836-glitch/GO'
RUN = 34306784341
COMMIT = 'a680d586248dd9106a19d25f7ff1b7140f77f3d5'
ARTIFACT = 10086993406
SHA = 'c7afd030cb34aa6d5d0b128d0adfa593f399da627b497d8b7dbd956e90cc46ad'
REF = 'refs/heads/evidence/cp11-depth25-runtime-34306784341'
API = 'https://api.github.com/repos/' + REPO


def request(path, data=None):
    req = urllib.request.Request(API + path, data=json.dumps(data).encode() if data is not None else None,
          headers={'Authorization': 'Bearer ' + os.environ['GITHUB_TOKEN'], 'Accept': 'application/vnd.github+json',
                   'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


run = request('/actions/runs/' + str(RUN))
assert run['conclusion'] == 'success' and run['head_sha'] == COMMIT
artifact = request('/actions/artifacts/' + str(ARTIFACT))
assert artifact['workflow_run']['id'] == RUN and artifact['digest'] == 'sha256:' + SHA


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Keep the repository token on api.github.com; the signed download needs no token.
req = urllib.request.Request(API + '/actions/artifacts/' + str(ARTIFACT) + '/zip',
      headers={'Authorization': 'Bearer ' + os.environ['GITHUB_TOKEN'], 'Accept': 'application/vnd.github+json'})
try:
    urllib.request.build_opener(NoRedirect()).open(req, timeout=60)
    raise AssertionError('Expected GitHub signed download redirect')
except urllib.error.HTTPError as e:
    assert e.code in (301, 302, 303, 307, 308)
    url = e.headers['Location']
assert url.startswith('https://')
data = urllib.request.urlopen(url, timeout=60).read()
assert hashlib.sha256(data).hexdigest() == SHA
payload = {'GO_DEPTH25_RUNTIME_ORIGINAL.zip': data}
with zipfile.ZipFile(io.BytesIO(data)) as z:
    assert z.testzip() is None
    for info in z.infolist():
        p = PurePosixPath(info.filename)
        assert not p.is_absolute() and '..' not in p.parts and '\\' not in info.filename
        assert info.file_size < 2000000
        if not info.is_dir():
            payload['original/' + str(p)] = z.read(info)
assert json.loads(payload['original/RUNTIME_GATE.json'])['runtime_acceptance'] == 'PASS'
entries = []
manifest = []
for name, blob in sorted(payload.items()):
    sha = request('/git/blobs', {'encoding': 'base64', 'content': base64.b64encode(blob).decode()})['sha']
    entries.append({'path': 'deliverables/CP11_DEPTH25_RUNTIME_ORIGINAL_20260909/' + name,
                    'mode': '100644', 'type': 'blob', 'sha': sha})
    manifest.append({'path': name, 'size': len(blob), 'sha256': hashlib.sha256(blob).hexdigest(), 'git_blob': sha})
entries.append({'path': 'deliverables/CP11_DEPTH25_RUNTIME_ORIGINAL_20260909/EXPORT_RECEIPT.json',
                'mode': '100644', 'type': 'blob', 'content': json.dumps({'run_id': RUN, 'source_commit': COMMIT,
                'artifact_id': ARTIFACT, 'artifact_sha256': SHA, 'files': manifest}, indent=2) + '\n'})
base = request('/git/commits/' + COMMIT)
tree = request('/git/trees', {'base_tree': base['tree']['sha'], 'tree': entries})['sha']
commit = request('/git/commits', {'message': 'Preserve original passing DEPTH25 Actions evidence and SHA256',
                 'tree': tree, 'parents': [COMMIT]})['sha']
request('/git/refs', {'ref': REF, 'sha': commit})
print(json.dumps({'commit': commit, 'ref': REF, 'artifact_sha256': SHA, 'exported_files': len(entries)}))
