"""Export only fingerprinted sealed source, never environment or runtime files.

Preparation only: no imports from the application, no dependency installation,
no application execution, no network calls, no tests, no release promotion.
"""
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import zipfile

CANDIDATE = 'c495ca6547a667b9a4eb94a02e296231f9b88e79'
EXPECTED = 'f576c976bfe8f34d3182ba232fe1290c374346106c602a4fffe4935366f7a961'


def main():
    fp = json.loads(Path('candidate/deliverables/CP11_DEPTH30_NATIVE_PAYMENT_20260909/SOURCE_FINGERPRINT.json').read_text())
    digest = hashlib.sha256(''.join(f'{p}\0{h}\n' for p, h in sorted(fp.items())).encode()).hexdigest()
    if digest != EXPECTED or len(fp) != 1222:
        raise ValueError('UNEXPECTED_CANDIDATE_FINGERPRINT')
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for name, expected in sorted(fp.items()):
            rel = PurePosixPath(name)
            if rel.is_absolute() or '..' in rel.parts or '\\' in name or str(rel) != name:
                raise ValueError('UNSAFE_SOURCE_PATH')
            path = Path('restored') / rel
            if path.is_symlink() or not path.is_file():
                raise ValueError('INVALID_SOURCE_FILE:' + name)
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError('SOURCE_MISMATCH:' + name)
            item = zipfile.ZipInfo(name, date_time=(2026, 9, 9, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o100644 << 16
            output.writestr(item, raw)
    payload = data.getvalue()
    Path('evidence').mkdir(exist_ok=True)
    Path('evidence/verified-source.zip').write_bytes(payload)
    record = dict(candidate=CANDIDATE, source_tree_sha256=digest,
                  source_files=len(fp), zip_sha256=hashlib.sha256(payload).hexdigest(),
                  zip_bytes=len(payload), scope='source materialization and integrity only',
                  application_executed=False, tests_rerun=False, deployed=False,
                  release_gate='HOLD')
    Path('evidence/source-export.json').write_text(json.dumps(record, indent=2) + '\n')
    print('GO_SOURCE_RECORD ' + json.dumps(record), flush=True)
    encoded = base64.b64encode(payload).decode('ascii')
    # Chunked private job-log transport avoids binary connector limits. No
    # credentials, caches, runtime configuration or untracked files are read.
    for index, start in enumerate(range(0, len(encoded), 3000)):
        print(f'GO_SOURCE_CHUNK {index:06d} ' + encoded[start:start + 3000], flush=True)
    print('GO_SOURCE_END', flush=True)


if __name__ == '__main__':
    main()
