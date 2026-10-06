from datetime import datetime, timezone

from sqlalchemy import select

from go_hotel.db.models import JudgmentEvidencePackageRow, JudgmentHookRow, JudgmentRuntimeRow, RecommendationDecisionRow
from go_hotel.db.session import SessionLocal
from go_hotel.judgment.service import (
    ANNUAL_REVIEW_SOURCE_TYPE,
    RECOMMENDATION_EXPIRED_ANNUAL_REASSESSMENT_REQUIRED,
    RECOMMENDATION_VALIDITY_START_UNVERIFIED,
    judgment_service,
)


def at(value: str) -> datetime:
    return datetime.fromisoformat(value)


def assessment(label: str = "initial") -> dict:
    return {
        "verdict": "GO_RECOMMENDED",
        "worth_the_journey": "YES",
        "commercial_independence_attested": True,
        "dimensions": {
            key: {
                "state": "PRESENT",
                "evidence_summary": f"{label}:{key}",
            }
            for key in (
                "WORK_OF_HOSPITALITY",
                "IRREPLACEABILITY",
                "SENSE_OF_PLACE",
                "AESTHETIC_JUDGMENT",
                "EMOTIONAL_RESONANCE",
                "WORTH_THE_JOURNEY",
            )
        },
    }


def open_review_hooks(hotel_id: str):
    with SessionLocal() as session:
        return list(session.scalars(select(JudgmentHookRow).where(
            JudgmentHookRow.hotel_id == hotel_id,
            JudgmentHookRow.source_type == ANNUAL_REVIEW_SOURCE_TYPE,
        ).order_by(JudgmentHookRow.created_at)))


def test_recommendation_validity_tracks_review_window_and_expires_at_boundary(monkeypatch):
    hotel_id = "annual-window-hotel"
    created_at = at("2024-02-29T12:00:00+00:00")
    monkeypatch.setattr("go_hotel.judgment.service.now_utc", lambda: created_at)
    first = judgment_service.reevaluate(hotel_id, {"recommendation_assessment": assessment()})
    assert first["recommendation"]["status"] == "GO_RECOMMENDED"
    assert first["recommendation"]["validity"]["expires_at"] == "2025-02-28T12:00:00+00:00"
    assert first["recommendation"]["validity"]["review_due_at"] == "2025-01-29T12:00:00+00:00"

    review_due_at = at("2025-01-29T12:00:00+00:00")
    monkeypatch.setattr("go_hotel.judgment.service.now_utc", lambda: review_due_at)
    summary = judgment_service.public_summary_or_default(hotel_id)
    assert summary["recommendation_status"] == "GO_RECOMMENDED"
    assert summary["validity"]["status"] == "REASSESSMENT_DUE"
    assert judgment_service.process_pending() == []
    hooks = open_review_hooks(hotel_id)
    assert len(hooks) == 1
    assert hooks[0].status == "REQUESTED"
    assert hooks[0].payload["validity"]["review_due_at"] == "2025-01-29T12:00:00+00:00"

    expires_at = at("2025-02-28T12:00:00+00:00")
    monkeypatch.setattr("go_hotel.judgment.service.now_utc", lambda: expires_at)
    latest = judgment_service.get_latest(hotel_id)
    public_view = judgment_service.public_view(hotel_id)
    public_summary = judgment_service.public_summary_or_default(hotel_id)
    assert latest["recommendation"]["status"] == "NOT_YET_RATED"
    assert latest["recommendation"]["reason_codes"] == [RECOMMENDATION_EXPIRED_ANNUAL_REASSESSMENT_REQUIRED]
    assert latest["public_go_score"] is None
    assert public_view["recommendation"]["status"] == "NOT_YET_RATED"
    assert public_summary["recommendation_status"] == "NOT_YET_RATED"


