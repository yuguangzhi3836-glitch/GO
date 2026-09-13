#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/gate_runtime/python/bin/python"
if [ -z "${GO_FIRECRAWL_API_KEY:-}" ]; then echo 'HOLD: GO_FIRECRAWL_API_KEY not present in secure runtime environment'; exit 2; fi
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_ROOT="${1:-$ROOT/deploy/evidence/aoluguya-one-click-2-0-$STAMP}"
mkdir -p "$EVIDENCE_ROOT/cache"
CAND="$EVIDENCE_ROOT/firecrawl_media_candidates.json"
DISC="$EVIDENCE_ROOT/firecrawl_discovery_evidence.json"
HARV="$EVIDENCE_ROOT/real_image_byte_harvest_evidence.json"
set +e
"$PY" scripts/aoluguya_firecrawl_media_discovery.py --out "$CAND" --evidence-out "$DISC" --target-total 160 --limit 20 | tee "$EVIDENCE_ROOT/discovery.stdout.log"
DISC_RC=${PIPESTATUS[0]}
set -e
"$PY" - "$DISC" "$DISC_RC" <<'PY'
import json,sys
d=json.load(open(sys.argv[1],encoding='utf-8'))
assert int(sys.argv[2])==0, 'DISCOVERY_EXIT_NONZERO'
assert d.get('target_candidate_capacity')==160, 'DISCOVERY_CAPACITY_NOT_160'
assert d.get('capacity_gate_pass') is True, 'DISCOVERY_CAPACITY_GATE_HOLD'
assert d.get('scene_budget_gate_pass') is True, 'DISCOVERY_SCENE_BUDGET_GATE_HOLD'
assert all(d.get('scene_budget_checks',{}).values()), 'DISCOVERY_SCENE_BUDGET_MISMATCH'
print('DISCOVERY_160_AND_SIX_SCENE_BUDGET_GATE=PASS')
PY
set +e
"$PY" scripts/aoluguya_real_media_harvest_gate.py --candidates "$CAND" --cache-dir "$EVIDENCE_ROOT/cache" --evidence-out "$HARV" --rights-owner 'AOLUGUYA Hotel' --owner-verified | tee "$EVIDENCE_ROOT/harvest.stdout.log"
RC=${PIPESTATUS[0]}
set -e
"$PY" - "$HARV" "$EVIDENCE_ROOT/FINAL_GATE.txt" "$RC" <<'PY'
import json,sys
p,out,rc=sys.argv[1],sys.argv[2],int(sys.argv[3])
d=json.load(open(p,encoding='utf-8')); g=d['golden_media_gate']
checks={
 'downloaded_ge_30': int(d.get('downloaded_count',0))>=30,
 'unique_publishable_media_ge_30': int(g.get('unique_publishable_media',0))>=30,
 'six_scene_complete': g.get('six_scene_complete') is True,
 'golden_media_gate_pass': g.get('golden_media_gate_pass') is True,
 'harvest_exit_zero': rc==0,
}
status='PASS' if all(checks.values()) else 'HOLD'
text='\n'.join([f'AOLUGUYA_REAL_MEDIA_FINAL_GATE={status}']+[f'{k}={"PASS" if v else "HOLD"}' for k,v in checks.items()]+[f'downloaded={d.get("downloaded_count",0)}',f'unique_publishable_media={g.get("unique_publishable_media",0)}',f'six_scene_complete={str(g.get("six_scene_complete")).lower()}',f'golden_media_gate_pass={str(g.get("golden_media_gate_pass")).lower()}'])+'\n'
open(out,'w',encoding='utf-8').write(text); print(text,end='')
raise SystemExit(0 if status=='PASS' else 2)
PY
sha256sum "$CAND" "$DISC" "$HARV" "$EVIDENCE_ROOT/FINAL_GATE.txt" > "$EVIDENCE_ROOT/SHA256SUMS.txt"
echo "EVIDENCE_ROOT=$EVIDENCE_ROOT"
