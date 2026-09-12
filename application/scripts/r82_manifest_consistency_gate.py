#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
HEAD='0112_ti_p0_20260829'; COUNT=112; RID='R3.1.7-P0-REFERENCE10-NATIVE-V2-GO-RECOMMENDATION-1.0-FULL'
def block(m): print('R8.2_MANIFEST_CONSISTENCY_GATE: BLOCK'); print(m); raise SystemExit(1)
source=json.loads((ROOT/'gate_runtime/RUNTIME_SOURCE.json').read_text())
for name in ('CURRENT_RELEASE_MANIFEST.json','RELEASE_CANDIDATE_MANIFEST.json'):
 d=json.loads((ROOT/name).read_text()); r=d.get('release',{}); m=d.get('migration',{})
 checks={
  'release_id':r.get('release_id')==RID,
  'scope':r.get('scope')=='P0_TRAVEL_INTELLIGENCE_CLEAN_SLATE_PLUS_CONSUMER_REFERENCE10_NATIVE_V2_PLUS_GO_RECOMMENDATION_CONSTITUTION_1_0_FULL_SYSTEM',
  'candidate':r.get('deployment_status')=='CANDIDATE',
  'business_change':r.get('business_code_change') is True,
  'consumer_vi_change':r.get('consumer_vi_change') is True,
  'migration_no_new_write':r.get('rds_migration_change') is False,
  'head':m.get('single_head')==HEAD,
  'count':m.get('revision_count')==COUNT,
  'no_stamp':m.get('stamp_allowed') is False,
  'runtime_sha':r.get('runtime_contract',{}).get('sha256')==source.get('expected_sha256'),
  'recommendation_constitution':r.get('go_recommendation_constitution',{}).get('version')=='1.0' and r.get('go_recommendation_constitution',{}).get('go_score_auto_endorsement') is False,
 }
 bad=[k for k,v in checks.items() if not v]
 for k,v in checks.items(): print(f'{name}:{k}={"PASS" if v else "FAIL"}')
 if bad: block(name+':'+','.join(bad))
print('R8.2_MANIFEST_CONSISTENCY_GATE: PASS')
