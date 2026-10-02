"""Latest independent award must preserve unpaid compensation obligations."""
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import select,func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OmnichannelMoneyMovementRow as Movement
from go_hotel.services import rental_deposit_money as service
from go_hotel.mobility.rental import damage,deposit_authority as authority
from tests.payments.test_c11_rental_deposit_money import obligation,args,decide,settle,OWNER,CHECKER,principal,ev
from tests.payments.test_c11_deposit_compensation import appeal,execute


@pytest.mark.parametrize('paid,target,expected_compensation',[(False,5000,5000),(False,4000,6000),(True,5000,5000)])
def test_maintained_or_lower_award_uses_actual_net_capture(obligation,paid,target,expected_compensation):
    service.authorize(CHECKER,*args(obligation));first=decide(obligation,10000);settle(obligation,first)
    second=appeal(obligation,first,5000)
    if paid:execute(obligation,second)
    latest=appeal(obligation,second,target,'third-checker')
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:execute(obligation,latest),range(2)))
    assert results[0]==results[1]
    final=service.status(OWNER,*args(obligation))
    assert final['net_captured_minor']==target and final['compensated_minor']==expected_compensation
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(Movement).where(Movement.movement_type=='COMPENSATION'))==1
    with pytest.raises(ValueError,match='VERSION_CONFLICT'):execute(obligation,second)


def test_maintained_award_retry_after_atomic_money_failure(obligation,monkeypatch):
    service.authorize(CHECKER,*args(obligation));first=decide(obligation,10000);settle(obligation,first)
    second=appeal(obligation,first,5000);latest=appeal(obligation,second,5000,'third-checker')
    post=service.money._post
    def interrupted(session,intent,movement):
        post(session,intent,movement)
        raise RuntimeError('after posting before commit')
    monkeypatch.setattr(service.money,'_post',interrupted)
    with pytest.raises(RuntimeError):execute(obligation,latest)
    assert service.status(OWNER,*args(obligation))['net_captured_minor']==10000
    monkeypatch.setattr(service.money,'_post',post)
    assert execute(obligation,latest)['net_captured_minor']==5000


def test_unknown_compensation_still_blocks_maintained_award(obligation):
    service.authorize(CHECKER,*args(obligation));first=decide(obligation,10000);settle(obligation,first)
    second=appeal(obligation,first,5000);execute(obligation,second)
    latest=appeal(obligation,second,5000,'third-checker')
    with SessionLocal.begin() as s:
        s.scalar(select(Movement).where(Movement.movement_type=='COMPENSATION')).state='UNKNOWN_EXTERNAL_STATE'
    with pytest.raises(ValueError,match='RECONCILIATION_REQUIRED'):execute(obligation,latest)
    assert service.status(OWNER,*args(obligation))['net_captured_minor'] is None