def test_same_assessment_replay_cannot_reset_annual_window(monkeypatch):
    hotel_id = "annual-replay-hotel"
    created_at = at("2024-03-10T08:30:00+00:00")
    monkeypatch.setattr("go_hotel.judgment.service.now_utc", lambda: created_at)
    first = judgment_service.reevaluate(hotel_id, {"recommendation_assessment": assessment("cycle-a")})
    first_expiry = first["recommendation"]["validity"]["expires_at"]

    replayed_at = at("2025-03-15T08:30:00+00:00")
    monkeypatch.setattr("go_hotel.judgment.service.now_utc", lambda: replayed_at)
    replay = judgment_service.reevaluate(hotel_id, {
        "recommendation_assessment": assessment("cycle-a"),
        "assessment_revision": "replayed-same-assessment",
    })
    assert replay["judgment_id"] != first["judgment_id"]
    assert replay["recommendation"]["authority_status"] == "GO_RECOMMENDED"
    assert replay["recommendation"]["status"] == "NOT_YET_RATED"
    assert replay["recommendation"]["validity"]["expires_at"] == first_expiry
    assert replay["recommendation"]["reason_codes"] == [RECOMMENDATION_EXPIRED_ANNUAL_REASSESSMENT_REQUIRED]


def test_new_assessment_creates_new_cycle_and_completes_review_request(monkeypatch):
    hotel_id = "annual-renewal-hotel"
    created_at = at("2024-04-01T00:00:00+00:00")
    monkeypatch.setattr("go_hotel.judgment.service.now_utc", lambda: created_at)
    first = judgment_service.reevaluate(hotel_id, {"recommendation_assessment": assessment("cycle-a")})

    review_due_at = at("2025-03-02T00:00:00+00:00")
    monkeypatch.setattr("go_hotel.judgment.service.now_utc", lambda: review_due_at)
    judgment_service.process_pending()
    hooks = open_review_hooks(hotel_id)
    assert len(hooks) == 1
    assert hooks[0].status == "REQUESTED"

    renewed_at = at("2025-03-15T00:00:00+00:00")
    monkeypatch.setattr("go_hotel.judgment.service.now_utc", lambda: renewed_at)
    renewed = judgment_service.reevaluate(hotel_id, {"recommendation_assessment": assessment("cycle-b")})
    assert renewed["judgment_id"] != first["judgment_id"]
    assert renewed["recommendation"]["status"] == "GO_RECOMMENDED"
    assert renewed["recommendation"]["validity"]["valid_from"] == "2025-03-15T00:00:00+00:00"
    assert renewed["recommendation"]["validity"]["expires_at"] == "2026-03-15T00:00:00+00:00"

    hooks = open_review_hooks(hotel_id)
    assert len(hooks) == 1
    assert hooks[0].status == "COMPLETED"
    assert hooks[0].payload["previous_judgment_id"] == first["judgment_id"]
    assert hooks[0].payload["judgment_id"] == renewed["judgment_id"]


