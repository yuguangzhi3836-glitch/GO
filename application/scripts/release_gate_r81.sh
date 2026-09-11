#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
python scripts/r8_staging_static_gate.py
python -m compileall -q src
node --check frontend/consumer/app.js
node --check frontend/shared/app.js
node --check frontend/admin/config.js
node --check frontend/supplier/config.js
python scripts/operations_console_completion_gate_v61.py
python scripts/r8_contract_gate.py
# R8.1 control-debt cleanup gate
python scripts/r81_control_debt_gate.py
python scripts/r81_commercial_fail_closed_gate.py
echo "R8.1 RELEASE GATE: PASS"
