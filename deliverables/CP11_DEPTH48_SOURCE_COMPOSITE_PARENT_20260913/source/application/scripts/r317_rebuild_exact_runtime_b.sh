#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUTDIR=${R317_OUTDIR:-"$ROOT/dist_r317"}
WORK=${R317_WORKDIR:-"$ROOT/.r317_runtime_build"}
UPSTREAM_NAME='cpython-3.13.5+20250612-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz'
UPSTREAM_URL="${R317_UPSTREAM_URL:-https://github.com/astral-sh/python-build-standalone/releases/download/20250612/cpython-3.13.5%2B20250612-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz}"
FINAL_NAME='gate_runtime_python_cpython-3.13.5_ubuntu-22.04-x86_64_r3.1.7.tar.gz'
TARGET_GLIBC='2.35'
UPSTREAM_EXPECTED_SHA='5c63e7ffe47baff0a96a685c94fb5075612817741feb4e85ec3cc082c742b4f8'

fail(){ echo "R3.1.7_EXACT_RUNTIME_REBUILD: BLOCK"; echo "$1"; exit 1; }
command -v curl >/dev/null 2>&1 || fail 'curl missing'
command -v tar >/dev/null 2>&1 || fail 'tar missing'
command -v sha256sum >/dev/null 2>&1 || fail 'sha256sum missing'
if command -v readelf >/dev/null 2>&1; then :; else fail 'readelf missing (install binutils)'; fi
[ "$(uname -m)" = x86_64 ] || fail "architecture must be x86_64, got $(uname -m)"
[ -d "$ROOT/gate_runtime/wheelhouse" ] || fail 'wheelhouse missing'
[ -f "$ROOT/gate_runtime/requirements.lock" ] || fail 'requirements.lock missing'
[ -f "$ROOT/gate_runtime/WHEELHOUSE_SHA256SUMS.txt" ] || fail 'wheelhouse checksum manifest missing'
mkdir -p "$OUTDIR"
rm -rf "$WORK" && mkdir -p "$WORK/upstream" "$WORK/runtime"

printf '%s\n' '[1/9] verify frozen wheelhouse'
(cd "$ROOT/gate_runtime/wheelhouse" && sha256sum -c ../WHEELHOUSE_SHA256SUMS.txt)

printf '%s\n' '[2/9] download pinned CPython 3.13.5 standalone asset'
curl --fail --location --retry 3 --retry-delay 2 --output "$WORK/$UPSTREAM_NAME" "$UPSTREAM_URL"
UPSTREAM_SHA=$(sha256sum "$WORK/$UPSTREAM_NAME" | awk '{print $1}')
printf 'upstream_sha256=%s\n' "$UPSTREAM_SHA"
[ "$UPSTREAM_SHA" = "$UPSTREAM_EXPECTED_SHA" ] || fail "upstream SHA mismatch: expected $UPSTREAM_EXPECTED_SHA got $UPSTREAM_SHA"

printf '%s\n' '[3/9] extract and verify upstream identity'
tar -xzf "$WORK/$UPSTREAM_NAME" -C "$WORK/upstream"
[ -x "$WORK/upstream/python/bin/python3" ] || fail 'upstream python/bin/python3 missing'
PY="$WORK/upstream/python/bin/python3"
VER=$($PY --version 2>&1) || fail 'upstream python cannot start'
[ "$VER" = 'Python 3.13.5' ] || fail "wrong Python version: $VER"
# The install_only_stripped asset does not contain PYTHON.json. Identity is therefore
# established fail-closed from the immutable upstream artifact name + pinned SHA-256,
# then independently checked from the executable runtime properties actually shipped.
$PY - <<'PY'
import platform, sys, sysconfig
assert sys.version_info[:3] == (3, 13, 5), sys.version
assert sys.platform == 'linux', sys.platform
assert platform.machine() == 'x86_64', platform.machine()
plat = sysconfig.get_platform()
assert plat == 'linux-x86_64', plat
soabi = sysconfig.get_config_var('SOABI') or ''
assert soabi.startswith('cpython-313-x86_64-linux-gnu'), soabi
print('runtime identity: Python 3.13.5 / linux-x86_64 / GNU SOABI: PASS')
print('sysconfig_platform=', plat)
print('SOABI=', soabi)
PY
readelf -h "$PY" | grep -q 'Advanced Micro Devices X86-64' || fail 'ELF machine is not x86-64'
printf '%s\n' 'ELF machine x86-64: PASS'

