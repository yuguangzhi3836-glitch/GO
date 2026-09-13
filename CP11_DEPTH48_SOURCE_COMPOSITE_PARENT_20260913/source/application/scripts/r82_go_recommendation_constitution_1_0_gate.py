#!/usr/bin/env python3
from pathlib import Path
import ast
ROOT=Path(__file__).resolve().parents[1]
SVC=ROOT/'src/go_hotel/judgment/service.py'
STD=ROOT/'src/go_hotel/judgment/good_hotel_standard.py'
MASTER=ROOT/'GO_RECOMMENDATION_CONSTITUTION_1_0_PARENT_CONTROLLED_UPDATE_20260829.md'
TEST=ROOT/'tests/test_sprint1p_judgment_runtime.py'
DIMS=(
 'WORK_OF_HOSPITALITY','IRREPLACEABILITY','SENSE_OF_PLACE',
 'AESTHETIC_JUDGMENT','EMOTIONAL_RESONANCE','WORTH_THE_JOURNEY')
def block(m):
 print('R8.2_GO_RECOMMENDATION_CONSTITUTION_1_0_GATE: BLOCK'); print(m); raise SystemExit(1)
for p in (SVC,STD,MASTER,TEST):
 if not p.is_file(): block('MISSING:'+p.relative_to(ROOT).as_posix())
for p in (SVC,STD,TEST):
 try: ast.parse(p.read_text(encoding='utf-8'))
 except Exception as e: block('PYTHON_PARSE:'+p.name+':'+str(e))
svc=SVC.read_text(encoding='utf-8'); std=STD.read_text(encoding='utf-8'); master=MASTER.read_text(encoding='utf-8'); test=TEST.read_text(encoding='utf-8')
checks={
 'rule_version':'GO_RECOMMENDATION_CONSTITUTION_1.0' in svc,
 'all_six_dimensions':all(d in svc and d in std for d in DIMS),
 'high_score_no_auto_recommend':'RECOMMENDATION_ASSESSMENT_REQUIRED' in svc and 'GO_INDEPENDENT_JUDGMENT_PASSED' not in svc,
 'worth_journey_hard_gate':'WORTH_THE_JOURNEY_EXPLICIT_YES_REQUIRED' in svc,
 'commercial_attestation':'COMMERCIAL_INDEPENDENCE_ATTESTATION_REQUIRED' in svc,
 'recursive_commercial_firewall':'_assert_no_forbidden_features' in svc,
 'no_city_quota':'city_quota_forbidden' in std,
 'no_fixed_ratio':'fixed_recommendation_ratio_forbidden' in std,
 'master_independent_state_machines':'independent state machines' in master,
 'master_non_weighted':'not a weighted mechanical formula' in master,
 'test_high_score_no_auto':'test_high_go_score_does_not_auto_create_recommendation' in test,
 'test_six_dimension_publish':'test_constitution_assessment_can_publish_go_recommended_without_score_threshold_rule' in test,
 'test_worth_yes':'test_worth_the_journey_yes_is_mandatory_for_recommendation' in test,
 'test_nested_commercial':'test_nested_commercial_field_is_rejected_from_recommendation_assessment' in test,
}
for k,v in checks.items(): print(f'{k}={"PASS" if v else "FAIL"}')
bad=[k for k,v in checks.items() if not v]
if bad: block(','.join(bad))
print('R8.2_GO_RECOMMENDATION_CONSTITUTION_1_0_GATE: PASS')
