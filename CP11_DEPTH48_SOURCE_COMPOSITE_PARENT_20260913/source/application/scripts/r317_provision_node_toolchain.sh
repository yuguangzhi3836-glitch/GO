#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SRC="$ROOT/gate_toolchain/NODE_SOURCE.json"
TARGET="$ROOT/gate_toolchain/node"
WORK=${R317_NODE_WORKDIR:-"$ROOT/.r317_node_build"}
TARGET_GLIBC='2.35'
fail(){ echo 'R3.1.7_NODE_TOOLCHAIN: BLOCK'; echo "$1"; exit 1; }
for c in curl tar sha256sum readelf python3 uname find sort awk sed grep; do command -v "$c" >/dev/null 2>&1 || fail "$c missing"; done
[ "$(uname -m)" = x86_64 ] || fail "architecture must be x86_64, got $(uname -m)"
[ -f "$SRC" ] || fail 'NODE_SOURCE.json missing'
eval "$(python3 - "$SRC" <<'PY'
import json,shlex,sys
j=json.load(open(sys.argv[1]))
for k,v in {
 'NODE_VERSION':j['version'],'NODE_ARTIFACT':j['artifact_name'],'NODE_URL':j['upstream_url'],
 'NODE_SHA':j['expected_sha256'],'NODE_PLATFORM':j['platform']}.items(): print(f"{k}={shlex.quote(v)}")
PY
)"
[ "$NODE_VERSION" = 'v22.22.0' ] || fail "unexpected node version contract: $NODE_VERSION"
[ "$NODE_PLATFORM" = 'linux-x64' ] || fail "unexpected node platform contract: $NODE_PLATFORM"
rm -rf "$WORK" && mkdir -p "$WORK/download" "$WORK/extract"
echo '[node 1/6] download pinned official Node.js binary'
curl --fail --location --retry 3 --retry-delay 2 --output "$WORK/download/$NODE_ARTIFACT" "$NODE_URL"
ACTUAL=$(sha256sum "$WORK/download/$NODE_ARTIFACT" | awk '{print $1}')
echo "node_upstream_sha256=$ACTUAL"
[ "$ACTUAL" = "$NODE_SHA" ] || fail "Node artifact SHA mismatch expected=$NODE_SHA actual=$ACTUAL"
echo '[node 2/6] extract and verify version/platform'
tar -xJf "$WORK/download/$NODE_ARTIFACT" -C "$WORK/extract"
BASE="$WORK/extract/node-v22.22.0-linux-x64"
[ -x "$BASE/bin/node" ] || fail 'node binary missing after extraction'
VER=$($BASE/bin/node --version 2>&1) || fail 'node cannot start'
[ "$VER" = "$NODE_VERSION" ] || fail "node version mismatch: $VER"
readelf -h "$BASE/bin/node" | grep -q 'Advanced Micro Devices X86-64' || fail 'Node ELF is not x86-64'
echo '[node 3/6] GLIBC compatibility scan'
MAX=0.0
COUNT=0
for f in "$BASE/bin/node" $(find "$BASE" -type f \( -name '*.so' -o -name '*.so.*' \) -print | sort); do
  [ -f "$f" ] || continue
  COUNT=$((COUNT+1))
  for v in $(readelf --version-info "$f" 2>/dev/null | grep -o 'GLIBC_[0-9][0-9]*\.[0-9][0-9]*' | sed 's/GLIBC_//' || true); do
    MAX=$(printf '%s\n%s\n' "$MAX" "$v" | sort -V | tail -1)
  done
done
echo "NODE_GLIBC_SCAN max_required=$MAX scanned=$COUNT target<=$TARGET_GLIBC"
HIGHEST=$(printf '%s\n%s\n' "$TARGET_GLIBC" "$MAX" | sort -V | tail -1)
[ "$HIGHEST" = "$TARGET_GLIBC" ] || fail "Node GLIBC requirement $MAX exceeds $TARGET_GLIBC"
echo '[node 4/6] install sealed Node tree'
rm -rf "$TARGET"
mkdir -p "$TARGET"
cp -a "$BASE/." "$TARGET/"
echo '[node 5/6] compute immutable tree manifest'
TREE_SHA=$(python3 - "$TARGET" <<'PY'
import hashlib,pathlib,sys
root=pathlib.Path(sys.argv[1]); h=hashlib.sha256()
for p in sorted(x for x in root.rglob('*') if x.is_file()):
 rel=p.relative_to(root).as_posix().encode(); h.update(rel+b'\0'); h.update(hashlib.sha256(p.read_bytes()).digest())
print(h.hexdigest())
PY
)
cat > "$ROOT/gate_toolchain/NODE_MANIFEST.json" <<EOF2
{
  "toolchain_release": "R3.1.7-V7",
  "component": "node",
  "node_version": "$NODE_VERSION",
  "platform": "$NODE_PLATFORM",
  "target_os_contract": "Ubuntu 22.04",
  "target_glibc_max": "$TARGET_GLIBC",
  "max_required_glibc": "$MAX",
  "upstream_artifact": "$NODE_ARTIFACT",
  "upstream_sha256": "$ACTUAL",
  "node_tree_sha256": "$TREE_SHA"
}
EOF2
echo '[node 6/6] final executable smoke'
"$TARGET/bin/node" --check - <<'JS'
const x = 1;
JS
printf '%s\n' 'R3.1.7_NODE_TOOLCHAIN: PASS'
printf 'node=%s\nnode_tree_sha256=%s\nmax_required_glibc=%s\n' "$VER" "$TREE_SHA" "$MAX"
