import os
os.environ['DATABASE_URL']='sqlite:////tmp/go_sprint4w_test.db'
from datetime import datetime,timezone
import pytest
from go_hotel.db.session import engine,SessionLocal
from go_hotel.db.models import *
from go_hotel.journey.recovery_forecast_portfolio_governance import recovery_forecast_portfolio_governance_service as svc

def now(): return datetime.now(timezone.utc)
def setup_function():
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine);seed()

def seed():
    with SessionLocal() as s:
        for mid,v in [('champ',1),('c1',2),('c2',3)]:
            s.add(JourneyRecoveryRiskForecastModelVersionRow(risk_forecast_model_version_id=mid,model_key='risk',version_no=v,environment='PROD',algorithm_key='x',parameters_json={},conservative_parameters_json={},minimum_samples=2,max_mae_points=10,max_brier_score=.25,max_false_positive_rate=.2,max_false_negative_rate=.2,max_capacity_drift_pct=10,requested_by='x',board_approver_one='a',board_approver_two='b',state='ACTIVE',created_at=now(),supplier_fact_unchanged=True))
        for tid,team,domain,h in [('tA','TEAM_A','IDENTITY',24),('tB','TEAM_B','CLOUD',24),('tC','TEAM_C','RELEASE',168)]:
            s.add(JourneyRecoveryForecastRemediationTargetRow(forecast_remediation_target_id=tid,environment='PROD',retraining_request_id='rr_'+tid,source_segment_assessment_id='seg_'+tid,champion_model_version_id='champ',team_key=team,risk_domain=domain,horizon_hours=h,baseline_mae=100,baseline_rmse=120,baseline_brier=.2,required_improvement_pct=15,created_at=now(),supplier_fact_unchanged=True))
        s.commit()

def add_good_evidence(model,target,improvement=25,maxreg=2):
    with SessionLocal() as s:
        s.add(JourneyRecoveryForecastRemediationAssessmentRow(forecast_remediation_assessment_id=f'a_{model}_{target}',environment='PROD',remediation_target_id=target,challenger_model_version_id=model,effectiveness_state='REMEDIATION_EFFECTIVE',target_improvement_pct=improvement,max_cross_segment_regression_pct=maxreg,reason_codes_json=[],promotion_eligible=True,evidence_json={},evaluated_at=now(),supplier_fact_unchanged=True))
        s.add(JourneyRecoveryForecastGeneralizationValidationRow(forecast_generalization_validation_id=f'g_{model}_{target}',environment='PROD',remediation_target_id=target,challenger_model_version_id=model,segment_key=f'ADJ|{target}',sample_count=5,baseline_mae=50,challenger_mae=49,regression_pct=-2,validation_state='PASS',reason_codes_json=[],evaluated_at=now(),supplier_fact_unchanged=True))
        s.add(JourneyRecoveryForecastHoldoutValidationRow(forecast_holdout_validation_id=f'h_{model}_{target}',environment='PROD',remediation_target_id=target,challenger_model_version_id=model,holdout_segment_key=f'HOLD|{target}',sample_count=5,baseline_mae=50,challenger_mae=49,regression_pct=-2,validation_state='PASS',reason_codes_json=[],evaluated_at=now(),supplier_fact_unchanged=True))
        s.commit()

def make_portfolio(protected=None):
    return svc.create_portfolio(['tA','tB'],{'tA':'MUST_FIX','tB':'MUST_FIX'},protected or [],'maker')

def test_portfolio_requires_multiple_segments():
    with pytest.raises(ValueError,match='AT_LEAST_TWO_TARGETS'):svc.create_portfolio(['tA'])

def test_unresolved_mutual_conflict_rejects_candidate():
    p=make_portfolio();svc.register_conflict(p['portfolio_id'],'tA','tB','MUTUALLY_CONFLICTING','OPEN',20)
    add_good_evidence('c1','tA');add_good_evidence('c1','tB')
    c=svc.register_candidate(p['portfolio_id'],'c1')
    a=svc.assess_candidate(c['candidate_id'])
    assert a['assessment_state']=='REJECTED_CONFLICT' and 'UNRESOLVED_MUTUAL_SEGMENT_CONFLICT' in a['reason_codes']

