"""Public endorsement must preserve its sealed hotel, value and time binding."""
from datetime import timedelta
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from go_hotel.domain.models import now_utc
from go_hotel.db.models import JudgmentRuntimeRow, JudgmentEvidencePackageRow, RecommendationDecisionRow
from go_hotel.db.session import SessionLocal
from go_hotel.judgment.service import judgment_service as svc
from test_sprint1p_judgment_runtime import constitution_assessment


def publish():
    return svc.reevaluate('bound-hotel', {'recommendation_assessment': constitution_assessment()})


@pytest.mark.parametrize('damage', ['other_hotel', 'expired_decision', 'future_decision', 'expired_judgment',
    'standard_mismatch', 'score_mismatch', 'evidence_hotel', 'evidence_content'])
def test_invalid_binding_is_not_published(damage):
    result = publish()
    with SessionLocal.begin() as session:
        j = session.get(JudgmentRuntimeRow, result['judgment_id'])
        r = session.scalar(select(RecommendationDecisionRow).where(RecommendationDecisionRow.judgment_id == j.judgment_id))
        p = session.get(JudgmentEvidencePackageRow, j.evidence_package_id)
        if damage == 'other_hotel': r.hotel_id = 'another-hotel'
        elif damage == 'expired_decision': r.valid_to = now_utc() - timedelta(seconds=1)
        elif damage == 'future_decision': r.valid_from = now_utc() + timedelta(days=1)
        elif damage == 'expired_judgment': j.valid_to = now_utc() - timedelta(seconds=1)
        elif damage == 'standard_mismatch': r.good_hotel_standard_version_id = 'different-standard'
        elif damage == 'score_mismatch': r.public_go_score_milli = j.go_score_milli + 100
        elif damage == 'evidence_hotel': p.hotel_id = 'another-hotel'
        elif damage == 'evidence_content': p.feature_snapshot = {**p.feature_snapshot, 'unsealed_fact': True}
    summary = svc.public_summary_or_default('bound-hotel')
    assert summary['go_score'] is None
    assert summary['recommendation_status'] == 'NOT_YET_RATED'
    assert summary['reason_codes'] == ['JUDGMENT_RESULT_REVIEW_REQUIRED']
    with pytest.raises(HTTPException) as caught:
        svc.public_view('bound-hotel')
    assert caught.value.detail['code'] == 'JUDGMENT_RESULT_REVIEW_REQUIRED'


def test_valid_public_binding_and_historical_audit_remain_available():
    first = publish()
    assert svc.public_summary_or_default('bound-hotel')['go_score'] == first['go_score']
    assert svc.public_view('bound-hotel')['recommendation']['status'] == 'GO_RECOMMENDED'
    second = svc.reevaluate('bound-hotel', {'revision': 2})
    assert svc.public_view('bound-hotel')['judgment_id'] == second['judgment_id']
    assert svc.get_judgment(first['judgment_id'])['status'] == 'SUPERSEDED'
    assert svc.public_summary_or_default('absent-hotel')['reason_codes'] == ['INSUFFICIENT_EVIDENCE']


def test_http_public_endpoint_rejects_cross_hotel_decision(client):
    result = publish()
    with SessionLocal.begin() as session:
        row = session.scalar(select(RecommendationDecisionRow).where(RecommendationDecisionRow.judgment_id == result['judgment_id']))
        row.hotel_id = 'different-hotel'
    response = client.get('/v1/hotels/bound-hotel/judgment')
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'JUDGMENT_RESULT_REVIEW_REQUIRED'
    assert 'go_score' not in response.json()


def test_public_decision_validity_is_half_open(monkeypatch):
    import go_hotel.judgment.service as module
    result = publish()
    opened = now_utc()
    closed = opened + timedelta(minutes=1)
    with SessionLocal.begin() as session:
        row = session.scalar(select(RecommendationDecisionRow).where(RecommendationDecisionRow.judgment_id == result['judgment_id']))
        row.valid_from, row.valid_to = opened, closed
    monkeypatch.setattr(module, 'now_utc', lambda: opened)
    assert svc.public_summary_or_default('bound-hotel')['go_score'] == result['go_score']
    monkeypatch.setattr(module, 'now_utc', lambda: closed)
    assert svc.public_summary_or_default('bound-hotel')['go_score'] is None


def test_standard_upgrade_keeps_one_decision_per_judgment_and_public_history():
    from go_hotel.judgment.good_hotel_standard import good_hotel_standard_service, DEFAULT
    first = publish()
    updated = {**DEFAULT, 'thresholds': {**DEFAULT['thresholds'], 'minimum_completed_reviews_for_go_score': 2}}
    version = good_hotel_standard_service.create(updated, 'maker')
    good_hotel_standard_service.approve(version['good_hotel_standard_version_id'], 'checker')
    second = publish()
    assert first['judgment_id'] != second['judgment_id']
    assert svc.public_view('bound-hotel')['judgment_id'] == second['judgment_id']
    assert svc.public_view('bound-hotel')['recommendation']['status'] == 'GO_RECOMMENDED'
    with SessionLocal() as session:
        for result in (first, second):
            assert len(list(session.scalars(select(RecommendationDecisionRow).where(
                RecommendationDecisionRow.judgment_id == result['judgment_id'])))) == 1
    assert svc.get_judgment(first['judgment_id'])['status'] == 'SUPERSEDED'


def test_hotel_search_retains_offer_and_hides_expired_endorsement(client):
    tomorrow = (now_utc() + timedelta(days=30)).date()
    payload = {'destination': {'city_code': 'TYO'},
        'stay': {'check_in': tomorrow.isoformat(), 'check_out': (tomorrow + timedelta(days=2)).isoformat()},
        'occupancy': {'rooms': 1, 'adults': 2, 'children': 0}, 'currency': 'CNY'}
    first = client.post('/v1/search/hotels', json=payload)
    assert first.status_code == 200
    hotel = first.json()['data']['hotels'][0]['hotel_id']
    result = svc.reevaluate(hotel, {'recommendation_assessment': constitution_assessment()})
    before = client.post('/v1/search/hotels', json=payload).json()['data']['hotels'][0]
    assert before['go_score'] == result['go_score']
    with SessionLocal.begin() as session:
        row = session.scalar(select(RecommendationDecisionRow).where(RecommendationDecisionRow.judgment_id == result['judgment_id']))
        row.valid_to = now_utc() - timedelta(seconds=1)
    after = client.post('/v1/search/hotels', json=payload)
    assert after.status_code == 200
    item = after.json()['data']['hotels'][0]
    assert item['hotel_id'] == hotel and item['best_offer']['offer_id']
    assert item['go_score'] is None and item['recommendation_status'] == 'NOT_YET_RATED'
