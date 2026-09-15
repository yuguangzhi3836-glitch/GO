#!/usr/bin/env python3
"""Build a clean R8.2 candidate ZIP without runtime/test residue.

This builder intentionally excludes bytecode caches, media/runtime caches,
deployment evidence, and local test-output residue. It preserves source files
only; shell executable bits are not trusted by deployment and are restored by
`deploy/deploy_hk_staging.sh`.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import zipfile

EXCLUDED_DIR_NAMES = {
    '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache',
    'media_cache', '.cache', 'tmp', 'temp',
}
EXCLUDED_SUFFIXES = {'.pyc', '.pyo'}
EXCLUDED_PREFIXES = ('deploy/evidence/',)
EXCLUDED_FILE_NAMES = {
    '.coverage', 'coverage.xml', 'pytest-report.xml',
}


def should_exclude(rel: Path) -> bool:
    if any(part in EXCLUDED_DIR_NAMES for part in rel.parts):
        return True
    posix = rel.as_posix()
    if any(posix.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return True
    if rel.suffix.lower() in EXCLUDED_SUFFIXES:
        return True
    if rel.name in EXCLUDED_FILE_NAMES:
        return True
    # Local ad-hoc outputs convention; checked-in historical verification
    # artifacts remain part of the repository evidence bundle.
    if rel.name.startswith(('local_test_', 'tmp_test_', 'scratch_')):
        return True
    return False


def build(root: Path, out: Path) -> tuple[int, list[str]]:
    root = root.resolve()
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    included = 0
    excluded: list[str] = []
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(root.rglob('*')):
            if not path.is_file() or path.resolve() == out:
                continue
            rel = path.relative_to(root)
            if should_exclude(rel):
                excluded.append(rel.as_posix())
                continue
            info = zipfile.ZipInfo.from_file(path, arcname=rel.as_posix())
            # Normalize timestamps for reproducibility within the source tree's
            # current metadata; permissions are retained when the ZIP tool can.
            with path.open('rb') as fh:
                zf.writestr(info, fh.read(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
            included += 1
    return included, excluded


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    count, excluded = build(Path(args.root), Path(args.out))
    print(f'R8.2_CANDIDATE_PACKAGE_BUILD: PASS files={count} excluded={len(excluded)}')
    for item in excluded:
        print('EXCLUDED:' + item)


if __name__ == '__main__':
    main()
