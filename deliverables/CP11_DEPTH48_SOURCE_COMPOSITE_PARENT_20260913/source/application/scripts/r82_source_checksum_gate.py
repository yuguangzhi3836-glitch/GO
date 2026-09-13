#!/usr/bin/env python3
from __future__ import annotations
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKSUM_FILE = ROOT / 'SOURCE_CHECKSUMS.sha256'
SERVER_INJECTED = {
    'deploy/.env.822-staging',
    'deploy/compose.822-staging.yml',
    'deploy/Caddyfile.822-staging',
}
NON_SOURCE_METADATA = {'SOURCE_CHECKSUMS.sha256'}
CACHE_PARTS = {'__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', 'media_cache'}
BAD_SUFFIXES = {'.pyc', '.pyo'}

def block(msg: str) -> None:
    print('R8.2_SOURCE_CHECKSUM_GATE: BLOCK')
    print(msg)
    raise SystemExit(1)

def eligible(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    if rel in SERVER_INJECTED or rel in NON_SOURCE_METADATA:
        return False
    if any(part in CACHE_PARTS for part in path.relative_to(ROOT).parts):
        return False
    if path.suffix.lower() in BAD_SUFFIXES:
        return False
    if rel.startswith('deploy/evidence/'):
        return False
    return path.is_file()

if not CHECKSUM_FILE.is_file():
    block('CHECKSUM_FILE_MISSING')
expected = {}
for line in CHECKSUM_FILE.read_text(encoding='utf-8').splitlines():
    line = line.strip()
    if not line:
        continue
    try:
        digest, rel = line.split('  ', 1)
    except ValueError:
        block('INVALID_CHECKSUM_LINE:' + line)
    if rel in expected:
        block('DUPLICATE_ENTRY:' + rel)
    expected[rel] = digest

actual_paths = sorted(p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if eligible(p))
actual_set = set(actual_paths)
expected_set = set(expected)
missing = sorted(actual_set - expected_set)
extra = sorted(expected_set - actual_set)
if missing:
    block('UNCHECKED_SOURCE_FILES:' + ','.join(missing[:20]))
if extra:
    block('STALE_CHECKSUM_ENTRIES:' + ','.join(extra[:20]))

for rel in actual_paths:
    h = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
    if h != expected[rel]:
        block('CHECKSUM_MISMATCH:' + rel)

for rel in SERVER_INJECTED:
    if rel in expected:
        block('SERVER_INJECTED_FILE_MUST_NOT_BE_CHECKSUMMED:' + rel)

print(f'R8.2_SOURCE_CHECKSUM_GATE: PASS files={len(actual_paths)} server_injected_whitelist={len(SERVER_INJECTED)}')
