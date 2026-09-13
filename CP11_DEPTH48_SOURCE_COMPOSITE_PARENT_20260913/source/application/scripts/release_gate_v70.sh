#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

RELEASE_ID="GO-V7.0-PARALLEL-WAVE07-FRG02-20260831"
PARENT_RELEASE_ID="GO-V7.0-PARALLEL-WAVE07-20260831"
PARENT_ZIP_SHA="638d27279c6d06063a4ae9a725a7c2a172b9874e183239388faf01a061efee70"
PARENT_SOURCE_TREE_SHA="7505db171b0558a3e5fe475988bcf67a1b0f7b139ba65b50e38ce7b75a248888"
SOURCE_HEAD="0114_ext_truth_incident_hard"
STAGING_PREDEPLOY_HEAD="0111_test_account_expiry"

if [ -z "${GO_RELEASE_CANDIDATE_ZIP:-}" ] || [ -z "${GO_RELEASE_CANDIDATE_SHA256:-}" ]; then
  echo "FAIL: exact candidate ZIP path and SHA must be supplied via GO_RELEASE_CANDIDATE_ZIP and GO_RELEASE_CANDIDATE_SHA256"; exit 1
fi
if [ ! -f "$GO_RELEASE_CANDIDATE_ZIP" ]; then echo "FAIL: candidate ZIP missing"; exit 1; fi
ACTUAL_CANDIDATE_SHA="$(sha256sum "$GO_RELEASE_CANDIDATE_ZIP" | awk '{print $1}')"
if [ "$ACTUAL_CANDIDATE_SHA" != "$GO_RELEASE_CANDIDATE_SHA256" ]; then
  echo "FAIL: candidate ZIP SHA mismatch expected=$GO_RELEASE_CANDIDATE_SHA256 actual=$ACTUAL_CANDIDATE_SHA"; exit 1
fi

echo "[1/8] Exact candidate ZIP identity"
echo "CANDIDATE_ZIP_SHA256_OK=$ACTUAL_CANDIDATE_SHA"

echo "[2/8] V7.0 controlling master identity"
python - <<'PY'
from pathlib import Path
p=Path('CURRENT_CONTROL_VERSION.md').read_text(encoding='utf-8')
assert 'Unique controlling solution master:' in p
assert 'GO Ultimate Master Plan V7.0' in p
assert 'V6.1 / Constitutional Alignment references remain historical or runtime-lineage facts only' in p
for fn in ('GO_ULTIMATE_MASTER_PLAN_V7.0_2026-08-31_MASTER.pdf','GO_ULTIMATE_MASTER_PLAN_V7.0_2026-08-31_CONSTITUTIONAL_LEGAL_SYNC_MASTER.pdf'):
    assert Path(fn).is_file(), fn
print('V7_CONTROL_IDENTITY_OK')
PY

echo "[3/8] Wave 07 FRG02 release identity + migration truth separation"
python - <<'PY'
import json
from pathlib import Path
RID='GO-V7.0-PARALLEL-WAVE07-FRG02-20260831'; PRID='GO-V7.0-PARALLEL-WAVE07-20260831'
PSHA='638d27279c6d06063a4ae9a725a7c2a172b9874e183239388faf01a061efee70'
PST='7505db171b0558a3e5fe475988bcf67a1b0f7b139ba65b50e38ce7b75a248888'
for fn in ('CURRENT_RELEASE_MANIFEST.json','RELEASE_CANDIDATE_MANIFEST.json'):
    d=json.loads(Path(fn).read_text(encoding='utf-8')); w=d['wave07_frg02_release_control']; m=d['migration']
    assert w['release_id']==RID; assert w['parent_release_id']==PRID
    assert w['immutable_parent_zip_sha256']==PSHA; assert w['immutable_parent_source_tree_sha256']==PST
    assert w['deployment_status']=='NOT_DEPLOYED'
    assert m['source_candidate']['revision_count']==114
    assert m['source_candidate']['single_head']=='0114_ext_truth_incident_hard'
    assert m['source_candidate']['down_revision']=='0113_ext_truth_ops_20260901'
    assert m['hong_kong_staging_confirmed']['current_head']=='0111_test_account_expiry'
    assert m['hong_kong_staging_confirmed']['row_count']==1
    assert m['deployment_preflight_policy']['do_not_claim_0114_applied_before_staging_execution'] is True
    assert m['deployment_preflight_policy']['stamp_allowed'] is False
    assert m['deployment_preflight_policy']['reset_allowed'] is False