def test_legacy_recommended_row_without_verifiable_assessment_becomes_pending_review(monkeypatch):
    now = at("2026-01-05T09:00:00+00:00")
    monkeypatch.setattr("go_hotel.judgment.service.now_utc", lambda: now)
    with SessionLocal.begin() as session:
        session.add(JudgmentEvidencePackageRow(
            package_id="legacy-evpkg",
            hotel_id="legacy-hotel",
            source_refs=[],
            source_summary={},
            feature_snapshot={},
            excluded_commercial_fields=[],
            content_hash="a" * 64,
            sealed_at=now,
            created_at=now,
        ))
        session.add(JudgmentRuntimeRow(
            judgment_id="legacy-judgment",
            hotel_id="legacy-hotel",
            evidence_package_id="legacy-evpkg",
            go_score_milli=4700,
            dimension_result={},
            explanation={},
            confidence_bps=9000,
            model_version="m1",
            prompt_version="p1",
            rule_version="r1",
            good_hotel_standard_version_id="ghs1",
            status="ACTIVE",
            public_at=now,
            valid_from=now,
            valid_to=None,
            created_at=now,
        ))
        session.add(RecommendationDecisionRow(
            decision_id="legacy-decision",
            hotel_id="legacy-hotel",
            judgment_id="legacy-judgment",
            status="GO_RECOMMENDED",
            reason_codes=["LEGACY_IMPORTED"],
            public_go_score_milli=4700,
            rule_version="rr1",
            good_hotel_standard_version_id="ghs1",
            valid_from=now,
            valid_to=None,
            created_at=now,
        ))

    summary = judgment_service.public_summary_or_default("legacy-hotel")
    latest = judgment_service.get_latest("legacy-hotel")
    assert summary["recommendation_status"] == "NOT_YET_RATED"
    assert RECOMMENDATION_VALIDITY_START_UNVERIFIED in summary["reason_codes"]
    assert latest["recommendation"]["authority_status"] == "GO_RECOMMENDED"
    assert latest["recommendation"]["status"] == "NOT_YET_RATED"

    judgment_service.process_pending()
    hooks = open_review_hooks("legacy-hotel")
    assert len(hooks) == 1
    assert hooks[0].status == "REQUESTED"
    assert hooks[0].payload["validity"]["status"] == "START_UNVERIFIED"


def test_process_pending_is_idempotent_for_same_review_cycle(monkeypatch):
    hotel_id = "annual-idempotent-hotel"
    created_at = at("2024-06-01T06:00:00+00:00")
    monkeypatch.setattr("go_hotel.judgment.service.now_utc", lambda: created_at)
    judgment_service.reevaluate(hotel_id, {"recommendation_assessment": assessment()})

    review_due_at = at("2025-05-02T06:00:00+00:00")
    monkeypatch.setattr("go_hotel.judgment.service.now_utc", lambda: review_due_at)
    judgment_service.process_pending()
    judgment_service.process_pending()
    hooks = open_review_hooks(hotel_id)
    assert len(hooks) == 1
    assert hooks[0].status == "REQUESTED"

def test_historical_assessment_replay_after_intervening_decision_never_renews(monkeypatch):
    hotel = 'annual-history'
    monkeypatch.setattr('go_hotel.judgment.service.now_utc', lambda: at('2024-01-01T00:00:00+00:00'))
    first = judgment_service.reevaluate(hotel, {'recommendation_assessment': assessment('A')})
    monkeypatch.setattr('go_hotel.judgment.service.now_utc', lambda: at('2024-12-20T00:00:00+00:00'))
    judgment_service.reevaluate(hotel, {'recommendation_assessment': assessment('B')})
    monkeypatch.setattr('go_hotel.judgment.service.now_utc', lambda: at('2025-02-01T00:00:00+00:00'))
    replay = judgment_service.reevaluate(hotel, {'recommendation_assessment': assessment('A')})
    assert replay['recommendation']['status'] == 'NOT_YET_RATED'
    assert replay['recommendation']['validity']['expires_at'] == first['recommendation']['validity']['expires_at']


def test_scan_pages_all_hotels_and_survives_service_restart(monkeypatch):
    from go_hotel.judgment.service import JudgmentService
    monkeypatch.setattr('go_hotel.judgment.service.now_utc', lambda: at('2024-01-01T00:00:00+00:00'))
    for hotel in ['a-old', 'b-old', 'c-old']:
        judgment_service.reevaluate(hotel, {'recommendation_assessment': assessment()})
    monkeypatch.setattr('go_hotel.judgment.service.now_utc', lambda: at('2025-02-01T00:00:00+00:00'))
    judgment_service.process_pending(limit=1)
    JudgmentService().process_pending(limit=1)
    for hotel in ['a-old', 'b-old', 'c-old']:
        assert len(open_review_hooks(hotel)) == 1