def test_must_fix_segment_cannot_be_hidden_by_global_candidate_score():
    p=make_portfolio();add_good_evidence('c1','tA')
    c=svc.register_candidate(p['portfolio_id'],'c1')
    a=svc.assess_candidate(c['candidate_id'])
    assert a['assessment_state']!='PORTFOLIO_PASS'
    assert any(x.startswith('4U_REMEDIATION_EVIDENCE_REQUIRED_tB') for x in a['reason_codes'])

def test_unified_candidate_passes_when_all_must_fix_and_4v_evidence_pass():
    p=make_portfolio();add_good_evidence('c1','tA',28);add_good_evidence('c1','tB',20)
    c=svc.register_candidate(p['portfolio_id'],'c1','UNIFIED')
    a=svc.assess_candidate(c['candidate_id'])
    assert a['assessment_state']=='PORTFOLIO_PASS' and a['must_fix_passed']==2

def test_protected_segment_regression_blocks_portfolio():
    p=make_portfolio(['PROTECTED|PAYMENTS']);add_good_evidence('c1','tA');add_good_evidence('c1','tB')
    with SessionLocal() as s:
        s.add(JourneyRecoveryForecastCrossSegmentRegressionRow(forecast_cross_segment_regression_id='reg1',environment='PROD',remediation_target_id='tA',challenger_model_version_id='c1',segment_key='PROTECTED|PAYMENTS',baseline_mae=20,challenger_mae=30,regression_pct=50,regression_state='REGRESSED',evaluated_at=now(),supplier_fact_unchanged=True));s.commit()
    c=svc.register_candidate(p['portfolio_id'],'c1');a=svc.assess_candidate(c['candidate_id'])
    assert a['assessment_state']!='PORTFOLIO_PASS' and 'PROTECTED_SEGMENT_REGRESSION_PROTECTED|PAYMENTS' in a['reason_codes']

def test_arbitration_selects_best_portfolio_safe_candidate():
    p=make_portfolio();
    for t in ['tA','tB']:
        add_good_evidence('c1',t,20,3);add_good_evidence('c2',t,30,1)
    c1=svc.register_candidate(p['portfolio_id'],'c1');c2=svc.register_candidate(p['portfolio_id'],'c2')
    svc.assess_candidate(c1['candidate_id']);svc.assess_candidate(c2['candidate_id'])
    ar=svc.arbitrate(p['portfolio_id'])
    assert ar['decision_state']=='PORTFOLIO_WINNER_SELECTED' and ar['winner_model_version_id']=='c2'
    assert any(x['model_version_id']=='c1' and x['state']=='KEEP_IN_SHADOW' for x in ar['rankings'])

def test_only_arbitration_winner_can_receive_portfolio_promotion_gate():
    p=make_portfolio();
    for t in ['tA','tB']:
        add_good_evidence('c1',t,20,3);add_good_evidence('c2',t,30,1)
    c1=svc.register_candidate(p['portfolio_id'],'c1');c2=svc.register_candidate(p['portfolio_id'],'c2')
    svc.assess_candidate(c1['candidate_id']);svc.assess_candidate(c2['candidate_id']);svc.arbitrate(p['portfolio_id'])
    g1=svc.create_promotion_gate(p['portfolio_id'],c1['candidate_id']);g2=svc.create_promotion_gate(p['portfolio_id'],c2['candidate_id'])
    assert not g1['promotion_eligible'] and 'PORTFOLIO_WINNER_REQUIRED' in g1['reason_codes']
    assert g2['promotion_eligible'] and g2['gate_state']=='PASS'

def test_hard_promotion_guard_requires_4w_gate_and_preserves_supplier_fact():
    p=make_portfolio();add_good_evidence('c1','tA');add_good_evidence('c1','tB')
    c=svc.register_candidate(p['portfolio_id'],'c1');svc.assess_candidate(c['candidate_id'])
    with SessionLocal() as s:
        with pytest.raises(ValueError,match='MULTI_SEGMENT_PORTFOLIO_PROMOTION_GATE_REQUIRED'):svc.assert_promotion_eligible_in_session(s,'PROD','c1')
    svc.arbitrate(p['portfolio_id']);g=svc.create_promotion_gate(p['portfolio_id'],c['candidate_id'],{'proof':'portfolio-safe'})
    with SessionLocal() as s: assert svc.assert_promotion_eligible_in_session(s,'PROD','c1') is True
    assert g['supplier_fact_unchanged'] is True