print('WAVE07_RELEASE_IDENTITY_MIGRATION_TRUTH_OK')
PY

echo "[4/8] Alembic source single-head lineage"
HEADS="$(DATABASE_URL=sqlite+pysqlite:////tmp/go_v70_release_gate.db python -m alembic heads | awk '{print $1}')"
COUNT="$(printf '%s\n' "$HEADS" | sed '/^$/d' | wc -l | tr -d ' ')"
if [ "$COUNT" != "1" ] || [ "$HEADS" != "$SOURCE_HEAD" ]; then echo "FAIL: expected single source head $SOURCE_HEAD, got: $HEADS"; exit 1; fi
python - <<'PY'
from pathlib import Path
p=Path('alembic/versions/0114_ext_truth_incident_hard.py').read_text(encoding='utf-8')
assert 'revision = "0114_ext_truth_incident_hard"' in p
assert 'down_revision = "0113_ext_truth_ops_20260901"' in p
p13=Path('alembic/versions/0113_ext_truth_ops_20260901.py').read_text(encoding='utf-8')
assert 'revision = "0113_ext_truth_ops_20260901"' in p13
assert 'down_revision = "0112_ti_p0_20260829"' in p13
print('ALEMBIC_SOURCE_LINEAGE_OK')
PY

echo "[5/8] No stamp/reset + deployment reality fail-closed"
if find scripts deploy -type f \( -name '*.sh' -o -name '*.bash' \) ! -name 'run_postgres_tests.sh' -print0 2>/dev/null | xargs -0 grep -n -E '(^|[;&|])[[:space:]]*alembic[[:space:]]+stamp([[:space:]]|$)|(^|[;&|])[[:space:]]*alembic[[:space:]]+downgrade([[:space:]]|$)' 2>/dev/null >/tmp/go_v70_forbidden_release_ops.txt; then
  if [ -s /tmp/go_v70_forbidden_release_ops.txt ]; then echo "FAIL: executable stamp/downgrade operation found"; cat /tmp/go_v70_forbidden_release_ops.txt; exit 1; fi
fi
python - <<'PY'
from pathlib import Path
m=Path('CURRENT_RELEASE_MANIFEST.md').read_text(encoding='utf-8')
assert 'Source candidate migration head: `0114_ext_truth_incident_hard`' in m
assert 'Confirmed Hong Kong Staging DB fact before Wave 07 deployment: `0111_test_account_expiry`' in m
assert 'Deployment status: `NOT_DEPLOYED`' in m
print('DEPLOYMENT_REALITY_OK')
PY

echo "[6/8] V7 governance gates"
python scripts/check_v7_ai_org_build01.py
python scripts/check_v7_ai_org_build01_1.py
python scripts/r82_go_recommendation_constitution_1_0_gate.py

echo "[7/8] Release-focused tests"
python -m pytest -q -p no:cacheprovider tests/test_wave03_c07_c09_authority_contract.py tests/test_sprint3r_release_governance.py tests/test_outbox_resilience.py tests/test_reconciliation.py tests/test_saga_recovery.py

echo "[8/8] Wave 07 FRG02 source-tree binding"
python scripts/v70_source_tree_binding.py --verify

echo "V7.0 WAVE07 FRG02 FULL RELEASE GATE: PASS"
