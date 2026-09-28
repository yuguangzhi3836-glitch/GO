from copy import deepcopy
from sqlalchemy import select
from test_payment_sandbox_audit_integrity import audit
from test_hosted_room_registry import rooms
from go_hotel.db.models import HostedDirectInventoryPoolRow as Pool


def test_waiting_writer_must_refresh_probe_before_cas(rooms):
    sessions,_=rooms
    with sessions() as waiting:
        probe=waiting.get(Pool,'pool-a')
        assert probe.room_details_json['room_registry']['version']==1
        # Models another writer committing while the first awaits its hotel lock.
        with sessions.begin() as writer:
            pool=writer.get(Pool,'pool-a');updated=deepcopy(pool.room_details_json)
            updated['room_registry']['version']=2;pool.room_details_json=updated
        # Exact pool query shape from initial configure_isolated_registry.
        pools=list(waiting.scalars(select(Pool).where(Pool.hosted_hotel_id=='isolated-hotel')
            .order_by(Pool.inventory_pool_id).with_for_update()))
        pool=next(row for row in pools if row.inventory_pool_id=='pool-a')
        assert pool is probe
        assert pool.room_details_json['room_registry']['version']==2, 'Cached pre-lock probe masks the committed version and permits a stale CAS'
