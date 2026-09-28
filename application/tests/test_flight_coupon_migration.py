"""Exercise the actual additive migration on the isolated database engine."""
import importlib.util
from pathlib import Path
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect
from go_hotel.db.session import engine
from go_hotel.db.models import FlightCouponRow,FlightCouponRefundRow


def test_coupon_migration_upgrade_and_empty_downgrade(client):
    path=Path(__file__).parents[1]/'alembic/versions/0141_flight_coupons.py'
    spec=importlib.util.spec_from_file_location('coupon_migration',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with engine.begin() as connection:
        FlightCouponRefundRow.__table__.drop(connection)
        FlightCouponRow.__table__.drop(connection)
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            assert {'flight_coupon','flight_coupon_refund'}<=set(inspect(connection).get_table_names())
            assert inspect(connection).get_unique_constraints('flight_coupon')
            module.downgrade()
            assert 'flight_coupon' not in inspect(connection).get_table_names()
            module.upgrade()
