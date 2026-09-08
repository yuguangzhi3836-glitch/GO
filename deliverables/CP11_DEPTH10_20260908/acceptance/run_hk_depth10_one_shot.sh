#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$(pwd)}"
EVIDENCE_DIR="${GO_DEPTH10_EVIDENCE_DIR:-$ROOT/evidence/depth10_hk_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$EVIDENCE_DIR"

export PYTHONPATH="$ROOT/deliverables/CP11_DEPTH10_20260908/src:${PYTHONPATH:-}"
unset GO_HOTEL_ALLOW_LEGACY_REDIS_REGIONAL_WORKER || true

run_gate() {
  local name="$1"
  shift
  set +e
  "$@" >"$EVIDENCE_DIR/${name}.out" 2>"$EVIDENCE_DIR/${name}.err"
  local rc=$?
  set -e
  printf '%s\n' "$rc" >"$EVIDENCE_DIR/${name}.exit_code"
  if [ "$rc" -ne 0 ]; then
    echo "${name}=HOLD"
    echo "EVIDENCE_DIR=$EVIDENCE_DIR"
    exit "$rc"
  fi
  echo "${name}=PASS"
}

python3 - <<'PY' >"$EVIDENCE_DIR/production_authorities.json"
import json
from go_hotel.services.production_bindings import production_authorities
value = production_authorities()
print(json.dumps(value, ensure_ascii=False, indent=2))
if value.get("regional_queue") != "POSTGRES_DURABLE_LEASE_ACK": raise SystemExit(10)
if value.get("media_metadata") != "POSTGRES_DURABLE_MEDIA_LEDGER": raise SystemExit(11)
if value.get("media_local_json_authority") is not False: raise SystemExit(12)
if value.get("release_safe") is not True: raise SystemExit(13)
PY

echo "production_authority=PASS"

run_gate legacy_guard \
  python3 "$ROOT/deliverables/CP11_DEPTH10_20260908/acceptance/release_static_legacy_guard.py" \
  "$ROOT/deliverables/CP11_DEPTH10_20260908/src"

run_gate postgres_crash_recovery \
  python3 "$ROOT/deliverables/CP11_DEPTH10_20260908/acceptance/run_postgres_crash_recovery.py"

run_gate hyatt_10_cohort \
  python3 "$ROOT/deliverables/CP11_DEPTH10_20260908/acceptance/run_hyatt_10_real_e2e.py"

python3 - <<'PY' >"$EVIDENCE_DIR/gate_summary.json"
import json, os
print(json.dumps({
  "POSTGRES_CRASH_RECOVERY_GATE":"PASS",
  "HYATT_10_COHORT_FREEZE_AND_ENQUEUE":"PASS",
  "HYATT_10_WORKER_DRAIN":"HOLD",
  "HYATT_10_BROWSER_GATE":"HOLD",
  "HOTEL_REPLICATION_GATE":"HOLD",
  "FINAL_RELEASE_GATE":"HOLD"
}, indent=2))
PY

echo "HK_DEPTH10_PRE_DRAIN_GATES=PASS"
echo "HYATT_10_WORKER_DRAIN=HOLD"
echo "HYATT_10_BROWSER_GATE=HOLD"
echo "EVIDENCE_DIR=$EVIDENCE_DIR"
