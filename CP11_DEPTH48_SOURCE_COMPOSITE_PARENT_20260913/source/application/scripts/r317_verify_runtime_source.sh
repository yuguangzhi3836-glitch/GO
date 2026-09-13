#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SRC=${1:-${R317_RUNTIME_TARBALL:-}}
[ -n "$SRC" ] || { echo 'R3.1.7_RUNTIME_SOURCE: BLOCK'; echo 'RUNTIME_TARBALL_REQUIRED'; exit 1; }
[ -f "$SRC" ] || { echo 'R3.1.7_RUNTIME_SOURCE: BLOCK'; echo "RUNTIME_TARBALL_MISSING:$SRC"; exit 1; }
META=$ROOT/gate_runtime/RUNTIME_SOURCE.json
[ -f "$META" ] || { echo 'R3.1.7_RUNTIME_SOURCE: BLOCK'; echo 'RUNTIME_SOURCE_METADATA_MISSING'; exit 1; }
EXPECTED=$(python3 - "$META" <<'PY'
import json,sys
x=json.load(open(sys.argv[1]))
print(x.get('expected_sha256',''))
PY
)
EXPECTED_NAME=$(python3 - "$META" <<'PY'
import json,sys
x=json.load(open(sys.argv[1]))
print(x.get('artifact_name',''))
PY
)
case "$EXPECTED" in
  [0-9a-f][0-9a-f]*) [ "${#EXPECTED}" -eq 64 ] || { echo 'R3.1.7_RUNTIME_SOURCE: BLOCK'; echo 'EXPECTED_SHA256_INVALID'; exit 1; } ;;
  *) echo 'R3.1.7_RUNTIME_SOURCE: BLOCK'; echo 'EXPECTED_SHA256_INVALID'; exit 1 ;;
esac
ACTUAL=$(sha256sum "$SRC" | awk '{print $1}')
if [ "$ACTUAL" != "$EXPECTED" ]; then
  echo 'R3.1.7_RUNTIME_SOURCE: BLOCK'
  echo "EXPECTED_SHA256=$EXPECTED"
  echo "ACTUAL_SHA256=$ACTUAL"
  exit 1
fi
BASE=$(basename "$SRC")
[ "$BASE" = "$EXPECTED_NAME" ] || {
  echo 'R3.1.7_RUNTIME_SOURCE: BLOCK'; echo "ARTIFACT_NAME_MISMATCH expected=$EXPECTED_NAME actual=$BASE"; exit 1;
}
echo 'R3.1.7_RUNTIME_SOURCE: PASS'
echo "sha256=$ACTUAL"
echo "artifact=$BASE"