scan_tree() {
  base=$1
  max=0.0
  count=0
  for f in "$base/bin/python3" $(find "$base" -type f \( -name '*.so' -o -name '*.so.*' \) -print | sort); do
    [ -f "$f" ] || continue
    count=$((count+1))
    for v in $(readelf --version-info "$f" 2>/dev/null | grep -o 'GLIBC_[0-9][0-9]*\.[0-9][0-9]*' | sed 's/GLIBC_//' || true); do
      max=$(printf '%s\n%s\n' "$max" "$v" | sort -V | tail -1)
    done
  done
  printf 'GLIBC_SCAN base=%s max_required=%s scanned=%s\n' "$base" "$max" "$count"
  highest=$(printf '%s\n%s\n' "$TARGET_GLIBC" "$max" | sort -V | tail -1)
  [ "$highest" = "$TARGET_GLIBC" ] || fail "GLIBC requirement $max exceeds $TARGET_GLIBC"
}

printf '%s\n' '[4/9] pre-install GLIBC compatibility scan'
scan_tree "$WORK/upstream/python"

printf '%s\n' '[5/9] install frozen 29-wheel dependency closure offline'
cp -a "$WORK/upstream/python/." "$WORK/runtime/"
"$WORK/runtime/bin/python3" -m pip install --no-index --find-links "$ROOT/gate_runtime/wheelhouse" --requirement "$ROOT/gate_runtime/requirements.lock"

printf '%s\n' '[6/9] post-install GLIBC compatibility and import smoke'
scan_tree "$WORK/runtime"
"$WORK/runtime/bin/python3" - <<'PY'
import fastapi, sqlalchemy, pytest, pydantic, starlette, greenlet, pydantic_settings, dotenv, httpx, httpcore, h11, certifi, cryptography, PIL, jwt, pytest_asyncio, cffi
assert fastapi.__version__=='0.128.2'
assert sqlalchemy.__version__=='2.0.50'
assert pytest.__version__=='9.0.2'
assert pydantic_settings.__version__=='2.14.1'
assert httpx.__version__=='0.28.1'
assert cryptography.__version__=='46.0.4'
assert PIL.__version__=='12.3.0'
assert jwt.__version__=='2.13.0'
assert pytest_asyncio.__version__=='1.3.0'
print('R3.1.7 gate dependency import smoke: PASS (29-wheel complete offline test closure)')
PY

printf '%s\n' '[7/9] create runtime manifest'
REQ_SHA=$(sha256sum "$ROOT/gate_runtime/requirements.lock" | awk '{print $1}')
WHEEL_SHA=$(sha256sum "$ROOT/gate_runtime/WHEELHOUSE_SHA256SUMS.txt" | awk '{print $1}')
TREE_SHA=$($WORK/runtime/bin/python3 - "$WORK/runtime" <<'PYTREE'
import hashlib,pathlib,sys
root=pathlib.Path(sys.argv[1]); h=hashlib.sha256()
for p in sorted(x for x in root.rglob('*') if x.is_file() and '__pycache__' not in x.parts and x.suffix not in {'.pyc','.pyo'}):
 rel=p.relative_to(root).as_posix().encode(); h.update(rel+b'\0'); h.update(hashlib.sha256(p.read_bytes()).digest())
print(h.hexdigest())
PYTREE
)
cat > "$WORK/runtime/RUNTIME_MANIFEST.json" <<EOF
{
  "runtime_release": "R3.1.7",
  "python_version": "3.13.5",
  "platform": "linux-x86_64",
  "target_os_contract": "Ubuntu 22.04",
  "target_glibc_max": "2.35",
  "upstream_artifact": "$UPSTREAM_NAME",
  "upstream_url": "$UPSTREAM_URL",
  "upstream_sha256": "$UPSTREAM_SHA",
  "requirements_lock_sha256": "$REQ_SHA",
  "wheelhouse_checksums_sha256": "$WHEEL_SHA",
  "runtime_tree_sha256": "$TREE_SHA"
}
EOF

