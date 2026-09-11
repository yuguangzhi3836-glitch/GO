"""Reassemble the nine committed parts without changing the accepted parent ZIP."""
import argparse
import hashlib
import json
from pathlib import Path
import os
import tempfile

EXPECTED_NAME = 'CP11_DEPTH40_P03_COMPAT_V2_PARENT_20260912.zip'
EXPECTED_SHA = '421b11f95d0400bdfc69d4053a6d3b54599fa791a0d6b43311b83094bcd51c6a'
EXPECTED_BYTES = 187168614


def reconstruct(directory, output):
    data = json.loads((directory / 'PARENT_PARTS.json').read_text())
    if data['zip_file'] != EXPECTED_NAME or data['zip_sha256'] != EXPECTED_SHA or data['zip_bytes'] != EXPECTED_BYTES:
        raise ValueError('PARENT_IDENTITY_MISMATCH')
    parts = data['parts']
    if len(parts) != 9 or [p['name'] for p in parts] != [EXPECTED_NAME + f'.part{i:03d}' for i in range(9)]:
        raise ValueError('PART_ORDER_MISMATCH')
    if output.exists() or output.is_symlink():
        raise ValueError('OUTPUT_EXISTS')
    digest = hashlib.sha256(); total = 0
    temp = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.go-parent-', dir=output.parent, delete=False) as target:
            temp = Path(target.name)
            for part in parts:
                path = directory / part['name']
                if path.is_symlink() or not path.is_file():
                    raise ValueError('PART_NOT_REGULAR')
                part_digest = hashlib.sha256(); size = 0
                with path.open('rb') as source:
                    while chunk := source.read(1024 * 1024):
                        target.write(chunk); digest.update(chunk); part_digest.update(chunk)
                        size += len(chunk); total += len(chunk)
                if size != part['bytes'] or part_digest.hexdigest() != part['sha256']:
                    raise ValueError('PART_HASH_MISMATCH:' + part['name'])
            target.flush(); os.fsync(target.fileno())
        if total != EXPECTED_BYTES or digest.hexdigest() != EXPECTED_SHA:
            raise ValueError('PARENT_ZIP_HASH_MISMATCH')
        # Atomic publication without replacing an existing path, including races.
        os.link(temp, output)
        return {'status': 'PASS', 'zip_file': str(output), 'bytes': total, 'sha256': digest.hexdigest()}
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--output', type=Path, default=Path(EXPECTED_NAME))
    args = parser.parse_args()
    print(json.dumps(reconstruct(args.directory, args.output), sort_keys=True))
