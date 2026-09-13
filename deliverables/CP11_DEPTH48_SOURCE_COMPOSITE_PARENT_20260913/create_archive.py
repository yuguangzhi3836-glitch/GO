"""Create a deterministic ZIP from a verified checkout; never overwrite output."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import zipfile

sys.dont_write_bytecode = True
from verify_parent import inventory, require, safe_name, sha256, verify


def verify_zip(archive, rows, prefix):
    expected = {prefix + '/' + name: row for name, row in rows.items()}
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        names = [info.filename for info in infos]
        require(len(set(names)) == len(names), 'ZIP_DUPLICATE')
        require(set(names) == set(expected), 'ZIP_FILE_SET')
        for info in infos:
            safe_name(info.filename)
            mode = info.external_attr >> 16
            require(stat.S_ISREG(mode), 'ZIP_SPECIAL_FILE')
            row = expected[info.filename]
            require(info.file_size == row['bytes'] and bool(mode & 0o111) ==
                    (row['mode'] == '100755'), 'ZIP_METADATA')
            with z.open(info) as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            require(digest == row['sha256'], 'ZIP_HASH')


def create(root, output, manifest_sha256):
    root, output = Path(root).resolve(), Path(output).absolute()
    require(not output.exists() and not output.is_symlink(), 'OUTPUT_EXISTS')
    require(not output.resolve().is_relative_to(root), 'OUTPUT_INSIDE_INPUT')
    result = verify(root, manifest_sha256)
    rows, _ = inventory(root)
    fd, temporary = tempfile.mkstemp(prefix='.go-parent-', suffix='.zip', dir=output.parent)
    os.close(fd)
    temporary = Path(temporary)
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6, allowZip64=True) as z:
            for name, row in sorted(rows.items()):
                info = zipfile.ZipInfo(root.name + '/' + name, (2026, 9, 13, 0, 0, 0))
                info.create_system = 3
                mode = 0o100755 if row['mode'] == '100755' else 0o100644
                info.external_attr = mode << 16
                info.compress_type = zipfile.ZIP_STORED if '.zip.part' in name else zipfile.ZIP_DEFLATED
                with (root / name).open('rb') as src, z.open(info, 'w', force_zip64=True) as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
        verify_zip(temporary, rows, root.name)
        # An existing file or symlink always causes exclusive publication to fail.
        os.link(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return dict(result, zip_file=output.name, zip_bytes=output.stat().st_size,
                zip_sha256=sha256(output), zip_readback='PASS')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(create(args.directory, args.output, args.manifest_sha256), sort_keys=True))
