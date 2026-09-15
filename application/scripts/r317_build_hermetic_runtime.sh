#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
INPUT=${1:-${R317_RUNTIME_TARBALL:-}}
[ -n "$INPUT" ] || { echo 'usage: scripts/r317_build_hermetic_runtime.sh /path/to/gate_runtime_python_cpython-3.13.5_ubuntu-22.04-x86_64_r3.1.7.tar.gz'; exit 2; }
"$ROOT/scripts/r317_verify_runtime_source.sh" "$INPUT"
[ -f "$ROOT/gate_runtime/requirements.lock" ] || { echo 'BLOCK: requirements.lock missing'; exit 1; }
[ -d "$ROOT/gate_runtime/wheelhouse" ] || { echo 'BLOCK: wheelhouse missing'; exit 1; }
[ -f "$ROOT/gate_runtime/WHEELHOUSE_SHA256SUMS.txt" ] || { echo 'BLOCK: wheelhouse checksum manifest missing'; exit 1; }
(
  cd "$ROOT/gate_runtime/wheelhouse"
  sha256sum -c ../WHEELHOUSE_SHA256SUMS.txt
)
rm -rf "$ROOT/gate_runtime/python"
mkdir -p "$ROOT/gate_runtime/.tmp"
rm -rf "$ROOT/gate_runtime/.tmp"/*
tar -xzf "$INPUT" -C "$ROOT/gate_runtime/.tmp"
# Accept either archive root python/ or direct bin/lib runtime root, but normalize to gate_runtime/python.
if [ -d "$ROOT/gate_runtime/.tmp/python" ]; then
  mv "$ROOT/gate_runtime/.tmp/python" "$ROOT/gate_runtime/python"
elif [ -x "$ROOT/gate_runtime/.tmp/bin/python3" ]; then
  mv "$ROOT/gate_runtime/.tmp" "$ROOT/gate_runtime/python"
  mkdir -p "$ROOT/gate_runtime/.tmp"
else
  echo 'BLOCK: runtime archive layout unsupported'; exit 1
fi
rm -rf "$ROOT/gate_runtime/.tmp"
"$ROOT/scripts/r82_gate_runtime_compatibility.sh"
"$ROOT/gate_runtime/python/bin/python3" -m pip install --no-index --find-links "$ROOT/gate_runtime/wheelhouse" --requirement "$ROOT/gate_runtime/requirements.lock"
"$ROOT/scripts/r82_gate_runtime_compatibility.sh"
(
 cd "$ROOT"
 "$ROOT/gate_runtime/python/bin/python3" - <<'PY2'
import hashlib,json,pathlib
root=pathlib.Path('gate_runtime/python')
h=hashlib.sha256()
for p in sorted(x for x in root.rglob('*') if x.is_file() and '__pycache__' not in x.parts and x.suffix not in {'.pyc','.pyo'}):
 rel=p.relative_to(root).as_posix().encode(); h.update(rel+b'\0'); h.update(hashlib.sha256(p.read_bytes()).digest())
source=json.loads(pathlib.Path('gate_runtime/RUNTIME_SOURCE.json').read_text())
lock=pathlib.Path('gate_runtime/requirements.lock').read_bytes()
wheel_sums=pathlib.Path('gate_runtime/WHEELHOUSE_SHA256SUMS.txt').read_bytes()
manifest={
 'runtime_release':'R3.1.7',
 'python_version':'3.13.5',
 'target_glibc_max':'2.35',
 'source_artifact':source['artifact_name'],
 'source_sha256':source['expected_sha256'],
 'requirements_lock_sha256':hashlib.sha256(lock).hexdigest(),
 'wheelhouse_checksums_sha256':hashlib.sha256(wheel_sums).hexdigest(),
 'tree_sha256':h.hexdigest()
}
pathlib.Path('gate_runtime/RUNTIME_MANIFEST.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
PY2
)
"$ROOT/gate_runtime/python/bin/python3" "$ROOT/scripts/r82_gate_runtime_integrity.py"
echo 'R3.1.7 hermetic runtime build: PASS'
