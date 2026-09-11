#!/usr/bin/env bash
set -euo pipefail

destination="${1:?physical iOS destination required}"
candidate_sha="${2:?candidate sha required}"
output="${3:?output evidence path required}"

case "$destination" in
  *Simulator*) echo "APPLE_PHYSICAL_DEVICE_REQUIRED" >&2; exit 41 ;;
esac
case "$destination" in
  *platform=iOS*) ;;
  *) echo "APPLE_PHYSICAL_IOS_DESTINATION_REQUIRED" >&2; exit 42 ;;
esac

: "${GO_IOS_DEVICE_UDID:?GO_IOS_DEVICE_UDID required on the device runner}"
: "${GO_IOS_DEVICE_MODEL:?GO_IOS_DEVICE_MODEL required on the device runner}"
: "${GO_IOS_VERSION:?GO_IOS_VERSION required on the device runner}"
: "${GO_APP_INTENTS_DEVICE_SMOKE:?GO_APP_INTENTS_DEVICE_SMOKE executable required on the device runner}"

if [[ ! -x "$GO_APP_INTENTS_DEVICE_SMOKE" ]]; then
  echo "APPLE_DEVICE_SMOKE_EXECUTABLE_REQUIRED" >&2
  exit 43
fi

smoke_log="$(mktemp)"
"$GO_APP_INTENTS_DEVICE_SMOKE" "$destination" "$candidate_sha" | tee "$smoke_log"
grep -qx 'APP_INTENTS_SMOKE=PASS' "$smoke_log"
grep -qx 'TRANSACTION_LIFECYCLE_SMOKE=PASS' "$smoke_log"

xcode_version="$(xcodebuild -version | tr '\n' ' ' | sed 's/[[:space:]]*$//')"
udid_hash="$(printf '%s' "$GO_IOS_DEVICE_UDID" | shasum -a 256 | awk '{print $1}')"

python3 - "$candidate_sha" "$xcode_version" "$GO_IOS_DEVICE_MODEL" "$GO_IOS_VERSION" "$udid_hash" "$destination" "$output" <<'PY'
import hashlib, json, sys
sha,xcode,model,ios,udid,destination,out=sys.argv[1:]
data={
  'candidate_sha':sha,
  'xcode_version':xcode,
  'device_model':model,
  'ios_version':ios,
  'device_udid_sha256':udid,
  'destination':destination,
  'build_exit_code':0,
  'app_intents_smoke':'PASS',
  'transaction_lifecycle_smoke':'PASS',
  'evidence_sha256':'',
}
raw=(json.dumps(data,sort_keys=True,separators=(',',':'))+'\n').encode()
data['evidence_sha256']=hashlib.sha256(raw).hexdigest()
with open(out,'w',encoding='utf-8') as f:
    json.dump(data,f,indent=2,sort_keys=True); f.write('\n')
PY

echo 'APPLE_PHYSICAL_DEVICE_SMOKE_EVIDENCE=READY'
