import os
os.environ['DATABASE_URL']='sqlite:////tmp/go_sprint4x_test.db'
from datetime import datetime,timezone
import pytest
from sqlalchemy import select
from go_hotel.db.session import engine,SessionLocal
from go_hotel.db.models import *
from go_hotel.journey.recovery_forecast_champion_governance import recovery_forecast_champion_governance_service as svc

def now(): return datetime.now(timezone.utc)
def setup_function(): Base.metadata.drop_all(engine);Base.metadata.create_all(engine);seed()

def seed():
    with SessionLocal() as s:
        for mid,v in [('champ',1),('cand',2),('weak',3)]:
            s.add(JourneyRecoveryRiskForecastModelVersionRow(risk_forecast_model_version_id=mid,model_key='risk',version_no=v,environment='PROD',algorithm_key='x',parameters_json={},conservative_parameters_json={},minimum_samples=2,max_mae_points=10,max_brier_score=.25,max_false_positive_rate=.2,max_false_negative_rate=.2,max_capacity_drift_pct=10,requested_by='x',board_approver_one='a',board_approver_two='b',state='ACTIVE',created_at=now(),supplier_fact_unchanged=True))
        s.add(JourneyRecoveryForecastRemediationPortfolioRow(forecast_remediation_portfolio_id='pf',environment='PROD',champion_model_version_id='champ',target_ids_json=['tA','tB'],objectives_json=[{'target_id':'tA','role':'MUST_FIX'},{'target_id':'tB','role':'MUST_FIX'}],protected_segment_keys_json=['PAYMENTS'],portfolio_state='OPEN',created_by='x',created_at=now(),supplier_fact_unchanged=True))
        for cid,mid in [('pc','cand'),('pw','weak')]:
            s.add(JourneyRecoveryForecastPortfolioCandidateRow(forecast_portfolio_candidate_id=cid,environment='PROD',portfolio_id='pf',challenger_model_version_id=mid,strategy='UNIFIED',covered_target_ids_json=['tA','tB'],candidate_state='REGISTERED',registered_by='x',created_at=now(),supplier_fact_unchanged=True))
        s.add(JourneyRecoveryForecastCandidateArbitrationRow(forecast_candidate_arbitration_id='arb',environment='PROD',portfolio_id='pf',winner_candidate_id='pc',winner_model_version_id='cand',decision_state='PORTFOLIO_WINNER_SELECTED',rankings_json=[],reason_codes_json=[],evidence_json={},decided_at=now(),supplier_fact_unchanged=True))
        s.add(JourneyRecoveryForecastPortfolioPromotionGateRow(forecast_portfolio_promotion_gate_id='gate',environment='PROD',portfolio_id='pf',portfolio_candidate_id='pc',challenger_model_version_id='cand',arbitration_id='arb',gate_state='PASS',promotion_eligible=True,reason_codes_json=[],evidence_json={},evaluated_at=now(),supplier_fact_unchanged=True))
        s.commit()

def champion(): return svc.register_champion('pf','champ',None,'maker')
def open_good_challenge():
    c=champion(); return c,svc.open_challenge(c['champion_state_id'],'pc','maker')
def superior(challenge_id): return svc.compare_candidate(challenge_id,80,90,True,True,True,True,{'proof':'same-objectives'},'assessor')

def seed_4r(canary=10):
    with SessionLocal() as s:
        for mid,key,bid in [('champ','dep-champ','bchamp'),('cand','dep-cand','bcand')]:
            s.add(JourneyRecoveryForecastArtifactDeploymentBindingRow(forecast_artifact_deployment_binding_id=bid,environment='PROD',model_version_id=mid,forecast_model_artifact_id='art-'+mid,forecast_artifact_promotion_binding_id='pb-'+mid,deployment_key=key,expected_artifact_digest='d'*64,expected_build_hash='b'*64,binding_hash=('c' if mid=='champ' else 'e')*64,state='ACTIVE',bound_by='x',bound_at=now(),supplier_fact_unchanged=True))
        s.add(JourneyRecoveryForecastTrafficPolicyRow(forecast_traffic_policy_id='tp',environment='PROD',version_no=1,champion_deployment_key='dep-champ',candidate_deployment_key='dep-cand',allowed_canary_steps_json=[0,1,5,10,25,50,100],min_requests_per_step=1,max_error_rate=.1,max_timeout_rate=.1,max_p95_latency_ms=1000,max_shadow_divergence=.5,requested_by='x',approver_one='a',approver_two='b',state='ACTIVE',created_at=now(),supplier_fact_unchanged=True))
        s.add(JourneyRecoveryForecastTrafficAllocationRow(forecast_traffic_allocation_id='alloc',forecast_traffic_policy_id='tp',environment='PROD',champion_percentage=100-canary,canary_percentage=canary,allocation_version=1,state='ACTIVE',reason_codes_json=[],activated_at=now(),supplier_fact_unchanged=True));s.commit()

