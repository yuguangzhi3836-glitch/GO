"""Executable known-gap reproduction: committed side effect then callback error."""
import asyncio
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, Column, Integer, Table, MetaData, select, func
from sqlalchemy.orm import sessionmaker
from go_hotel.api import idempotency
from go_hotel.repositories import sql
from go_hotel.db.models import IdempotencyRow

@pytest.mark.parametrize("asynchronous", [False,True], ids=["sync","async"])
def test_post_commit_error_does_not_allow_duplicate_effect(monkeypatch, asynchronous):
    engine=create_engine("sqlite+pysqlite:///:memory:")
    sessions=sessionmaker(bind=engine)
    IdempotencyRow.__table__.create(engine)
    effects=Table("c11_committed_effect",MetaData(),Column("id",Integer,primary_key=True))
    effects.create(engine)
    monkeypatch.setattr(sql,"SessionLocal",sessions)
    repo=sql.SqlRepository()
    monkeypatch.setattr(idempotency,"repo",repo)
    errors=[]
    def callback():
        with sessions.begin() as session:
            session.execute(effects.insert())
        raise RuntimeError("CALLBACK_RESPONSE_FAILED_AFTER_COMMIT")
    async def async_callback():
        return callback()
    try:
        for _ in range(2):
            try:
                args=("C11_PROBE","fixed-key",{"amount_minor":100})
                if asynchronous:
                    asyncio.run(idempotency.run_idempotent_async(*args,async_callback))
                else:
                    idempotency.run_idempotent(*args,callback)
            except (RuntimeError,HTTPException) as exc:
                errors.append(type(exc).__name__)
        with sessions() as session:
            count=session.scalar(select(func.count()).select_from(effects))
        claim=repo.get_idempotency("C11_PROBE","fixed-key")
        print({"effects_committed":count,"claim_retained":claim is not None,"errors":errors})
        assert count == 1, "UNCERTAIN_CALLBACK_FAILURE_RELEASED_CLAIM_AND_DUPLICATED_COMMITTED_EFFECT"
    finally:
        engine.dispose()
