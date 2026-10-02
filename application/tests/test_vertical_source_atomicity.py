"""A source-write failure must not leave a booked order behind a released key."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import MobilityRideOrderRow as Ride, VerticalSourceDecisionRow as Decision, IdempotencyRow
from go_hotel.api.routes.mobility import rb, RideBook
from go_hotel.mobility.ride.service import ride_service
from go_hotel.services import vertical_source_runtime as source
from ride_cancellation_fixture import synthetic_policy, accepted_body

def test_source_failure_rolls_back_order_before_same_key_retry(monkeypatch):
    owner='source-atomicity-owner'; key='source-atomicity-key'
    body={'offer_id':'ride_standard','pickup':'ISOLATED_A','dropoff':'ISOLATED_B',
          'pickup_at':(datetime.now(timezone.utc)+timedelta(days=10)).isoformat(),
          'passengers':[{'full_name':'SYNTHETIC'}]}
    original=source.insert_once
    def fail_after_insert(*args,**kwargs):
        original(*args,**kwargs)
        raise RuntimeError('SOURCE_WRITE_FAILED')
    with synthetic_policy():
        request=RideBook(**accepted_body(ride_service,body)); principal=SimpleNamespace(user_id=owner)
        with monkeypatch.context() as m:
            m.setattr(source,'insert_once',fail_after_insert)
            with pytest.raises(RuntimeError,match='SOURCE_WRITE_FAILED'):rb(request,principal,key)
        with SessionLocal() as s:
            assert not list(s.scalars(select(Ride).where(Ride.account_id==owner))), 'ORDER_SURVIVED_FAILED_CREATE'
            assert not list(s.scalars(select(Decision).where(Decision.vertical=='RIDE')))
            assert s.get(IdempotencyRow,{'operation':'RIDE_CREATE_ORDER','idempotency_key':key}) is None
        result=rb(request,principal,key)
        assert rb(request,principal,key)==result
    with SessionLocal() as s:
        orders=list(s.scalars(select(Ride).where(Ride.account_id==owner)))
        assert len(orders)==1 and orders[0].order_id==result['data']['order_id']
        decisions=list(s.scalars(select(Decision).where(Decision.vertical=='RIDE',Decision.business_id==orders[0].order_id)))
        assert len(decisions)==1 and decisions[0].route=='OFFICIAL_DIRECT'

@pytest.mark.parametrize('vertical',['RENTAL','ATTRACTION'])
def test_source_failure_rolls_back_native_order_and_inventory(monkeypatch,vertical):
    from go_hotel.db.models import MobilityRentalOrderRow, AttractionOrderRow, VerticalCapacityClaimRow
    from go_hotel.mobility.rental.service import rental_service
    from test_depth23_capacity import attr_quote,order,ledger
    owner='source-atomicity-owner'
    if vertical=='RENTAL':
        model=MobilityRentalOrderRow
        body={'offer_id':'rental_compact','pickup_location':'ISOLATED_A','return_location':'ISOLATED_A',
              'pickup_at':'2026-10-10T10:00:00+00:00','return_at':'2026-10-13T10:00:00+00:00'}
        create=lambda:rental_service.create(owner,body)
    else:
        model=AttractionOrderRow; quote=attr_quote(quantity=1)
        create=lambda:order('ATTRACTION',quote,owner)
    original=source.insert_once
    def fail_after_insert(*args,**kwargs):
        original(*args,**kwargs)
        raise RuntimeError('SOURCE_WRITE_FAILED')
    with monkeypatch.context() as m:
        m.setattr(source,'insert_once',fail_after_insert)
        with pytest.raises(RuntimeError,match='SOURCE_WRITE_FAILED'):create()
    with SessionLocal() as s:
        assert not list(s.scalars(select(model).where(model.account_id==owner)))
        assert not list(s.scalars(select(Decision).where(Decision.vertical==vertical)))
        assert not list(s.scalars(select(VerticalCapacityClaimRow).where(VerticalCapacityClaimRow.vertical==vertical)))
    if vertical=='ATTRACTION':assert ledger()==0
    result=create()
    if vertical=='ATTRACTION':
        assert create()==result
        assert ledger()==1
    with SessionLocal() as s:
        assert len(list(s.scalars(select(model).where(model.account_id==owner))))==1
        assert len(list(s.scalars(select(Decision).where(Decision.vertical==vertical,Decision.business_id==result['order_id']))))==1
