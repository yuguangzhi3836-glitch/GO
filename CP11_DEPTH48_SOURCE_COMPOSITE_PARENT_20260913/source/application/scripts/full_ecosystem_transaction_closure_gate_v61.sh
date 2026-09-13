#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p verification/current_release
REPORT="verification/current_release/FULL_ECOSYSTEM_TRANSACTION_CLOSURE_GATE_V6.1.json"
python scripts/full_ecosystem_transaction_closure_gate_v61.py --mode contract --json-out "$REPORT"
echo "FULL_ECOSYSTEM_CONTRACT_CLOSURE_GATE: PASS"
set +e
python scripts/full_ecosystem_transaction_closure_gate_v61.py --mode production >/tmp/go_v61_full_ecosystem_production_gate.txt 2>&1
PROD=$?
set -e
if [ "$PROD" -eq 2 ]; then
  echo "FULL_ECOSYSTEM_PRODUCTION_GATE: BLOCKED_AS_DESIGNED"
else
  echo "FAIL: production gate must fail closed until external supplier/payment/refund evidence is configured (exit=$PROD)"
  cat /tmp/go_v61_full_ecosystem_production_gate.txt
  exit 1
fi
