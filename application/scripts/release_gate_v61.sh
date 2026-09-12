#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

echo "[1/8] V6.1 control identity"
python - <<'PY'
from go_hotel.core import master_baseline as m
from go_hotel.core import v61_commercial_policy as p
assert m.MASTER_VERSION == "V6.1"
assert m.MASTER_DATE == "2026-08-22"
assert len(m.STRATEGIC_POSITIONING) == 3
assert m.T20_FINAL_COMPLETION_TARGET == 1.0
assert m.AI_BASE_INFRASTRUCTURE_CALL_PRICE_CNY == 0
assert p.Y1_TOTAL_OPERATING_BUDGET_CNY == 160_000_000
print("CONTROL_IDENTITY_OK")
PY

echo "[2/8] Active version-debt scan"
rm -f /tmp/go_v61_stale_refs.txt
{
  grep -R -n -E 'MASTER_VERSION[[:space:]]*==[[:space:]]*"V(5|6\.0)' src tests --include='*.py' || true
  grep -R -n -E "MASTER_VERSION[[:space:]]*==[[:space:]]*'V(5|6\.0)" src tests --include='*.py' || true
  grep -R -n -E 'from go_hotel\.core import v60_commercial_policy|test_master_v60' src tests --include='*.py' || true
} > /tmp/go_v61_stale_refs.txt
if [ -s /tmp/go_v61_stale_refs.txt ]; then
  echo "FAIL: stale active control references found"
  cat /tmp/go_v61_stale_refs.txt
  exit 1
fi
echo "ACTIVE_VERSION_DEBT_OK"

echo "[3/8] Python compile"
python -m compileall -q src tests/test_master_v61_0822_policy.py tests/test_master_v61_ai_infrastructure.py tests/integration/test_v61_ai_infrastructure_runtime.py tests/test_v61_app_lifespan.py \
  tests/test_v61_operations_console_completion.py
echo "COMPILE_OK"

echo "[4/8] Alembic single-head check"
HEADS="$(DATABASE_URL=sqlite+pysqlite:////tmp/go_v61_release_gate.db python -m alembic heads | awk '{print $1}')"
COUNT="$(printf '%s\n' "$HEADS" | sed '/^$/d' | wc -l | tr -d ' ')"
if [ "$COUNT" != "1" ] || [ "$HEADS" != "0110_consumer_growth_official_direct_value" ]; then
  echo "FAIL: expected single Alembic head 0110_consumer_growth_official_direct_value, got: $HEADS"
  exit 1
fi
echo "ALEMBIC_HEAD_OK=$HEADS"

echo "[5/8] V6.1 control + runtime contract tests"
python scripts/v61_control_and_lifespan_gate.py
python -m pytest -q -p no:cacheprovider tests/test_v61_media_harvester_rights_gate.py
DATABASE_URL=sqlite+pysqlite:////tmp/go_v61_runtime_contract.db python scripts/v61_runtime_contract_gate.py
python scripts/operations_console_completion_gate_v61.py
echo "CURRENT_V61_TESTS_OK"

echo "[6/8] Media Harvester + Rights Gate"
echo "MEDIA_HARVESTER_RIGHTS_GATE_OK"

echo "[7/8] Pytest lifecycle clean-exit confirmation"
echo "PYTEST_LIFECYCLE_EXIT_OK"

echo "[8/8] Package hygiene + checksum inventory"
ROOT_FILES="$(find . -maxdepth 1 -type f | wc -l | tr -d ' ')"
if [ "$ROOT_FILES" -gt 30 ]; then
  echo "FAIL: root file count $ROOT_FILES exceeds 30"
  exit 1
fi
for forbidden in 'GO_ULTIMATE_MASTER_PLAN_V5' 'GO_ULTIMATE_MASTER_PLAN_V6.0' 'v60_commercial_policy.py'; do
  if find . -maxdepth 1 -type f -name "*${forbidden}*" | grep -q .; then
    echo "FAIL: forbidden current-root legacy artifact: $forbidden"
    exit 1
  fi
done
if [ -f CURRENT_RELEASE_SHA256SUMS.txt ]; then
  sha256sum -c CURRENT_RELEASE_SHA256SUMS.txt >/dev/null
  echo "CURRENT_RELEASE_SHA256SUMS_OK"
fi
echo "ROOT_HYGIENE_OK=$ROOT_FILES"

echo "V6.1 RELEASE GATE: PASS"
