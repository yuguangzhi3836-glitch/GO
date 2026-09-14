"""C09: overlapping reevaluation, durable evidence reuse and exact hook replay."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier, BrokenBarrierError, local
import pytest
from fastapi import HTTPException

from sqlalchemy import select
from sqlalchemy.orm import Session

from go_hotel.db.models import (
    JudgmentEvidencePackageRow, JudgmentHookRow, JudgmentRuntimeRow,
    RecommendationDecisionRow, RiskEventRuntimeRow,
    GoodHotelStandardVersionRow, GoodHotelStandardGovernanceEventRow,
)
from go_hotel.db.session import SessionLocal
from go_hotel.judgment.service import judgment_service as svc
from go_hotel.judgment.good_hotel_standard import good_hotel_standard_service


def rows(model):
    with SessionLocal() as session:
        return list(session.scalars(select(model)))


def assert_one_active(hotel):
    judgments = [x for x in rows(JudgmentRuntimeRow) if x.hotel_id == hotel]
    active = [x for x in judgments if x.status == 'ACTIVE']
    decisions = [x for x in rows(RecommendationDecisionRow) if x.hotel_id == hotel and x.valid_to is None]
    assert len(active) == len(decisions) == 1
    assert decisions[0].judgment_id == active[0].judgment_id
    assert len([x for x in rows(JudgmentEvidencePackageRow) if x.package_id == active[0].evidence_package_id]) == 1
    return active[0]


def hook(hotel='next-hotel', ident='next-hook'):
    now = datetime.now(timezone.utc)
    with SessionLocal.begin() as session:
        session.add(RiskEventRuntimeRow(risk_event_id=ident+'-risk', hotel_id=hotel,
            order_id='isolated-order', review_id='isolated-review', risk_type='SERIOUS_HYGIENE',
            severity='R2', status='CONFIRMED', confidence_bps=9900, created_at=now, updated_at=now))
        session.add(JudgmentHookRow(hook_id=ident, hotel_id=hotel, source_type='RISK_EVENT',
            source_id=ident+'-risk', reason_code='RISK_EVENT_CONFIRMED', status='REQUESTED',
            payload={'original_fact': 'preserved'}, created_at=now))
    return ident


def test_unchanged_reevaluation_reuses_sealed_evidence_and_active_judgment():
    first = svc.reevaluate('next-hotel')
    second = svc.reevaluate('next-hotel')
    assert second['judgment_id'] == first['judgment_id']
    assert second['evidence_package'] == first['evidence_package']
    assert len(rows(JudgmentEvidencePackageRow)) == 1
    assert_one_active('next-hotel')


def test_two_first_writers_cannot_leave_two_active_judgments(monkeypatch):
    good_hotel_standard_service.active()
    ready = Barrier(2)
    read_rendezvous = Barrier(2)
    original = Session.scalar
    def observed_read(session, statement, *args, **kwargs):
        value = original(session, statement, *args, **kwargs)
        sql = str(statement)
        # Coordinate the old read-before-write race without replacing DB results.
        # Serialized implementations let the first reader time out then commit.
        if 'FROM judgment_runtime' in sql and 'judgment_runtime.status' in sql:
            try:
                read_rendezvous.wait(timeout=0.3)
            except BrokenBarrierError:
                pass
        return value
    monkeypatch.setattr(Session, 'scalar', observed_read)
    def evaluate(label):
        ready.wait(timeout=10)
        return svc.reevaluate('next-hotel', {'assessment_revision': label})
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = [f.result(timeout=15) for f in [pool.submit(evaluate, 'A'), pool.submit(evaluate, 'B')]]
    assert len({x['judgment_id'] for x in values}) == 2
    active = assert_one_active('next-hotel')
    assert len([x for x in rows(JudgmentRuntimeRow) if x.status == 'SUPERSEDED']) == 1
    assert svc.get_latest('next-hotel')['judgment_id'] == active.judgment_id


def test_concurrent_same_hook_is_one_result_and_payload_keeps_evidence_binding():
    hid = hook()
    good_hotel_standard_service.active()
    ready = Barrier(2)
    def process():
        ready.wait(timeout=10)
        return svc.process_hook(hid)
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = [f.result(timeout=15) for f in [pool.submit(process), pool.submit(process)]]
    assert values[0]['judgment_id'] == values[1]['judgment_id']
    active = assert_one_active('next-hotel')
    with SessionLocal() as session:
        h = session.get(JudgmentHookRow, hid)
        assert h.status == 'COMPLETED'
        assert h.payload['original_fact'] == 'preserved'
        assert h.payload['judgment_id'] == active.judgment_id
        assert h.payload['evidence_package_id'] == active.evidence_package_id


def test_hook_replay_returns_its_original_judgment_after_later_reevaluation():
    hid = hook()
    first = svc.process_hook(hid)
    later = svc.reevaluate('next-hotel', {'assessment_revision': 'later'})
    assert later['judgment_id'] != first['judgment_id']
    replay = svc.process_hook(hid)
    assert replay['judgment_id'] == first['judgment_id']
    assert replay['evidence_package']['package_id'] == first['evidence_package']['package_id']
    assert replay['status'] == 'SUPERSEDED'
    assert_one_active('next-hotel')


def test_completed_hook_with_missing_binding_requires_review():
    hid = hook()
    svc.process_hook(hid)
    with SessionLocal.begin() as session:
        session.get(JudgmentHookRow, hid).payload = {'original_fact': 'preserved'}
    with pytest.raises(HTTPException) as caught:
        svc.process_hook(hid)
    assert caught.value.detail['code'] == 'JUDGMENT_HOOK_RESULT_REVIEW_REQUIRED'
    assert_one_active('next-hotel')


def test_completed_hook_cannot_be_rebound_to_another_hotel():
    hid = hook()
    svc.process_hook(hid)
    other = svc.reevaluate('other-hotel')
    with SessionLocal.begin() as session:
        session.get(JudgmentHookRow, hid).payload = {'judgment_id': other['judgment_id'],
            'evidence_package_id': other['evidence_package']['package_id']}
    with pytest.raises(HTTPException) as caught:
        svc.process_hook(hid)
    assert caught.value.detail['code'] == 'JUDGMENT_HOOK_RESULT_REVIEW_REQUIRED'
    assert_one_active('next-hotel')
    assert_one_active('other-hotel')


def test_historical_content_can_be_reused_without_reactivating_old_judgment():
    first = svc.reevaluate('next-hotel', {'assessment_revision': 'A'})
    second = svc.reevaluate('next-hotel', {'assessment_revision': 'B'})
    third = svc.reevaluate('next-hotel', {'assessment_revision': 'A'})
    assert len({first['judgment_id'], second['judgment_id'], third['judgment_id']}) == 3
    assert first['evidence_package']['package_id'] == third['evidence_package']['package_id']
    assert len(rows(JudgmentEvidencePackageRow)) == 2
    assert svc.get_judgment(first['judgment_id'])['status'] == 'SUPERSEDED'
    assert_one_active('next-hotel')


def test_hook_without_matching_persisted_source_is_not_marked_completed():
    hid = hook()
    with SessionLocal.begin() as session:
        session.get(JudgmentHookRow, hid).source_id = 'not-in-persisted-facts'
    svc.reevaluate('next-hotel')
    with SessionLocal() as session:
        assert session.get(JudgmentHookRow, hid).status == 'REQUESTED'


def test_first_hotel_writers_also_serialize_uninitialized_standard(monkeypatch):
    barrier = Barrier(2)
    first_read = local()
    original = Session.scalar
    def observed_read(session, statement, *args, **kwargs):
        value = original(session, statement, *args, **kwargs)
        if 'FROM good_hotel_standard_version' in str(statement) and not getattr(first_read, 'done', False):
            first_read.done = True
            try:
                barrier.wait(timeout=0.3)
            except BrokenBarrierError:
                pass
        return value
    monkeypatch.setattr(Session, 'scalar', observed_read)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [f.result(timeout=15) for f in [pool.submit(svc.reevaluate, 'next-hotel'), pool.submit(svc.reevaluate, 'next-hotel')]]
    assert results[0]['judgment_id'] == results[1]['judgment_id']
    assert_one_active('next-hotel')


def test_invalid_evidence_supplement_cannot_initialize_standard_or_write_events():
    assert rows(GoodHotelStandardVersionRow) == []
    assert rows(GoodHotelStandardGovernanceEventRow) == []
    with pytest.raises(HTTPException) as caught:
        svc.reevaluate('next-hotel', {'confirmed_serious_risk_count': 0})
    assert caught.value.detail['code'] == 'JUDGMENT_EVIDENCE_FIELD_FORBIDDEN'
    assert rows(GoodHotelStandardVersionRow) == []
    assert rows(GoodHotelStandardGovernanceEventRow) == []
    assert rows(JudgmentRuntimeRow) == []
