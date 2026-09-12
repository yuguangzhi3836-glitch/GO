"""Reassemble Git parts into a new ZIP, validating every part and the complete archive."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

NAME = 'CP11_DEPTH41_UNIFIED_PARENT_V1_20260912.zip'


def reconstruct(directory, output):
    index = json.loads((directory / 'PARENT_PARTS.json').read_text())
    if index['zip_file'] != NAME or not index['parts']:
        raise ValueError('WRONG_PACKAGE')
    if [p['name'] for p in index['parts']] != [NAME + f'.part{i:03d}' for i in range(len(index['parts']))]:
        raise ValueError('PART_ORDER')
    if output.exists() or output.is_symlink():
        raise ValueError('OUTPUT_EXISTS')
    temporary = None
    total = 0
    digest = hashlib.sha256()
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix='.go-parent-', delete=False) as target:
            temporary = Path(target.name)
            for part in index['parts']:
                path = directory / part['name']
                if path.is_symlink() or not path.is_file():
                    raise ValueError('PART_NOT_REGULAR')
                part_sha = hashlib.sha256()
                size = 0
                with path.open('rb') as source:
                    while chunk := source.read(1024 * 1024):
                        target.write(chunk)
                        digest.update(chunk)
                        part_sha.update(chunk)
                        total += len(chunk)
                        size += len(chunk)
                if size != part['bytes'] or part_sha.hexdigest() != part['sha256']:
                    raise ValueError('PART_HASH:' + part['name'])
            target.flush()
            os.fsync(target.fileno())
        if total != index['zip_bytes'] or digest.hexdigest() != index['zip_sha256']:
            raise ValueError('ZIP_HASH')
        os.link(temporary, output)
        return {'status': 'PASS', 'zip_bytes': total, 'zip_sha256': digest.hexdigest()}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--output', type=Path, default=Path(NAME))
    args = parser.parse_args()
    print(json.dumps(reconstruct(args.directory, args.output), sort_keys=True))
