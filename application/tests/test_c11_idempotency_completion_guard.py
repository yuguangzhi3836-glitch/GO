"""Fault-injection coverage for the existing durable idempotency contract.

The repository double models CLAIMED / IN_PROGRESS / REPLAY; completion failures
are injected after the business callback has returned, not inside the callback.
This is a unit guard, not evidence of payment-provider or database acceptance.
"""
import asyncio

import pytest
from fastapi import HTTPException

from go_hotel.api import idempotency


pytestmark = pytest.mark.no_db


class ClaimRepository:
    def __init__(self):
        self.claim = None
        self.response = None
        self.release_calls = 0
        self.fail_completion = False

    def claim_idempotency(self, operation, key, payload):
        fingerprint = (operation, key, dict(payload))
        if self.claim is None:
            self.claim = fingerprint
            return "CLAIMED", None
        if self.claim != fingerprint:
            raise ValueError("IDEMPOTENCY_CONFLICT")
        if self.response is None:
            return "IN_PROGRESS", {"response_code": 102}
        return "REPLAY", {"response": self.response}

    def complete_idempotency(self, operation, key, payload, response, resource_id):
        if self.fail_completion:
            raise RuntimeError("RESPONSE_STORAGE_UNAVAILABLE")
        self.response = response

    def release_idempotency_claim(self, operation, key, payload):
        self.release_calls += 1
        if self.response is None:
            self.claim = None


@pytest.fixture
def claim_repo(monkeypatch):
    repo = ClaimRepository()
    monkeypatch.setattr(idempotency, "repo", repo)
    return repo


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def invoke(request):
    def run(fn, *, resource_id_fn=None, payload=None, key="request-1"):
        args = ("MUTATION", key, {"amount_minor": 100} if payload is None else payload)
        if not request.param:
            return idempotency.run_idempotent(*args, fn, resource_id_fn)

        async def async_fn():
            return fn()

        return asyncio.run(idempotency.run_idempotent_async(*args, async_fn, resource_id_fn))

    return run


@pytest.mark.parametrize("failure", ["completion_storage", "resource_id"])
def test_successful_mutation_keeps_claim_if_result_recording_fails(claim_repo, invoke, failure):
    side_effects = []

    def mutate():
        side_effects.append("performed")
        return {"order_id": "order-1"}

    def extract_resource_id(response):
        if failure == "resource_id":
            raise RuntimeError("RESOURCE_ID_EXTRACTION_FAILED")
        return response["order_id"]

    claim_repo.fail_completion = failure == "completion_storage"
    with pytest.raises(RuntimeError):
        invoke(mutate, resource_id_fn=extract_resource_id)

    assert side_effects == ["performed"]
    assert claim_repo.release_calls == 0
    claim_repo.fail_completion = False
    with pytest.raises(HTTPException) as retry:
        invoke(mutate)
    assert retry.value.status_code == 409
    assert retry.value.detail["code"] == "IDEMPOTENCY_IN_PROGRESS"
    assert side_effects == ["performed"]


def test_completed_result_is_replayed_without_second_mutation(claim_repo, invoke):
    side_effects = []

    def mutate():
        side_effects.append("performed")
        return {"order_id": "order-1"}

    assert invoke(mutate) == {"order_id": "order-1"}
    assert invoke(mutate) == {"order_id": "order-1"}
    assert side_effects == ["performed"]
    assert claim_repo.release_calls == 0


def test_callback_failure_preserves_existing_release_contract(claim_repo, invoke):
    def fail_before_result():
        raise ValueError("BUSINESS_VALIDATION_FAILED")

    with pytest.raises(ValueError, match="BUSINESS_VALIDATION_FAILED"):
        invoke(fail_before_result)
    assert claim_repo.claim is None
    assert claim_repo.release_calls == 1
    assert invoke(lambda: {"order_id": "order-1"}) == {"order_id": "order-1"}


def test_existing_in_progress_claim_blocks_callback(claim_repo, invoke):
    claim_repo.claim_idempotency("MUTATION", "request-1", {"amount_minor": 100})
    with pytest.raises(HTTPException) as blocked:
        invoke(lambda: pytest.fail("in-progress mutation must not execute"))
    assert blocked.value.status_code == 409
    assert blocked.value.detail["code"] == "IDEMPOTENCY_IN_PROGRESS"


def test_changed_payload_cannot_reuse_claim(claim_repo, invoke):
    invoke(lambda: {"order_id": "order-1"})
    with pytest.raises(HTTPException) as conflict:
        invoke(lambda: pytest.fail("conflicting mutation must not execute"), payload={"amount_minor": 200})
    assert conflict.value.status_code == 409
    assert conflict.value.detail["code"] == "IDEMPOTENCY_CONFLICT"


def test_production_key_requirement_is_retained(monkeypatch, claim_repo, invoke):
    monkeypatch.setattr(idempotency.settings, "app_env", "production")
    with pytest.raises(HTTPException) as missing:
        invoke(lambda: pytest.fail("keyless production mutation must not execute"), key=None)
    assert missing.value.status_code == 428
    assert claim_repo.claim is None


def test_real_sql_claim_survives_failure_and_replays_after_reconciliation(monkeypatch, invoke):
    """Exercise real claim persistence in an exclusively owned in-memory DB."""
    from sqlalchemy import Column, Integer, MetaData, Table, create_engine, func, select
    from sqlalchemy.orm import sessionmaker
    from go_hotel.db.models import IdempotencyRow
    from go_hotel.repositories import sql

    engine = create_engine("sqlite+pysqlite:///:memory:")
    sessions = sessionmaker(bind=engine)
    IdempotencyRow.__table__.create(engine)
    mutations = Table("test_c11_mutations", MetaData(), Column("id", Integer, primary_key=True))
    mutations.create(engine)
    monkeypatch.setattr(sql, "SessionLocal", sessions)
    real_repo = sql.SqlRepository()
    monkeypatch.setattr(idempotency, "repo", real_repo)
    complete = real_repo.complete_idempotency

    def completion_unavailable(*args, **kwargs):
        raise RuntimeError("RESPONSE_STORAGE_UNAVAILABLE")

    def mutate():
        with sessions.begin() as session:
            session.execute(mutations.insert())
        return {"order_id": "order-1"}

    try:
        monkeypatch.setattr(real_repo, "complete_idempotency", completion_unavailable)
        with pytest.raises(RuntimeError, match="RESPONSE_STORAGE_UNAVAILABLE"):
            invoke(mutate)
        record = real_repo.get_idempotency("MUTATION", "request-1")
        assert record is not None and record["response_code"] == 102
        with pytest.raises(HTTPException) as blocked:
            invoke(mutate)
        assert blocked.value.detail["code"] == "IDEMPOTENCY_IN_PROGRESS"
        with sessions() as session:
            assert session.scalar(select(func.count()).select_from(mutations)) == 1

        # Explicit reconciliation uses the existing completion primitive; this
        # test does not claim that an automatic reconciliation worker exists.
        complete("MUTATION", "request-1", {"amount_minor": 100}, {"order_id": "order-1"}, "order-1")
        assert invoke(lambda: pytest.fail("reconciled mutation must replay")) == {"order_id": "order-1"}
    finally:
        engine.dispose()
