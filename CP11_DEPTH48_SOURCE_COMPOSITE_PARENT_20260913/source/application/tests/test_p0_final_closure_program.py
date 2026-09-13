from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import P0FinalClosureBundleRow
from go_hotel.services.p0_final_closure import p0_final_closure_service as svc,PROVIDER_MATRIX,CANCELLATION_REFUND_CONTRACT

def test_final_closure_design_contract_covers_all_day1_verticals_and_refund_states():
    assert set(PROVIDER_MATRIX)=={'PAYMENT','HOTEL','FLIGHT','RAIL','RIDE','RENTAL','ATTRACTION'}
    assert CANCELLATION_REFUND_CONTRACT==['CANCEL_REQUESTED','SUPPLIER_PROCESSING','CANCEL_CONFIRMED','REFUND_AMOUNT_CONFIRMED','REFUND_INITIATED','PSP_PROCESSING','REFUND_COMPLETED']

def test_final_closure_status_is_fail_closed_until_real_runtime_evidence_exists():
    r=svc.evaluate()
    assert r['external_sandbox_gate']=='BLOCK'
    assert 'ALL_VERTICAL_REAL_TRIPS_EVIDENCE_REQUIRED' in r['blockers']
    assert 'CLEAN_FULL_REGRESSION_REQUIRED' in r['blockers']
    assert r['provider_matrix']['PAYMENT']['named_provider']=='Stripe Test Mode'
    assert r['provider_matrix']['HOTEL']['named_provider']=='SiteMinder Channels Plus Test Environment'

def test_final_closure_bundle_is_append_only_snapshot():
    b=svc.seal('a'*64)
    assert b['external_sandbox_gate']=='BLOCK'
    with SessionLocal() as s:
        row=s.scalar(select(P0FinalClosureBundleRow).where(P0FinalClosureBundleRow.p0_final_closure_bundle_id==b['p0_final_closure_bundle_id']))
        assert row and row.evidence_hash==b['evidence_hash']
