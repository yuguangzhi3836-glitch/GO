from datetime import datetime, timezone
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import JourneyRecoveryReliabilityProfileRow,JourneyRecoverySupplierOperationRow
from go_hotel.journey.recovery_data_governance import recovery_data_governance_service as dg
from go_hotel.journey.recovery_strategy_governance import recovery_strategy_governance_service as sg
from go_hotel.journey.recovery_learning_registry import recovery_learning_registry_service as lr

def _profile(s,vertical='RAIL',adapter='rail_recovery_v1',n=30):
    r=s.get(JourneyRecoveryReliabilityProfileRow,f'{vertical}:{adapter}')
    if not r:
        r=JourneyRecoveryReliabilityProfileRow(reliability_profile_id=f'{vertical}:{adapter}',vertical=vertical,adapter_key=adapter,sample_count=n,async_count=1,unknown_count=1,confirmed_count=n-2,failed_count=0,manual_review_count=1,avg_confirmation_seconds=20,avg_webhook_lag_seconds=4,avg_poll_attempts=2,timeout_rate=.03,manual_review_rate=.03,confirmation_rate=.93,confidence=.95,risk_band='LOW',recommended_initial_poll_seconds=10,recommended_max_poll_seconds=180,recommended_max_attempts=10,recommended_ack_multiplier=.8,recommended_resolution_multiplier=1.0,metrics_json={},calculated_at=datetime.now(timezone.utc));s.add(r);s.flush()
    return r

def test_supplier_mapping_and_quality_gate( ):
    s=SessionLocal();p=_profile(s)
    for x in range(6):s.add(JourneyRecoverySupplierOperationRow(supplier_operation_id=f'op3p{x}',execution_item_id=f'i{x}',execution_id='e',vertical='RAIL',adapter_key='rail_recovery_v1',command_type='CHANGE',supplier_idempotency_key=f'k{x}',status='PENDING',created_at=datetime.now(timezone.utc),updated_at=datetime.now(timezone.utc)))
    s.commit();s.close();dg.upsert_supplier_mapping('RAIL','rail_recovery_v1','supplier_rail_1','test')
    out=dg.assess_quality();assert any(x['quality_state']=='PASS' for x in out)

def test_contaminated_sample_is_quarantined( ):
    s=SessionLocal();p=_profile(s,'HOTEL','hotel_recovery_v1',10);s.commit();s.close()
    dg.upsert_supplier_mapping('HOTEL','hotel_recovery_v1','supplier_hotel_1','test')
    s=SessionLocal();s.add(JourneyRecoverySupplierOperationRow(supplier_operation_id='badop',execution_item_id='baditem',execution_id='e',vertical='HOTEL',adapter_key='hotel_recovery_v1',command_type='CHANGE',supplier_idempotency_key='badkey',status='CONFIRMED',supplier_confirmation_id=None,created_at=datetime.now(timezone.utc),updated_at=datetime.now(timezone.utc)));s.commit();s.close()
    out=dg.assess_quality();assert any(x['quality_state']=='QUARANTINED' for x in out);assert dg.quarantines()

def test_global_kill_switch_forces_baseline( ):
    s=SessionLocal();p=_profile(s,'FLIGHT','flight_recovery_v1',30);s.commit();s.close()
    dg.upsert_supplier_mapping('FLIGHT','flight_recovery_v1','supplier_flight_1','test');dg.assess_quality()
    dg.set_kill_switch('GLOBAL','*',True,'test','incident')
    with SessionLocal() as ss:
        pp=ss.get(JourneyRecoveryReliabilityProfileRow,'FLIGHT:flight_recovery_v1');ev=sg.evaluate(ss,pp,'item-kill');assert ev['eligible'] is False;assert any('LEARNING_KILL_SWITCH' in x for x in ev['reasons']);assert ev['applied']['max_attempts']==8
    dg.set_kill_switch('GLOBAL','*',False,'test','resolved')

def test_privacy_budget_exhaustion_blocks_release( ):
    with SessionLocal() as s:
        b=dg.budget(s,'benchmark:TEST');b.epsilon_budget=.15;s.commit()
    with SessionLocal() as s:
        ok,_=dg.consume_privacy_budget(s,'benchmark:TEST',.1);s.commit();assert ok
    with SessionLocal() as s:
        ok,b=dg.consume_privacy_budget(s,'benchmark:TEST',.1);s.commit();assert not ok and b.state=='EXHAUSTED'

def test_benchmark_requires_governed_mapping_quality_and_privacy( ):
    s=SessionLocal()
    for idx in range(3):
        adapter=f'attr_{idx}';_profile(s,'ATTRACTION',adapter,20)
        for x in range(5):s.add(JourneyRecoverySupplierOperationRow(supplier_operation_id=f'a{idx}_{x}',execution_item_id=f'ai{idx}_{x}',execution_id='e',vertical='ATTRACTION',adapter_key=adapter,command_type='CHANGE',supplier_idempotency_key=f'ak{idx}_{x}',status='PENDING',created_at=datetime.now(timezone.utc),updated_at=datetime.now(timezone.utc)))
    s.commit();s.close()
    for idx in range(3):dg.upsert_supplier_mapping('ATTRACTION',f'attr_{idx}',f'supplier_{idx}','test')
    dg.assess_quality();out=lr.rebuild_benchmarks(anonymization_k=3);assert any(x['vertical']=='ATTRACTION' and x['state']=='AVAILABLE' for x in out)
