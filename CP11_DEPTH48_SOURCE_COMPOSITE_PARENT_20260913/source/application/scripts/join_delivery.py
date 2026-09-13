#!/usr/bin/env python3
"""Reassemble the downloaded GO raw-byte parts, checking every SHA256 first."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',nargs='?',type=Path,default=Path(__file__).resolve().parent)
    args=parser.parse_args();folder=args.directory.resolve()
    metadata=json.loads((folder/'GO_MASTER03_PARTS.json').read_text())
    for name in [metadata['filename']]+[part['filename'] for part in metadata['parts']]:
        if Path(name).name!=name or name in {'.','..'}:raise SystemExit('Invalid filename in manifest')
    target=folder/metadata['filename'];temp=folder/(metadata['filename']+'.joining')
    if target.exists():raise SystemExit('The output ZIP already exists; it was not overwritten.')
    for part in metadata['parts']:
        file=folder/part['filename']
        if not file.is_file() or file.stat().st_size!=part['size']:
            raise SystemExit('Missing or incomplete part: '+part['filename'])
    total=hashlib.sha256();size=0
    try:
        with temp.open('xb') as output:
            for part in metadata['parts']:
                current=hashlib.sha256()
                with (folder/part['filename']).open('rb') as source:
                    for block in iter(lambda:source.read(1024*1024),b''):
                        current.update(block);total.update(block);size+=len(block);output.write(block)
                if current.hexdigest()!=part['sha256']:raise ValueError('Part checksum failed: '+part['filename'])
                print('Verified',part['filename'])
        if total.hexdigest()!=metadata['sha256'] or size!=metadata['size']:
            raise ValueError('Complete ZIP checksum failed')
        with zipfile.ZipFile(temp) as archive:
            bad=archive.testzip()
            if bad:raise ValueError('ZIP integrity failed: '+bad)
        temp.rename(target)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    print('Verified complete archive:',target)
    print('SHA256:',total.hexdigest())

if __name__=='__main__':main()
