from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from go_hotel.db.models import Base, GoJourneyRow, JourneyRecoveryOptionRow, JourneyRecoveryPlanRow
from go_hotel.journey import recovery as recovery_module


pytestmark = pytest.mark.no_db

OWNER = "c10_recovery_owner"
OTHER = "c10_recovery_other"
JOURNEY_ID = "c10_recovery_journey"
OTHER_JOURNEY_ID = "c10_recovery_other_journey"
PLAN_ID = "c10_recovery_plan"
OTHER_PLAN_ID = "c10_recovery_other_plan"
FIXED_NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def isolated_recovery_session(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    tables = [
        GoJourneyRow.__table__,
        JourneyRecoveryPlanRow.__table__,
        JourneyRecoveryOptionRow.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(recovery_module, "SessionLocal", factory)
    monkeypatch.setattr(recovery_module, "now", lambda: FIXED_NOW)
    yield factory
    engine.dispose()


def _seed_journey(factory, *, journey_id=JOURNEY_ID, account_id=OWNER):
    with factory.begin() as session:
        session.add(
            GoJourneyRow(
                journey_id=journey_id,
                account_id=account_id,
                title="Recovery selection boundary",
                status="UPCOMING",
                created_at=FIXED_NOW,
                updated_at=FIXED_NOW,
            )
        )


def _seed_plan(factory, *, plan_id=PLAN_ID, journey_id=JOURNEY_ID, account_id=OWNER, expires_at=None):
    with factory.begin() as session:
        session.add(
            JourneyRecoveryPlanRow(
                plan_id=plan_id,
                journey_id=journey_id,
                account_id=account_id,
                advice_id=f"{plan_id}_advice",
                status="READY",
                currency="CNY",
                summary="Select only.",
                selected_option_ids_json=[],
                execution_boundary="SELECT_ONLY_NO_AUTO_MUTATION",
                expires_at=expires_at or (FIXED_NOW + timedelta(minutes=15)),
                created_at=FIXED_NOW,
                updated_at=FIXED_NOW,
            )
        )


def _seed_option(
    factory,
    *,
    option_id,
    impact_id,
    plan_id=PLAN_ID,
    journey_id=JOURNEY_ID,
    account_id=OWNER,
    status="AVAILABLE",
    expires_at=None,
):
    with factory.begin() as session:
        session.add(
            JourneyRecoveryOptionRow(
                option_id=option_id,
                plan_id=plan_id,
                journey_id=journey_id,
                account_id=account_id,
                impact_id=impact_id,
                vertical="HOTEL",
                order_id=f"{impact_id}_order",
                option_type="KEEP",
                title=f"Option {option_id}",
                subtitle="No auto execution.",
                total_delta_minor=0,
                currency="CNY",
                rank_score=100,
                status=status,
                execution_route="hotel.keep",
                requires_user_confirmation=False,
                quote_facts_json={},
                expires_at=expires_at or (FIXED_NOW + timedelta(minutes=10)),
                created_at=FIXED_NOW,
            )
        )


def _plan(factory, plan_id=PLAN_ID):
    with factory() as session:
        return session.get(JourneyRecoveryPlanRow, plan_id)


def test_select_rejects_expired_option_without_marking_plan_selected(isolated_recovery_session):
    _seed_journey(isolated_recovery_session)
    _seed_plan(isolated_recovery_session, expires_at=FIXED_NOW + timedelta(minutes=5))
    _seed_option(isolated_recovery_session, option_id="expired_lt", impact_id="impact_lt", expires_at=FIXED_NOW - timedelta(seconds=1))
    _seed_option(isolated_recovery_session, option_id="expired_eq", impact_id="impact_eq", expires_at=FIXED_NOW)

    with pytest.raises(ValueError, match="^RECOVERY_OPTION_NOT_AVAILABLE$"):
        recovery_module.journey_recovery_service.select(OWNER, JOURNEY_ID, PLAN_ID, ["expired_lt"])
    with pytest.raises(ValueError, match="^RECOVERY_OPTION_NOT_AVAILABLE$"):
        recovery_module.journey_recovery_service.select(OWNER, JOURNEY_ID, PLAN_ID, ["expired_eq"])

    plan = _plan(isolated_recovery_session)
    assert plan.status == "READY"
    assert plan.selected_option_ids_json == []
    assert recovery_module.as_utc(plan.updated_at) == FIXED_NOW


def test_select_allows_valid_option_and_preserves_existing_rejections(isolated_recovery_session):
    _seed_journey(isolated_recovery_session)
    _seed_journey(isolated_recovery_session, journey_id=OTHER_JOURNEY_ID, account_id=OTHER)
    _seed_plan(isolated_recovery_session)
    _seed_plan(
        isolated_recovery_session,
        plan_id=OTHER_PLAN_ID,
        journey_id=OTHER_JOURNEY_ID,
        account_id=OTHER,
        expires_at=FIXED_NOW + timedelta(minutes=20),
    )
    _seed_option(isolated_recovery_session, option_id="valid", impact_id="impact_a", expires_at=FIXED_NOW + timedelta(minutes=1))
    _seed_option(isolated_recovery_session, option_id="same_impact_2", impact_id="impact_a", expires_at=FIXED_NOW + timedelta(minutes=1))
    _seed_option(
        isolated_recovery_session,
        option_id="other_plan_option",
        impact_id="impact_b",
        plan_id=OTHER_PLAN_ID,
        journey_id=OTHER_JOURNEY_ID,
        account_id=OTHER,
        expires_at=FIXED_NOW + timedelta(minutes=1),
    )

    with pytest.raises(ValueError, match="^RECOVERY_OPTION_NOT_AVAILABLE$"):
        recovery_module.journey_recovery_service.select(OWNER, JOURNEY_ID, PLAN_ID, ["other_plan_option"])
    with pytest.raises(ValueError, match="^ONE_OPTION_PER_IMPACT$"):
        recovery_module.journey_recovery_service.select(OWNER, JOURNEY_ID, PLAN_ID, ["valid", "same_impact_2"])
    with pytest.raises(ValueError, match="^JOURNEY_NOT_FOUND$"):
        recovery_module.journey_recovery_service.select(OTHER, JOURNEY_ID, PLAN_ID, ["valid"])

    result = recovery_module.journey_recovery_service.select(OWNER, JOURNEY_ID, PLAN_ID, ["valid"])
    assert result["status"] == "SELECTED"
    assert result["selected_options"][0]["option_id"] == "valid"
    assert result["auto_mutation_performed"] is False
    assert result["next_step"] == "EXECUTE_EACH_OPTION_VIA_VERTICAL_WORKFLOW"

    plan = _plan(isolated_recovery_session)
    assert plan.status == "SELECTED"
    assert plan.selected_option_ids_json == ["valid"]
