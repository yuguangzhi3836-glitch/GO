"""Fault injection models a worker's stale ORM state before it acquires its lock.

SQLite's BEGIN IMMEDIATE otherwise hides this PostgreSQL READ COMMITTED window.
The competing state is written through SQL on the test connection; this is not
a PostgreSQL concurrency acceptance claim.
"""
import pytest
from sqlalchemy import event, update
from sqlalchemy.orm import sessionmaker

from go_hotel.db.models import (RideFlightAdjustmentRow as Adjustment,
    MobilityRideOrderRow as Ride, RideFlightBindingV2Row as Binding)
from go_hotel.db.session import engine, SessionLocal
from go_hotel.mobility.ride.flight_sync import FlightRideSync
from go_hotel.mobility.ride.isolated_fleet import IsolatedFleetAdapter
from test_depth19_ride_sync import authority, seed_ride, proposal


@pytest.mark.parametrize('competing_status', ['DISPATCHED', 'UNKNOWN'])
def test_stale_pending_snapshot_never_resends_dispatched_fleet_intent(tmp_path, competing_status):
    auth = authority()
    ride, identity = seed_ride(auth)
    aid = proposal(auth, ride, identity)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    injected = []

    def competing_transition(session, instance):
        if isinstance(instance, Adjustment) and instance.adjustment_id == aid and not injected:
            assert instance.status == 'PENDING'
            session.connection().execute(update(Adjustment).where(
                Adjustment.adjustment_id == aid).values(status=competing_status))
            # The ORM identity remains stale although durable state has moved.
            assert instance.status == 'PENDING'
            injected.append(True)

    event.listen(factory, 'loaded_as_persistent', competing_transition)

    class QueryOnly(IsolatedFleetAdapter):
        execute_calls = 0
        query_calls = 0

        def execute(self, *args):
            self.execute_calls += 1
            return super().execute(*args)

        def query(self, *args):
            self.query_calls += 1
            return super().query(*args)

    adapter = QueryOnly(tmp_path / 'fleet.db')
    result = FlightRideSync(factory).process(aid, adapter)
    assert injected == [True]
    assert adapter.execute_calls == 0
    assert adapter.query_calls == 1
    assert result['status'] == 'UNKNOWN'
    with SessionLocal() as session:
        assert session.get(Adjustment, aid).status == 'UNKNOWN'


@pytest.mark.parametrize('late_status', ['CONFIRMED', 'REJECTED'])
def test_late_query_cannot_overwrite_another_workers_confirmed_result(tmp_path, late_status):
    auth = authority()
    ride, identity = seed_ride(auth)
    aid = proposal(auth, ride, identity)

    class LostReply(IsolatedFleetAdapter):
        def execute(self, *args):
            super().execute(*args)
            raise TimeoutError('provider committed before lost response')

    path = tmp_path / 'fleet.db'
    assert FlightRideSync().process(aid, LostReply(path))['status'] == 'UNKNOWN'
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    loads = []

    def competing_confirmation(session, instance):
        if not isinstance(instance, Adjustment) or instance.adjustment_id != aid:
            return
        loads.append(instance.status)
        if len(loads) != 2:
            return
        assert instance.status == 'UNKNOWN'
        connection = session.connection()
        connection.execute(update(Adjustment).where(Adjustment.adjustment_id == aid).values(
            status='CONFIRMED', provider_reference='isolated-fleet:' + aid))
        connection.execute(update(Ride).where(Ride.order_id == ride['order_id']).values(
            pickup_at=instance.proposed_pickup_at))
        connection.execute(update(Binding).where(Binding.ride_order_id == ride['order_id']).values(
            current_pickup_at=instance.proposed_pickup_at))
        assert instance.status == 'UNKNOWN'

    event.listen(factory, 'loaded_as_persistent', competing_confirmation)

    class LateQuery(IsolatedFleetAdapter):
        def execute(self, *args):
            pytest.fail('An uncertain dispatch must only query')

        def query(self, *args):
            return super().query(*args) | {'status': late_status}

    result = FlightRideSync(factory).process(aid, LateQuery(path))
    assert loads == ['UNKNOWN', 'UNKNOWN']
    assert result['status'] == 'CONFIRMED'
    with SessionLocal() as session:
        row = session.get(Adjustment, aid)
        assert row.status == 'CONFIRMED'
        assert session.get(Ride, ride['order_id']).pickup_at == row.proposed_pickup_at
