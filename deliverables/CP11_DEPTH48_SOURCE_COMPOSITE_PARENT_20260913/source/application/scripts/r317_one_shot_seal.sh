#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PARENT=$(CDPATH= cd -- "$ROOT/.." && pwd)
# V8: sealing workspace and output are script-owned sibling paths outside source ROOT.
# Environment overrides are intentionally not accepted.
WORK="$PARENT/.r317_v8_seal_work"
OUT="$PARENT/r317_v8_seal_output"
case "$WORK" in
  "$ROOT"|"$ROOT"/*) echo "BLOCK: V8 WORK must be outside source ROOT: $WORK"; exit 1 ;;
esac
case "$OUT" in
  "$ROOT"|"$ROOT"/*) echo "BLOCK: V8 OUT must be outside source ROOT: $OUT"; exit 1 ;;
esac
[ "$WORK" != "$OUT" ] || { echo 'BLOCK: V8 WORK and OUT must be distinct'; exit 1; }
mkdir -p "$WORK" "$OUT"
WORK=$(CDPATH= cd -- "$WORK" && pwd -P)
OUT=$(CDPATH= cd -- "$OUT" && pwd -P)
case "$WORK" in
  "$ROOT"|"$ROOT"/*) echo "BLOCK: canonical V8 WORK resolved inside source ROOT: $WORK"; exit 1 ;;
esac
case "$OUT" in
  "$ROOT"|"$ROOT"/*) echo "BLOCK: canonical V8 OUT resolved inside source ROOT: $OUT"; exit 1 ;;
esac
RUNTIME=${R317_RUNTIME_TARBALL:-${1:-}}
[ -n "$RUNTIME" ] || { echo 'BLOCK: set R317_RUNTIME_TARBALL or pass exact runtime tarball path as arg1'; exit 1; }
"$ROOT/scripts/r317_verify_runtime_source.sh" "$RUNTIME" | tee "$OUT/R3_1_7_RUNTIME_SOURCE_VERIFY.txt"
# Build runtime. This intentionally fails closed if the locked wheelhouse is incomplete.
"$ROOT/scripts/r317_build_hermetic_runtime.sh" "$RUNTIME"
# Provision and seal the independent Node verification toolchain before any Full Release Gate.
"$ROOT/scripts/r317_provision_node_toolchain.sh" | tee "$OUT/R3_1_7_NODE_TOOLCHAIN_PROVISION.txt"
"$ROOT/gate_runtime/python/bin/python3" "$ROOT/scripts/r82_gate_toolchain_integrity.py" | tee "$OUT/R3_1_7_NODE_TOOLCHAIN_INTEGRITY.txt"
"$ROOT/scripts/r82_gate_runtime_compatibility.sh" | tee "$OUT/R3_1_7_COMPATIBILITY_GATE.txt"
"$ROOT/gate_runtime/python/bin/python3" "$ROOT/scripts/r82_gate_runtime_integrity.py" | tee "$OUT/R3_1_7_RUNTIME_INTEGRITY.txt"
# Rebuild source checksum after runtime integration.
"$ROOT/gate_runtime/python/bin/python3" - "$ROOT" <<'PY'
import hashlib, pathlib, sys
root=pathlib.Path(sys.argv[1])
out=root/'SOURCE_CHECKSUMS.sha256'
SERVER={'deploy/.env.822-staging','deploy/compose.822-staging.yml','deploy/Caddyfile.822-staging'}
META={'SOURCE_CHECKSUMS.sha256'}; CACHE={'__pycache__','.pytest_cache','.mypy_cache','.ruff_cache','media_cache'}; BAD={'.pyc','.pyo'}
def eligible(p):
 rel=p.relative_to(root).as_posix()
 return p.is_file() and rel not in SERVER and rel not in META and not rel.startswith('deploy/evidence/') and not any(x in CACHE for x in p.relative_to(root).parts) and p.suffix.lower() not in BAD
paths=sorted((p for p in root.rglob('*') if eligible(p)), key=lambda p:p.relative_to(root).as_posix())
with out.open('w',encoding='utf-8') as f:
 for p in paths:
  f.write(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(root).as_posix()+'\n')
print('source_checksum_files='+str(len(paths)))
PY
"$ROOT/gate_runtime/python/bin/python3" "$ROOT/scripts/r82_source_checksum_gate.py" | tee "$OUT/R3_1_7_SOURCE_CHECKSUM_GATE.txt"
"$ROOT/gate_runtime/python/bin/python3" "$ROOT/scripts/r82_manifest_consistency_gate.py" | tee "$OUT/R3_1_7_MANIFEST_GATE.txt"
(
 cd "$ROOT"
 set +e
 bash scripts/release_gate_r82.sh > "$OUT/R3_1_7_SOURCE_FULL_RELEASE_GATE.txt" 2>&1
 rc=$?
 set -e
 cat "$OUT/R3_1_7_SOURCE_FULL_RELEASE_GATE.txt"
 [ "$rc" -eq 0 ] || { echo "BLOCK: source full release gate exit=$rc"; exit "$rc"; }
 grep -q 'R8.2 RELEASE GATE: PASS' "$OUT/R3_1_7_SOURCE_FULL_RELEASE_GATE.txt" || { echo 'BLOCK: source release PASS marker missing'; exit 1; }
)
# Exact zip after all source-side PASS. Keep evidence outside ZIP until final proof to avoid mutating sealed bytes.
rm -rf "$WORK/package" "$WORK/fresh"
mkdir -p "$WORK/package" "$WORK/fresh"
BASE=$(basename "$ROOT")
cp -a "$ROOT" "$WORK/package/$BASE"
ZIP="$OUT/GO_R82_R3_1_7_AUDIT_SEALED_20260828.zip"
rm -f "$ZIP"
(cd "$WORK/package" && zip -X -q -r "$ZIP" "$BASE")
unzip -t "$ZIP" | tee "$OUT/R3_1_7_ZIP_INTEGRITY.txt"
unzip -q "$ZIP" -d "$WORK/fresh"
FRESH="$WORK/fresh/$BASE"
"$FRESH/scripts/r82_gate_runtime_compatibility.sh" | tee "$OUT/R3_1_7_FRESH_COMPATIBILITY_GATE.txt"
"$FRESH/gate_runtime/python/bin/python3" "$FRESH/scripts/r82_gate_runtime_integrity.py" | tee "$OUT/R3_1_7_FRESH_RUNTIME_INTEGRITY.txt"
"$FRESH/gate_runtime/python/bin/python3" "$FRESH/scripts/r82_gate_toolchain_integrity.py" | tee "$OUT/R3_1_7_FRESH_NODE_TOOLCHAIN_INTEGRITY.txt"
"$FRESH/gate_runtime/python/bin/python3" "$FRESH/scripts/r82_source_checksum_gate.py" | tee "$OUT/R3_1_7_FRESH_SOURCE_CHECKSUM_GATE.txt"
"$FRESH/gate_runtime/python/bin/python3" "$FRESH/scripts/r82_manifest_consistency_gate.py" | tee "$OUT/R3_1_7_FRESH_MANIFEST_GATE.txt"
(
 cd "$FRESH"
 set +e
 bash scripts/release_gate_r82.sh > "$OUT/R3_1_7_FRESH_FULL_RELEASE_GATE.txt" 2>&1
 rc=$?
 set -e
 cat "$OUT/R3_1_7_FRESH_FULL_RELEASE_GATE.txt"
 [ "$rc" -eq 0 ] || { echo "BLOCK: fresh full release gate exit=$rc"; exit "$rc"; }
 grep -q 'R8.2 RELEASE GATE: PASS' "$OUT/R3_1_7_FRESH_FULL_RELEASE_GATE.txt" || { echo 'BLOCK: fresh release PASS marker missing'; exit 1; }
)
# Content proof.
for p in gate_runtime/python/bin/python3 gate_toolchain/node/bin/node gate_toolchain/NODE_SOURCE.json gate_toolchain/NODE_MANIFEST.json scripts/r82_gate_toolchain_integrity.py gate_runtime/RUNTIME_MANIFEST.json gate_runtime/requirements.lock scripts/r82_gate_runtime_compatibility.sh scripts/r82_gate_runtime_integrity.py scripts/release_gate_r82.sh SOURCE_CHECKSUMS.sha256 CURRENT_RELEASE_MANIFEST.json R3_1_7_HERMETIC_RUNTIME_GLIBC_COMPATIBILITY_REBUILD_20260828.md; do
  [ -e "$FRESH/$p" ] || { echo "BLOCK: content proof missing $p"; exit 1; }
  echo "PRESENT $p"
done | tee "$OUT/R3_1_7_ZIP_CONTENT_PROOF.txt"
sha256sum "$ZIP" | tee "$ZIP.sha256"
BYTES=$(wc -c < "$ZIP" | tr -d ' ')
SHA=$(awk '{print $1}' "$ZIP.sha256")
cat > "$OUT/R3_1_7_FINAL_SEAL_RECORD.txt" <<EOF
R3.1.7 AUDIT-SEALED / FROZEN
artifact=$(basename "$ZIP")
bytes=$BYTES
sha256=$SHA
python=3.13.5
target_glibc_max=2.35
source_full_release_gate=PASS_EXIT_0
fresh_extraction_full_release_gate=PASS_EXIT_0
compatibility_gate=PASS
runtime_integrity=PASS
node_toolchain_integrity=PASS
sealed_node=v22.22.0
source_checksum=PASS
manifest_consistency=PASS
zip_content_proof=PASS
EOF
cat "$OUT/R3_1_7_FINAL_SEAL_RECORD.txt"
