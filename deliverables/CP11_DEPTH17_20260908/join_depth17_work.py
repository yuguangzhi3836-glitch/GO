#!/usr/bin/env python3
"""Join the cumulative GO review WORK archive and verify every part and final SHA256."""
import hashlib
import json
from pathlib import Path
import tempfile


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def main():
    root=Path(__file__).resolve().parent
    manifest=json.loads((root/'GO_DEPTH17_WORK_PARTS.json').read_text())
    names=[manifest['filename']]+[p['filename'] for p in manifest['parts']]
    if any(Path(n).name!=n or '\\' in n or ':' in n for n in names):raise ValueError('UNSAFE_FILENAME')
    destination=root/manifest['filename']
    if destination.exists():
        if destination.stat().st_size==manifest['size'] and sha(destination)==manifest['sha256']:
            print('ALREADY_VERIFIED',destination.name);return
        raise ValueError('EXISTING_OUTPUT_DOES_NOT_MATCH; choose a new directory')
    with tempfile.NamedTemporaryFile(dir=root,suffix='.joining',delete=False) as output:
        temporary=Path(output.name)
        try:
            for part in manifest['parts']:
                source=root/'work_parts'/part['filename']
                if source.stat().st_size!=part['size'] or sha(source)!=part['sha256']:
                    raise ValueError('PART_INTEGRITY_FAILED:'+part['filename'])
                with source.open('rb') as stream:
                    for block in iter(lambda:stream.read(1024*1024),b''):output.write(block)
            output.flush()
        except BaseException:
            temporary.unlink(missing_ok=True);raise
    try:
        if temporary.stat().st_size!=manifest['size'] or sha(temporary)!=manifest['sha256']:
            raise ValueError('WHOLE_ARCHIVE_INTEGRITY_FAILED')
        # A pre-existing different destination was rejected before any write.
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True);raise
    print('WORK_ARCHIVE_VERIFIED',destination.name,manifest['sha256'])


if __name__=='__main__':main()
