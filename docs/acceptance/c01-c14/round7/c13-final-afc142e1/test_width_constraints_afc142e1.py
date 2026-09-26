"""Independent named uniqueness and row preservation across five-column repair."""
from pathlib import Path
from datetime import datetime,timezone
import importlib.util
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from alembic.migration import MigrationContext
from alembic.operations import Operations
from go_hotel.db.models import OmnichannelMerchantBindingRow
pytestmark=pytest.mark.no_db

def test_merchant_binding_unique_constraint_survives_upgrade_and_downgrade(tmp_path):
 source=Path(__file__).resolve().parent/'candidate-afc142e1'/'application/alembic/versions/0139_hosted_publication_review.py'
 spec=importlib.util.spec_from_file_location('c13_frozen_width_migration',source);migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
 table=OmnichannelMerchantBindingRow.__table__.to_metadata(sa.MetaData());table.c.state.type=sa.String(24)
 engine=sa.create_engine('sqlite+pysqlite:///'+str(tmp_path/'independent-width.db'))
 with engine.begin() as connection:
  table.create(connection)
  row={'merchant_binding_id':'historic','owner_type':'HOTEL','owner_id':'synthetic-hotel','channel':'ALIPAY','market':'CN','merchant_reference':'synthetic','credential_reference':'isolated://none','webhook_key_reference':'isolated://none','capabilities_json':[],'state':'PENDING','updated_at':datetime.now(timezone.utc)}
  connection.execute(table.insert().values(**row))
  with Operations.context(MigrationContext.configure(connection)):
   migration.upgrade()
   for stage in ['UPGRADED','DOWNGRADED']:
    if stage=='DOWNGRADED':migration.downgrade()
    inspector=sa.inspect(connection)
    assert any(x['name']=='uq_omni_merchant_channel' and x['column_names']==['owner_type','owner_id','channel','market'] for x in inspector.get_unique_constraints(table.name))
    assert any(x['column_names']==['state'] for x in inspector.get_indexes(table.name))
    assert next(x for x in inspector.get_columns(table.name) if x['name']=='state')['type'].length==(64 if stage=='UPGRADED' else 24)
    assert connection.execute(sa.text('SELECT merchant_binding_id,state FROM omnichannel_merchant_binding')).one()==('historic','PENDING')
    with pytest.raises(IntegrityError):
     with connection.begin_nested():connection.execute(table.insert().values(**{**row,'merchant_binding_id':'duplicate'}))
 engine.dispose()
