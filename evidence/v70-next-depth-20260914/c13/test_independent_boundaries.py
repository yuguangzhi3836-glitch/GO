"""C13-owned next-depth cases: execute only after exact-candidate C14/root authorization."""
from copy import deepcopy
from datetime import datetime, UTC
from pathlib import Path
import hashlib
import importlib.util
import pytest
from sqlalchemy import select

from go_hotel.db.session import SessionLocal
from go_hotel.db.models import JourneyRecoveryEvidenceChainRow as Evidence, MobilityRideOrderRow
from go_hotel.services.rc20_vertical_evidence import _stable_hash
from go_hotel.repositories.sql import repo


def helper(relative, name):
    app = Path(__file__).resolve().parents[3] / 'application'
    spec = importlib.util.spec_from_file_location(name, app / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('phase', ['CONFIRMED', 'IN_PROGRESS'])
@pytest.mark.parametrize('field,bad', [('supplier_reference', 'OTHER-SUPPLIER'), ('actor', ''), ('evidence_reference', '')])
def test_c05_rehashed_unknown_record_with_unbound_authority_cannot_restore(phase, field, bad):
    from test_depth33_mobility_refund_consent import booked
    svc, owner, oid = booked('RIDE')
    if phase == 'IN_PROGRESS':
        svc.fulfill(owner, oid, 'START', 'isolated://c13/start')
    svc.admin_external_state(oid, 'UNKNOWN_EXTERNAL_STATE', 'isolated://c13/unknown', 'ops')
    with SessionLocal.begin() as session:
        rows = list(session.scalars(select(Evidence).where(Evidence.execution_id == 'rc20:RIDE:' + oid).order_by(Evidence.sequence_no)))
        latest = rows[-1]
        original_count = len(rows)
        body = deepcopy(latest.evidence_json)
        body['payload'][field] = bad
        latest.evidence_json = body
        latest.evidence_hash = _stable_hash(body)
        latest.entry_hash = _stable_hash({'evidence_hash': latest.evidence_hash, 'previous_hash': latest.previous_hash, 'sequence_no': latest.sequence_no})
    before = svc.get(owner, oid)
    with pytest.raises(ValueError, match='RIDE_RECOVERY_EVIDENCE_INVALID'):
        svc.admin_external_state(oid, 'CONFIRMED', 'isolated://c13/recovery', 'ops')
    assert svc.get(owner, oid) == before
    with SessionLocal() as session:
        assert session.get(MobilityRideOrderRow, oid).status == 'UNKNOWN_EXTERNAL_STATE'
        assert len(list(session.scalars(select(Evidence).where(Evidence.execution_id == 'rc20:RIDE:' + oid)))) == original_count


def test_c06_confirmed_date_change_uses_original_policy_after_catalog_drift(monkeypatch):
    from test_next_depth_c06_supplier_validity import install, booked, svc, service
    install(monkeypatch)
    _, owner, oid = booked('ATTRACTION')
    initial = deepcopy(svc.get(owner, oid)['redemption_window'])
    install(monkeypatch, destination_timezone='Europe/London', opens_minutes_before_session=0, closes_minutes_after_session=1)
    quote = svc.change_quote(owner, oid, '2026-09-16', '17:00')
    svc.execute_change(owner, oid, quote['quote_id'])
    svc.admin_external_state(oid, 'CONFIRMED', 'isolated://c13/change', 'ops', 'C13-SUPPLIER', 'C13-VOUCHER')
    frozen = svc.get(owner, oid)['redemption_window']
    assert frozen['destination_timezone'] == initial['destination_timezone'] == 'Asia/Tokyo'
    assert frozen['policy_reference'] == initial['policy_reference']
    assert frozen['opens_at'] == '2026-09-16T07:30:00+00:00'
    assert frozen['closes_at'] == '2026-09-16T10:00:00+00:00'
    monkeypatch.setattr(service, 'db_now_ms', lambda session: int(datetime(2026, 9, 16, 9, tzinfo=UTC).timestamp() * 1000))
    assert svc.redeem(owner, oid, 'isolated://c13/valid-original-zone')['status'] == 'FULFILLED'


@pytest.mark.parametrize('operation', ['FLIGHT_CHECKOUT', 'FLIGHT_EXECUTE_CHANGE'])
def test_c11_recovery_no_effect_claim_cannot_erase_uncertain_prior_execution(operation):
    from go_hotel.api.idempotency import run_recoverable_idempotent
    payload = {'user_id': 'c13-owner', 'order_id': 'c13-order', 'quote_id': 'c13-quote'}
    rid = payload['order_id'] if operation == 'FLIGHT_CHECKOUT' else payload['quote_id']
    key = 'c13-uncertain-original'
    visits = []
    def first(boundary):
        visits.append('first')
        boundary.before_effect()
        raise RuntimeError('C13_UNCERTAIN_ORIGINAL')
    def retry(boundary):
        visits.append('recovery')
        assert boundary.recovering
        boundary.prove_no_effect()
        assert not boundary.proven_no_effect
        raise ValueError('C13_RECOVERY_VALIDATION_REJECTED')
    with pytest.raises(RuntimeError, match='C13_UNCERTAIN_ORIGINAL'):
        run_recoverable_idempotent(operation, key, payload, rid, first, retry)
    assert repo.get_idempotency(operation, key)['response']['status'] == 'RECOVERY_REQUIRED'
    for _ in range(2):
        with pytest.raises(ValueError, match='C13_RECOVERY_VALIDATION_REJECTED'):
            run_recoverable_idempotent(operation, key, payload, rid, first, retry)
        for op, claim_key in ((operation, key), ('RESOURCE:' + operation, rid)):
            claim = repo.get_idempotency(op, claim_key)
            assert claim is not None and claim['response']['status'] == 'RECOVERY_REQUIRED'
    assert visits == ['first', 'recovery', 'recovery']


def test_c11_wrong_returned_capture_after_commit_is_held_then_same_money_recovers(monkeypatch):
    from fastapi import HTTPException
    h = helper('tests/payments/test_c11_flight_idempotency_recovery.py', 'c13_next_flight_setup')
    order = h.create_order()
    oid = order['order_id']
    original = h.checkout_bridge.checkout_contract
    def wrong_receipt(*args, **kwargs):
        receipt = original(*args, **kwargs)
        return {**receipt, 'capture_id': 'c13-foreign-capture'}
    monkeypatch.setattr(h.checkout_bridge, 'checkout_contract', wrong_receipt)
    with pytest.raises(HTTPException) as exc:
        h.call_checkout(oid)
    assert 'FLIGHT_PAYMENT_RETURNED_RECEIPT_INVALID' in str(exc.value.detail)
    before = h.observe('FLIGHT_CHECKOUT', oid, oid)
    assert before['claim']['body']['status'] == 'RECOVERY_REQUIRED'
    assert before['order_status'] == 'PAYMENT_AUTHORIZED'
    assert {m['type'] for m in before['money']} == {'AUTHORIZATION', 'CAPTURE'}
    monkeypatch.setattr(h.checkout_bridge, 'checkout_contract', original)
    result = h.call_checkout(oid)
    after = h.observe('FLIGHT_CHECKOUT', oid, oid)
    assert result['data']['status'] == 'PAYMENT_CONFIRMED_AWAITING_SUPPLIER'
    assert after['money'] == before['money']
    assert after['claim']['code'] == 200
    assert h.call_checkout(oid) == result


from test_c10_current_status_projection import isolated_session


@pytest.mark.no_db
def test_c10_mixed_vertical_same_order_id_has_separate_owned_projection(isolated_session):
    from go_hotel.journey import service as jm
    from go_hotel.db.models import GoJourneyItemRow
    from test_c10_current_status_projection import _seed, OWNER, MEMBER, OUTSIDER, JOURNEY_ID, ORDER_ID, STAMP
    hotel_model = _seed(isolated_session, 'HOTEL')
    flight_model, route = jm.VERTICALS['FLIGHT']
    with isolated_session.begin() as session:
        session.get(hotel_model, ORDER_ID).status = 'CANCELLED'
        session.add(flight_model(order_id=ORDER_ID, account_id=OWNER, prebook_id='c13-flight-prebook', status='TICKETED', total_amount_minor=50000, currency='CNY', created_at=STAMP, updated_at=STAMP))
        session.add(GoJourneyItemRow(item_id='c13-flight-item', journey_id=JOURNEY_ID, account_id=OWNER, vertical='FLIGHT', order_id=ORDER_ID, title='Flight', status_snapshot='HISTORICAL', facts_json={'frozen': True}, detail_route=route, sort_key='z', created_at=STAMP))
    for viewer in (OWNER, MEMBER):
        items = {x['vertical']: x for x in jm.journey_service.list(viewer)[0]['timeline']}
        assert items['HOTEL']['status'] == 'CANCELLED'
        assert items['FLIGHT']['status'] == 'TICKETED'
        assert items['FLIGHT']['facts'] == {'frozen': True}
    with isolated_session.begin() as session:
        session.get(flight_model, ORDER_ID).account_id = OUTSIDER
    items = {x['vertical']: x for x in jm.journey_service.list(MEMBER)[0]['timeline']}
    assert items['FLIGHT']['status'] == 'HISTORICAL'
    assert items['HOTEL']['status'] == 'CANCELLED'


@pytest.mark.no_db
def test_c12_symlinked_output_outside_root_cannot_admit_running_receipt(tmp_path):
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location('c13_next_receipt_verifier', root / 'ci/round2/verify_execution_receipt.py')
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    evidence = tmp_path / 'evidence'
    evidence.mkdir()
    outside = tmp_path / 'outside.log'
    outside.write_text('C13 independent fixture output\n')
    (evidence / 'output.log').symlink_to(outside)
    stamp = '2026-09-14T04:00:00+00:00'
    receipt = {'cell_id': 'C13', 'task_id': 'V70-R2-C13-02', 'agent': '/root/c13_independent', 'source_anchor': verifier.SOURCE_ANCHOR,
        'parent_candidate_commit': verifier.PARENT_CANDIDATE, 'status': 'RUNNING', 'acknowledged_at': stamp, 'started_at': stamp, 'observed_at': stamp,
        'execution_evidence': [{'kind': 'PROCESS_OUTPUT', 'path': 'output.log', 'sha256': hashlib.sha256(outside.read_bytes()).hexdigest()}]}
    result = verifier.verify(receipt, evidence, expected_cell='C13', expected_task='V70-R2-C13-02', expected_agent='/root/c13_independent')
    assert result['gate'] == 'HOLD' and any('outside root' in error for error in result['errors'])
    assert not result['authenticated_worker_identity'] and not result['live_worker_liveness_verified']
