"""Persist a single user-selected immutable GO artifact to one new archive branch.
No branch updates, merges, environment changes, builds or application tests.
"""
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile

REPO = 'yuguangzhi3836-glitch/GO'
API = 'https://api.github.com/repos/' + REPO
ARTIFACT = 10281491262
RUN = 34644569516
SOURCE = '4c9d24ee37cef02cfef026c41db3dfb38d09b9f0'
WRAPPER_SHA = '3a727c72cfe7d0894936bb066a71abf522a14a6a05943c8f4dc62b4f45cbcfe8'
ZIP_NAME = 'CP11_DEPTH40_P03_COMPAT_V2_PARENT_20260912.zip'
ZIP_SHA = '421b11f95d0400bdfc69d4053a6d3b54599fa791a0d6b43311b83094bcd51c6a'
ZIP_BYTES = 187168614
BRANCH = 'archive/depth40-p03-compat-v2-parent-34644569516'
DEST = 'deliverables/CP11_DEPTH40_P03_COMPAT_V2_PARENT_20260912'
EVIDENCE = 'evidence/depth40-parent-compat-v2/34644569516'
ROOT = Path(__file__).resolve().parent


def check(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def git_blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def headers():
    return {'Authorization': 'Bearer ' + os.environ['GITHUB_TOKEN'],
            'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json'}


def api(path, payload=None, missing=False):
    check(path.startswith('/') and not path.startswith('//') and '..' not in path, 'API_PATH')
    if payload is not None:
        check(path in ('/git/blobs', '/git/trees', '/git/commits', '/git/refs'), 'WRITE_ENDPOINT_NOT_ALLOWED')
        if path == '/git/refs':
            check(payload['ref'] == 'refs/heads/' + BRANCH, 'ARCHIVE_REF_ONLY')
    request = urllib.request.Request(API + path, headers=headers(),
        data=None if payload is None else json.dumps(payload).encode(),
        method='GET' if payload is None else 'POST')
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if missing and exc.code == 404:
            return None
        raise RuntimeError('GITHUB_API_' + str(exc.code) + ':' + path) from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def download(path):
    request = urllib.request.Request(API + '/actions/artifacts/' + str(ARTIFACT) + '/zip', headers=headers())
    try:
        response = urllib.request.build_opener(NoRedirect).open(request, timeout=60)
    except urllib.error.HTTPError as exc:
        check(exc.code in (301, 302, 303, 307, 308), 'ARTIFACT_DOWNLOAD_FAILED')
        location = exc.headers['Location']
        check(location.startswith('https://'), 'ARTIFACT_REDIRECT_SCHEME')
        # Deliberately no Authorization header on the signed storage redirect.
        response = urllib.request.urlopen(location, timeout=120)
    with response, path.open('wb') as target:
        shutil.copyfileobj(response, target)
    check(sha(path) == WRAPPER_SHA, 'ARTIFACT_WRAPPER_HASH')


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def publish_blob(path):
    data = path.read_bytes()
    digest = git_blob(data)
    created = api('/git/blobs', {'content': base64.b64encode(data).decode(), 'encoding': 'base64'})
    check(created['sha'] == digest, 'GIT_BLOB_WRITE_MISMATCH')
    return digest


def retrieve_blob(blob_sha, path):
    blob = api('/git/blobs/' + blob_sha)
    check(blob['encoding'] == 'base64' and blob['sha'] == blob_sha, 'GIT_BLOB_READ_METADATA')
    data = base64.b64decode(blob['content'])
    check(git_blob(data) == blob_sha and len(data) == blob['size'], 'GIT_BLOB_READ_HASH')
    path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)


