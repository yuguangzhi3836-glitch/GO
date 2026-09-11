"""Authenticate extracted fixed artifact before executing its verified integrity tool."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from identity import *

assert os.environ.get('GITHUB_ACTIONS') == 'true'
root = Path('fixed-runtime')
out = Path('upgrade-evidence'); out.mkdir(exist_ok=True)
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(root/'SHA256SUMS') == SUMS
assert sha(root/'verify_delivery.py') == VERIFIER
p = subprocess.run([sys.executable, '-B', str(root/'verify_delivery.py'), '--directory', str(root)],
                   capture_output=True, text=True, check=True)
(out/'FIXED_RUNTIME_VERIFICATION.json').write_text(p.stdout)
meta = json.loads((root/'RUNTIME_MANIFEST.json').read_text())
for key, expected in {'candidate': CANDIDATE, 'candidate_build_commit': BUILD,
    'parent_artifact_id': ARTIFACT, 'parent_archive_sha256': PARENT_ARCHIVE,
    'source_tree_sha256': TREE, 'source_files': 1271, 'image_config_id': IMAGE,
    'runtime_archive_sha256': IMAGE_ARCHIVE}.items():
    assert meta[key] == expected, key
parts = json.loads((root/'RUNTIME_PARTS.json').read_text())
archive = Path('fixed-runtime-image.tar.gz')
with archive.open('xb') as dest:
    for part in parts['parts']:
        dest.write((root/part['name']).read_bytes())
assert sha(archive) == IMAGE_ARCHIVE
(out/'CANDIDATE_BINDING.json').write_text(json.dumps(binding(), indent=2)+'\n')
print(json.dumps({'fixed_image_archive_sha256': sha(archive), 'image_id': IMAGE,
                  'image_build': 'NOT_RUN', 'hk_execution': 'NOT_RUN'}))
