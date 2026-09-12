#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, os, subprocess
from pathlib import Path

def sha(path: Path) -> str:
    h=hashlib.sha256(); h.update(path.read_bytes()); return h.hexdigest()

def git(*args):
    try: return subprocess.check_output(['git',*args], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception: return 'unknown'
root=Path(__file__).resolve().parents[1]
manifest={
  'git_sha': os.getenv('GIT_SHA') or git('rev-parse','HEAD'),
  'image_tag': os.getenv('IMAGE_TAG','unbuilt'),
  'alembic_head': '0017_sprint1v',
  'openapi_sha256': sha(root/'openapi_runtime_sprint1v.json'),
  'staging_compose_sha256': sha(root/'docker-compose.staging.yml'),
}
print(json.dumps(manifest, indent=2, sort_keys=True))
