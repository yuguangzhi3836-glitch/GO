#!/usr/bin/env python3
"""Check all unpacked delivery files against the embedded manifest."""
import hashlib
import json
from pathlib import Path

def main():
    root=Path(__file__).resolve().parents[1]
    manifest=json.loads((root/'DELIVERY_FILE_MANIFEST.json').read_text())
    failures=[]
    for entry in manifest['files']:
        path=(root/entry['path']).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            failures.append(entry['path']);continue
        h=hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
        if path.stat().st_size!=entry['size'] or h.hexdigest()!=entry['sha256']:failures.append(entry['path'])
    if failures:raise SystemExit('DELIVERY_INTEGRITY_FAILED: '+', '.join(failures))
    print('DELIVERY_INTEGRITY_PASS',len(manifest['files']),'files')
    print('Engineering review copy; integrity is not release acceptance.')

if __name__=='__main__':main()