def main():
    check(os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('GITHUB_REPOSITORY') == REPO,
          'ONLY_GO_ISOLATED_ARCHIVE_JOB')
    check(api('/git/ref/heads/' + BRANCH, missing=True) is None, 'ARCHIVE_BRANCH_ALREADY_EXISTS_NO_OVERWRITE')
    run = api('/actions/runs/' + str(RUN))
    check(run['conclusion'] == 'success' and run['head_sha'] == SOURCE, 'SOURCE_CI_NOT_VERIFIED')
    artifact = api('/actions/artifacts/' + str(ARTIFACT))
    check(not artifact['expired'] and artifact['digest'] == 'sha256:' + WRAPPER_SHA
          and artifact['workflow_run']['id'] == RUN and artifact['workflow_run']['head_sha'] == SOURCE,
          'SOURCE_ARTIFACT_IDENTITY')
    work = Path('archive-work'); work.mkdir()
    wrapper = work / 'artifact.zip'; download(wrapper)
    folder = work / 'parent'; folder.mkdir()
    expected = {ZIP_NAME, ZIP_NAME + '.sha256', 'PARENT_BUILD_REPORT.json', 'PARENT_MANIFEST.json',
                'VERIFY_RESULT.json', 'verify_parent.py'}
    with zipfile.ZipFile(wrapper) as archive:
        check(set(archive.namelist()) == expected and len(archive.infolist()) == len(expected), 'WRAPPER_FILE_SET')
        for name in sorted(expected):
            with archive.open(name) as source, (folder / name).open('wb') as target:
                shutil.copyfileobj(source, target)
    parent = folder / ZIP_NAME
    check(parent.stat().st_size == ZIP_BYTES and sha(parent) == ZIP_SHA, 'PARENT_ZIP_IDENTITY')
    result = json.loads((folder / 'PARENT_BUILD_REPORT.json').read_text())
    check(result['zip_sha256'] == ZIP_SHA and result['packaging_commit'] == SOURCE
          and result['zip_restore'] == 'PASS', 'PARENT_REPORT_IDENTITY')
    parts = []
    with parent.open('rb') as source:
        index = 0
        while chunk := source.read(20 * 1024 * 1024):
            name = ZIP_NAME + f'.part{index:03d}'
            part = folder / name; part.write_bytes(chunk)
            parts.append({'name': name, 'bytes': len(chunk), 'sha256': sha(part)})
            index += 1
    check(len(parts) == 9, 'PART_COUNT')
    dump(folder / 'PARENT_PARTS.json', {'schema_version': '1', 'zip_file': ZIP_NAME,
        'zip_bytes': ZIP_BYTES, 'zip_sha256': ZIP_SHA, 'source_artifact_id': ARTIFACT,
        'source_run_id': RUN, 'parts': parts})
    shutil.copy2(ROOT / 'reconstruct_parent.py', folder)
    joined = subprocess.run([sys.executable, '-B', str(ROOT / 'reconstruct_parent.py'),
        '--directory', str(folder), '--output', str(work / 'reconstructed.zip')],
        check=True, capture_output=True, text=True)
    check(json.loads(joined.stdout)['sha256'] == ZIP_SHA, 'LOCAL_SPLIT_RESTORE')
    # Store only <=20 MiB parts; never rewrite or recompress the 187 MB accepted ZIP.
    parent.unlink()
    readme = '# DEPTH40 新父包永久归档\n\n'
    readme += '父包：**CP11_DEPTH40_P03_COMPAT_V2_PARENT_20260912**。完整 ZIP 原字节分成 9 卷，全部已存 Git 对象，不依赖 Actions Artifact 的 90 天有效期。\n\n'
    readme += f'原始验收：[Run {RUN}](https://github.com/{REPO}/actions/runs/{RUN})；源提交 `{SOURCE}`。\n\n'
    readme += f'合并后的文件：`{ZIP_NAME}`，{ZIP_BYTES} bytes。\n\n完整 SHA256：\n\n```text\n{ZIP_SHA}\n```\n\n'
    readme += '下载本目录的 9 个 `.part000` 至 `.part008`、`PARENT_PARTS.json` 和 `reconstruct_parent.py` 到同一目录，然后执行：\n\n'
    readme += f'```sh\npython3 reconstruct_parent.py --directory . --output {ZIP_NAME}\n```\n\n'
    readme += '脚本逐卷校验并核验总包哈希，只写入不存在的新文件，不执行包内代码或加载镜像。保留原 `.zip.sha256` 与 `verify_parent.py` 可进行原父包离线完整校验和恢复。\n\n'
    readme += '| 分卷 | 字节数 | SHA256 |\n|---|---:|---|\n'
    for part in parts:
        readme += f"| [{part['name']}]({part['name']}) | {part['bytes']} | `{part['sha256']}` |\n"
    readme += '\n本目录的 PARENT_BUILD_REPORT、PARENT_MANIFEST、VERIFY_RESULT、verify_parent.py 与 ZIP 校验文件均来自已校验的原 Artifact，原始验收日志存于仓库 evidence/depth40-parent-compat-v2/34644569516。ARCHIVE_RECEIPT 记录写入与从 Git blob 回读重组的实际核验结果。\n\n'
    readme += '旧父包和业务源码不变；本次仅保存，不合并 PR、不安装或部署。SITE_BINDING=UNBOUND，香港执行未发生，Production 继续 HOLD。Git 归档内容没有 Actions 自动到期规则；仍应保留正常仓库备份。\n'
    (folder / 'README.md').write_text(readme)
    (folder / 'SHA256SUMS').write_text(''.join(sha(p) + '  ' + p.name + '\n' for p in sorted(folder.iterdir())))
    payload = {DEST + '/' + p.name: p for p in sorted(folder.iterdir())}
    for path in sorted(Path(EVIDENCE).iterdir()):
        check(path.is_file() and not path.is_symlink(), 'EVIDENCE_FILE_TYPE')
        payload[path.as_posix()] = path
    check(all(path.startswith(DEST + '/') or path.startswith(EVIDENCE + '/') for path in payload), 'ARCHIVE_WRITE_SCOPE')
    entries = []
    for name, path in payload.items():
        blob_sha = publish_blob(path)
        entries.append({'path': name, 'mode': '100644', 'type': 'blob', 'sha': blob_sha})
        print('BLOB_SAVED=' + json.dumps({'path': name, 'sha': blob_sha, 'bytes': path.stat().st_size}), flush=True)
    # Re-read actual stored Git blobs and reassemble the exact accepted parent ZIP.
    readback = work / 'git-readback'; readback.mkdir()
    part_names = {p['name'] for p in parts} | {'PARENT_PARTS.json'}
    for entry in entries:
        if entry['path'].startswith(DEST + '/') and Path(entry['path']).name in part_names:
            retrieve_blob(entry['sha'], readback / Path(entry['path']).name)
    roundtrip = subprocess.run([sys.executable, '-B', str(ROOT / 'reconstruct_parent.py'),
        '--directory', str(readback), '--output', str(work / 'git-restored.zip')],
        check=True, capture_output=True, text=True)
    actual = json.loads(roundtrip.stdout)
    check(actual['sha256'] == ZIP_SHA and actual['bytes'] == ZIP_BYTES, 'GIT_READBACK_RECONSTRUCTION')
    receipt = {'schema_version': '1', 'created_at': datetime.now(timezone.utc).isoformat(),
        'archive_job_run_id': os.environ['GITHUB_RUN_ID'], 'archive_tool_commit': os.environ['GO_ARCHIVE_SHA'],
        'source_packaging_commit': SOURCE, 'source_run_id': RUN, 'source_artifact_id': ARTIFACT,
        'source_wrapper_sha256': WRAPPER_SHA, 'branch': BRANCH, 'directory': DEST,
        'zip_file': ZIP_NAME, 'zip_bytes': ZIP_BYTES, 'zip_sha256': ZIP_SHA,
        'part_count': len(parts), 'git_blob_readback': 'PASS', 'reconstructed_zip_sha256': actual['sha256'],
        'payload_files': len(entries), 'application_tests_rerun': False, 'image_rebuilt': False,
        'previous_parent_overwritten': False, 'merged': False, 'hong_kong_execution': 'NOT_RUN',
        'production': 'HOLD', 'entries': entries}
    receipt_path = work / 'ARCHIVE_RECEIPT.json'; dump(receipt_path, receipt)
    entries.append({'path': DEST + '/ARCHIVE_RECEIPT.json', 'mode': '100644', 'type': 'blob',
                    'sha': publish_blob(receipt_path)})
    original = api('/git/commits/' + SOURCE)
    tree = api('/git/trees', {'base_tree': original['tree']['sha'], 'tree': entries})
    commit = api('/git/commits', {'message': 'archive: persist verified DEPTH40 compatibility V2 parent as exact-byte parts',
        'tree': tree['sha'], 'parents': [SOURCE]})
    # Create a new ref only; no PATCH/force push/update of any branch is implemented.
    ref = api('/git/refs', {'ref': 'refs/heads/' + BRANCH, 'sha': commit['sha']})
    check(ref['object']['sha'] == commit['sha'], 'ARCHIVE_REF_WRITE')
    committed = api('/git/trees/' + tree['sha'] + '?recursive=1')
    check(not committed.get('truncated', False), 'ARCHIVE_TREE_TRUNCATED')
    tree_map = {e['path']: e['sha'] for e in committed['tree'] if e['type'] == 'blob'}
    check(all(tree_map.get(e['path']) == e['sha'] for e in entries), 'COMMITTED_TREE_MISMATCH')
    final = {**receipt, 'archive_commit': commit['sha'], 'archive_tree': tree['sha'], 'committed_tree_check': 'PASS',
             'archive_url': f'https://github.com/{REPO}/tree/{commit["sha"]}/{DEST}'}
    out = Path('archive-result'); out.mkdir()
    dump(out / 'ARCHIVE_RESULT.json', final)
    print('ARCHIVE_RESULT=' + json.dumps(final, sort_keys=True), flush=True)


if __name__ == '__main__': main()
