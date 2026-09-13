import os,sqlite3,subprocess,sys
import pytest

@pytest.mark.no_db
def test_rental_settlement_migration_roundtrip_preserves_existing_refunds(tmp_path):
    db=tmp_path/'migration.db'
    with sqlite3.connect(db) as conn:
        conn.execute('create table mobility_refund_runtime (refund_id varchar(64) primary key, status varchar(32) not null)')
        conn.execute("insert into mobility_refund_runtime values ('old-refund','REFUND_COMPLETED')")
    env={**os.environ,'DATABASE_URL':f'sqlite+pysqlite:///{db}','PYTHONPATH':'src'}
    def alembic(*args):
        return subprocess.run([sys.executable,'-m','alembic',*args],env=env,text=True,capture_output=True,check=True)
    alembic('stamp','0114_ext_truth_incident_hard');alembic('upgrade','0115_rental_change_settlement')
    with sqlite3.connect(db) as conn:
        assert conn.execute('select version_num from alembic_version').fetchone()[0]=='0115_rental_change_settlement'
        assert conn.execute('select settlement_plan_json from mobility_refund_runtime').fetchone()[0]=='[]'
        columns={r[1] for r in conn.execute('pragma table_info(rental_change_quote)')}
        assert {'quote_id','order_revision','difference_minor','refund_plan_json'}<=columns
    alembic('downgrade','0114_ext_truth_incident_hard')
    with sqlite3.connect(db) as conn:
        assert conn.execute('select * from mobility_refund_runtime').fetchone()==('old-refund','REFUND_COMPLETED')
        assert not conn.execute("select name from sqlite_master where name='rental_change_quote'").fetchone()
    alembic('upgrade','0115_rental_change_settlement')
