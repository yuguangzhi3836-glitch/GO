#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
RUNTIME_ROOT=${R8_2_GATE_RUNTIME_ROOT:-$ROOT/gate_runtime/python}
TARGET_MAJOR=2
TARGET_MINOR=35
block() { echo "R8.2_GATE_RUNTIME_COMPATIBILITY: BLOCK"; echo "$1"; exit 1; }
[ -d "$RUNTIME_ROOT" ] || block "RUNTIME_ROOT_MISSING:$RUNTIME_ROOT"
PY="$RUNTIME_ROOT/bin/python3"
[ -x "$PY" ] || block "PYTHON_MISSING_OR_NOT_EXECUTABLE:$PY"
if command -v readelf >/dev/null 2>&1; then INSPECTOR=readelf
elif command -v objdump >/dev/null 2>&1; then INSPECTOR=objdump
else block "ELF_INSPECTOR_MISSING:need readelf or objdump"; fi
max_major=0; max_minor=0; scanned=0
scan_one() {
  f=$1
  if [ "$INSPECTOR" = readelf ]; then
    vers=$(readelf --version-info "$f" 2>/dev/null | grep -o 'GLIBC_[0-9][0-9]*\.[0-9][0-9]*' || true)
  else
    vers=$(objdump -T "$f" 2>/dev/null | grep -o 'GLIBC_[0-9][0-9]*\.[0-9][0-9]*' || true)
  fi
  for v in $vers; do
    n=${v#GLIBC_}; maj=${n%%.*}; min=${n#*.}
    case "$maj:$min" in *[!0-9:]*|'') continue;; esac
    if [ "$maj" -gt "$max_major" ] || { [ "$maj" -eq "$max_major" ] && [ "$min" -gt "$max_minor" ]; }; then max_major=$maj; max_minor=$min; fi
  done
  scanned=$((scanned+1))
}
scan_one "$PY"
while IFS= read -r f; do scan_one "$f"; done <<EOF2
$(find "$RUNTIME_ROOT" -type f \( -name '*.so' -o -name '*.so.*' \) -print | sort)
EOF2
if [ "$max_major" -gt "$TARGET_MAJOR" ] || { [ "$max_major" -eq "$TARGET_MAJOR" ] && [ "$max_minor" -gt "$TARGET_MINOR" ]; }; then
  block "target_glibc<=${TARGET_MAJOR}.${TARGET_MINOR} max_required=${max_major}.${max_minor} scanned=$scanned"
fi
ver=$($PY --version 2>&1) || block "PYTHON_VERSION_EXECUTION_FAILED"
case "$ver" in 'Python 3.13.5') :;; *) block "PYTHON_VERSION_MISMATCH:$ver expected='Python 3.13.5'";; esac
echo "R8.2_GATE_RUNTIME_COMPATIBILITY: PASS"
echo "target_glibc<=${TARGET_MAJOR}.${TARGET_MINOR}"
echo "max_required=${max_major}.${max_minor}"
echo "python='$ver'"
echo "scanned_native_files=$scanned"