def seed_4v_proofs():
    with SessionLocal() as s:
        for tid in ['tA','tB']:
            s.add(JourneyRecoveryForecastPostPromotionProofRow(forecast_post_promotion_proof_id='proof-'+tid,environment='PROD',remediation_target_id=tid,promoted_model_version_id='cand',target_live_improvement_pct=20,max_adjacent_regression_pct=1,max_holdout_regression_pct=1,global_performance_state='PASS',proof_state='REMEDIATION_PROVEN_IN_PRODUCTION',rollback_required=False,reason_codes_json=[],evidence_json={},evaluated_at=now(),supplier_fact_unchanged=True));s.commit()

def test_continuity_distinguishes_degrading_no_longer_optimal_and_unsafe():
    c=champion(); assert svc.assess_continuity(c['champion_state_id'],82)['continuity_state']=='CHAMPION_DEGRADING'
    assert svc.assess_continuity(c['champion_state_id'],65)['continuity_state']=='CHAMPION_NO_LONGER_OPTIMAL'
    assert svc.assess_continuity(c['champion_state_id'],95,protected_segment_state='FAIL')['continuity_state']=='CHAMPION_UNSAFE'

def test_only_4w_portfolio_winner_can_open_challenge():
    c=champion()
    with pytest.raises(ValueError,match='4W_PORTFOLIO_WINNER_PROMOTION_GATE_REQUIRED'): svc.open_challenge(c['champion_state_id'],'pw')
    assert svc.open_challenge(c['champion_state_id'],'pc')['challenge_state']=='CHALLENGE_OPEN'

def test_multi_objective_safety_beats_single_score_gain():
    _,ch=open_good_challenge(); r=svc.compare_candidate(ch['challenge_id'],80,99,protected_segment_safe=False)
    assert r['comparison_state']=='CANDIDATE_UNSAFE' and 'PROTECTED_SEGMENT_REGRESSION' in r['reason_codes']

def test_candidate_must_be_materially_superior_before_replacement_approval():
    _,ch=open_good_challenge(); r=svc.compare_candidate(ch['challenge_id'],90,92)
    assert r['comparison_state']=='CANDIDATE_NON_INFERIOR'
    d=svc.decide_replacement(ch['challenge_id'],{'ticket':'change-1'})
    assert d['approved'] is False and 'CANDIDATE_SUPERIOR_COMPARISON_REQUIRED' in d['reason_codes']

def test_superior_candidate_gets_approved_but_not_immediate_champion_replacement():
    _,ch=open_good_challenge();superior(ch['challenge_id']);d=svc.decide_replacement(ch['challenge_id'],{'ticket':'change-2'})
    assert d['approved'] and d['decision_state']=='REPLACEMENT_APPROVED'
    with SessionLocal() as s:
        st=s.get(JourneyRecoveryForecastPortfolioChampionStateRow,ch['challenge_id'].replace('jfch_','missing_'))
        active=s.execute(select(JourneyRecoveryForecastPortfolioChampionStateRow).where(JourneyRecoveryForecastPortfolioChampionStateRow.portfolio_id=='pf',JourneyRecoveryForecastPortfolioChampionStateRow.champion_state!='SUPERSEDED')).scalars().all()
        assert any(x.champion_model_version_id=='champ' for x in active)

def test_transition_reads_4r_canary_as_source_of_truth():
    _,ch=open_good_challenge();superior(ch['challenge_id']);d=svc.decide_replacement(ch['challenge_id'],{'ticket':'change-3'});seed_4r(10)
    t=svc.sync_transition(d['replacement_decision_id'],'SYNC',{'evidence':'4r'})
    assert t['transition_state']=='REPLACEMENT_CANARY' and t['canary_percentage']==10 and t['previous_stable_champion_model_version_id']=='champ'

def test_full_traffic_cannot_finalize_without_4v_production_proof():
    _,ch=open_good_challenge();superior(ch['challenge_id']);d=svc.decide_replacement(ch['challenge_id'],{'ticket':'change-4'});seed_4r(100)
    with pytest.raises(ValueError,match='4V_PRODUCTION_PROOF_REQUIRED_tA'): svc.sync_transition(d['replacement_decision_id'],'FINALIZE',{'proof':'missing'})

def test_safe_replacement_and_rollback_preserve_history_and_supplier_fact():
    c,ch=open_good_challenge();superior(ch['challenge_id']);d=svc.decide_replacement(ch['challenge_id'],{'ticket':'change-5'});seed_4r(100);seed_4v_proofs()
    t=svc.sync_transition(d['replacement_decision_id'],'FINALIZE',{'production':'stable'})
    assert t['transition_state']=='CHAMPION_REPLACED' and t['supplier_fact_unchanged'] is True
    st=svc.status('PROD'); assert st['champions'][0]['champion_model_version_id']=='cand' and st['champions'][0]['previous_stable_champion_model_version_id']=='champ'
    rb=svc.sync_transition(d['replacement_decision_id'],'ROLLBACK',{'incident':'regression'})
    assert rb['transition_state']=='REPLACEMENT_ROLLED_BACK' and rb['to_model_version_id']=='champ' and rb['supplier_fact_unchanged'] is True