def test_same_cycle_different_judgment_does_not_complete_or_duplicate_request(monkeypatch):
    hotel = 'annual-cycle-identity'
    monkeypatch.setattr('go_hotel.judgment.service.now_utc', lambda: at('2024-01-01T00:00:00+00:00'))
    judgment_service.reevaluate(hotel, {'recommendation_assessment': assessment()})
    monkeypatch.setattr('go_hotel.judgment.service.now_utc', lambda: at('2024-12-15T00:00:00+00:00'))
    judgment_service.process_pending()
    original = open_review_hooks(hotel)[0]
    judgment_service.reevaluate(hotel, {'recommendation_assessment': assessment(), 'assessment_revision': 'transport-retry'})
    judgment_service.process_pending()
    hooks = open_review_hooks(hotel)
    assert len(hooks) == 1
    assert hooks[0].hook_id == original.hook_id
    assert hooks[0].status == 'REQUESTED'
    assert judgment_service.process_hook(hooks[0].hook_id)['recommendation']['status'] == 'GO_RECOMMENDED'
    assert open_review_hooks(hotel)[0].status == 'REQUESTED'


def test_failed_reassessment_does_not_extend_and_completed_hook_replays(monkeypatch):
    hotel = 'annual-failed-review'
    monkeypatch.setattr('go_hotel.judgment.service.now_utc', lambda: at('2024-01-01T00:00:00+00:00'))
    judgment_service.reevaluate(hotel, {'recommendation_assessment': assessment()})
    monkeypatch.setattr('go_hotel.judgment.service.now_utc', lambda: at('2024-12-15T00:00:00+00:00'))
    judgment_service.process_pending()
    failed = assessment('failed-review')
    failed['verdict'] = 'GO_NOT_RECOMMENDED'
    denied = judgment_service.reevaluate(hotel, {'recommendation_assessment': failed})
    hook = open_review_hooks(hotel)[0]
    assert hook.status == 'COMPLETED'
    assert hook.payload['outcome'] == 'GO_NOT_RECOMMENDED'
    assert denied['recommendation']['status'] == 'GO_NOT_RECOMMENDED'
    assert 'expires_at' not in denied['recommendation']['validity']
    assert judgment_service.process_hook(hook.hook_id)['judgment_id'] == denied['judgment_id']