printf '%s\n' '[8/9] pack exact R3.1.7 runtime and freeze its real SHA'
rm -f "$OUTDIR/$FINAL_NAME" "$OUTDIR/$FINAL_NAME.sha256"
mkdir -p "$WORK/package/python"
rm -rf "$WORK/package/python"
mkdir -p "$WORK/package/python"
cp -a "$WORK/runtime/." "$WORK/package/python/"
tar -C "$WORK/package" -czf "$OUTDIR/$FINAL_NAME" python
FINAL_SHA=$(sha256sum "$OUTDIR/$FINAL_NAME" | awk '{print $1}')
printf '%s  %s\n' "$FINAL_SHA" "$FINAL_NAME" > "$OUTDIR/$FINAL_NAME.sha256"
printf 'exact_runtime_sha256=%s\n' "$FINAL_SHA"

printf '%s\n' '[9/9] update PRE-SEAL runtime source contract to the newly manufactured exact bytes'
"$ROOT/gate_runtime/python/bin/python3" -V >/dev/null 2>&1 || true
python3 - "$ROOT" "$FINAL_SHA" "$FINAL_NAME" "$UPSTREAM_SHA" <<'PY'
import json,pathlib,sys,re
root=pathlib.Path(sys.argv[1]); sha=sys.argv[2]; name=sys.argv[3]; upstream_sha=sys.argv[4]
p=root/'gate_runtime/RUNTIME_SOURCE.json'
d=json.loads(p.read_text())
d.update({
 'artifact_name':name,
 'expected_sha256':sha,
 'source_status':'REBUILT_EXACT_RUNTIME_FROZEN',
 'upstream_sha256':upstream_sha,
 'note':'R3.1.7 B-route exact runtime rebuilt from pinned CPython 3.13.5 standalone + frozen 29-wheel closure; this SHA is derived from the finished artifact bytes.'
})
p.write_text(json.dumps(d,indent=2,sort_keys=True)+'\n')
vp=root/'scripts/r317_verify_runtime_source.sh'
s=vp.read_text()
s=re.sub(r"EXPECTED='[0-9a-f]{64}'", f"EXPECTED='{sha}'", s)
s=re.sub(r"\[ \"\$BASE\" = '[^']+' \]", f"[ \"$BASE\" = '{name}' ]", s)
vp.write_text(s)
# RUNTIME_SOURCE.json is the single SHA source of truth. Synchronize machine-readable release manifests to the exact artifact.
for fn in ('CURRENT_RELEASE_MANIFEST.json','RELEASE_CANDIDATE_MANIFEST.json'):
    mp=root/fn
    m=json.loads(mp.read_text())
    rtc=m.setdefault('release',{}).setdefault('runtime_contract',{})
    rtc['artifact_name']=name
    rtc['sha256']=sha
    rtc['python_version']='3.13.5'
    rtc['target_glibc_max']='2.35'
    mp.write_text(json.dumps(m,indent=2,sort_keys=True)+'\n')
# Keep current human-readable control surfaces aligned; historical evidence files are not rewritten.
old='a11b7c35e35edde640c285cdf07daf7836755d05f712544b926290ad80e775c8'
for fn in ('CURRENT_CONTROL_VERSION.md','CURRENT_RELEASE_MANIFEST.md','CURRENT_RELEASE_MANIFEST_R8.2.md','RELEASE_CANDIDATE_MANIFEST.md'):
    hp=root/fn
    if hp.exists():
        t=hp.read_text(encoding='utf-8').replace(old,sha)
        hp.write_text(t,encoding='utf-8')
PY

printf '%s\n' 'R3.1.7_EXACT_RUNTIME_REBUILD: PASS'
printf 'artifact=%s\nsha256=%s\n' "$OUTDIR/$FINAL_NAME" "$FINAL_SHA"
printf '%s\n' 'NEXT: regenerate source checksum, run manifest/debt gates, then execute scripts/r317_one_shot_seal.sh with this exact tarball.'