def test_utc_30_day_boundary_and_concurrent_scan(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    hotel = 'annual-concurrent'
    monkeypatch.setattr('go_hotel.judgment.service.now_utc', lambda: at('2024-06-01T08:00:00+08:00'))
    judgment_service.reevaluate(hotel, {'recommendation_assessment': assessment()})
    monkeypatch.setattr('go_hotel.judgment.service.now_utc', lambda: at('2025-05-01T23:59:59+00:00'))
    judgment_service.process_pending()
    assert not open_review_hooks(hotel)
    monkeypatch.setattr('go_hotel.judgment.service.now_utc', lambda: at('2025-05-02T08:00:00+08:00'))
    ready = Barrier(2)
    def scan():
        ready.wait(timeout=5)
        return judgment_service.process_pending()
    with ThreadPoolExecutor(max_workers=2) as pool:
        runs = [pool.submit(scan), pool.submit(scan)]
        for run in runs:
            assert run.result(timeout=15) == []
    assert len(open_review_hooks(hotel)) == 1


def test_corrupt_validity_fails_closed_and_replay_does_not_repair_it(monkeypatch):
    hotel = 'annual-corrupt'
    monkeypatch.setattr('go_hotel.judgment.service.now_utc', lambda: at('2024-06-01T00:00:00+00:00'))
    first = judgment_service.reevaluate(hotel, {'recommendation_assessment': assessment()})
    with SessionLocal.begin() as session:
        package = session.get(JudgmentEvidencePackageRow, first['evidence_package']['package_id'])
        feature = dict(package.feature_snapshot)
        feature['recommendation_authority'] = {'assessment_digest': 'bad', 'started_at': 'not-a-date'}
        package.feature_snapshot = feature
    assert judgment_service.public_summary_or_default(hotel)['recommendation_status'] == 'NOT_YET_RATED'
    replay = judgment_service.reevaluate(hotel, {'recommendation_assessment': assessment()})
    assert replay['recommendation']['status'] == 'NOT_YET_RATED'


def test_validity_metadata_cannot_be_injected_by_caller():
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as caught:
        judgment_service.reevaluate('annual-injection', {'recommendation_authority': {'started_at': '2030-01-01'}})
    assert caught.value.detail['code'] == 'JUDGMENT_EVIDENCE_FIELD_FORBIDDEN'

def test_legacy_assessment_without_annual_provenance_cannot_start_today(monkeypatch):
    hotel = 'annual-legacy-assessment'
    monkeypatch.setattr('go_hotel.judgment.service.now_utc', lambda: at('2024-06-01T00:00:00+00:00'))
    first = judgment_service.reevaluate(hotel, {'recommendation_assessment': assessment()})
    with SessionLocal.begin() as session:
        p = session.get(JudgmentEvidencePackageRow, first['evidence_package']['package_id'])
        feature = dict(p.feature_snapshot)
        feature.pop('recommendation_authority')
        p.feature_snapshot = feature
    monkeypatch.setattr('go_hotel.judgment.service.now_utc', lambda: at('2026-06-01T00:00:00+00:00'))
    replay = judgment_service.reevaluate(hotel, {'recommendation_assessment': assessment()})
    assert replay['recommendation']['status'] == 'NOT_YET_RATED'
    assert replay['recommendation']['validity']['status'] == 'START_UNVERIFIED'
    assert 'expires_at' not in replay['recommendation']['validity']


def test_replayed_closed_cycle_and_superseded_read_never_restore_recommendation(monkeypatch):
    hotel = 'annual-closed-cycle'
    monkeypatch.setattr('go_hotel.judgment.service.now_utc', lambda: at('2024-01-01T00:00:00+00:00'))
    first = judgment_service.reevaluate(hotel, {'recommendation_assessment': assessment('A')})
    monkeypatch.setattr('go_hotel.judgment.service.now_utc', lambda: at('2024-12-15T00:00:00+00:00'))
    judgment_service.process_pending()
    judgment_service.reevaluate(hotel, {'recommendation_assessment': assessment('B')})
    assert judgment_service.get_judgment(first['judgment_id'])['recommendation']['status'] == 'NOT_YET_RATED'
    monkeypatch.setattr('go_hotel.judgment.service.now_utc', lambda: at('2025-02-01T00:00:00+00:00'))
    judgment_service.reevaluate(hotel, {'recommendation_assessment': assessment('A')})
    judgment_service.process_pending()
    assert len(open_review_hooks(hotel)) == 1
    assert judgment_service.public_summary_or_default(hotel)['recommendation_status'] == 'NOT_YET_RATED'


def test_annual_request_rolls_back_and_next_scan_recovers(monkeypatch):
    import pytest
    from sqlalchemy.orm import Session
    hotel = 'annual-crash'
    monkeypatch.setattr('go_hotel.judgment.service.now_utc', lambda: at('2024-01-01T00:00:00+00:00'))
    judgment_service.reevaluate(hotel, {'recommendation_assessment': assessment()})
    monkeypatch.setattr('go_hotel.judgment.service.now_utc', lambda: at('2025-01-01T00:00:00+00:00'))
    original_commit = Session.commit
    def interrupted_commit(session):
        if any(isinstance(row, JudgmentHookRow) for row in session.new):
            raise RuntimeError('isolated pre-commit failure')
        return original_commit(session)
    with monkeypatch.context() as m:
        m.setattr(Session, 'commit', interrupted_commit)
        with pytest.raises(RuntimeError, match='pre-commit'):
            judgment_service.process_pending()
    assert open_review_hooks(hotel) == []
    judgment_service.process_pending()
    judgment_service.process_pending()
    assert len(open_review_hooks(hotel)) == 1
