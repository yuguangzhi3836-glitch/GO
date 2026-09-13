import os,sqlite3,subprocess,sys
import pytest

@pytest.mark.no_db
def test_fare_migration_roundtrip_preserves_prior_tables_and_does_not_fabricate_snapshots(tmp_path):
    db=tmp_path/'fare_migration.db'
    with sqlite3.connect(db) as conn:
        conn.execute('create table hosted_direct_reservation (hosted_reservation_id varchar(64) primary key, amount_minor integer)')
        conn.execute("insert into hosted_direct_reservation values ('historical',162000)")
    env={**os.environ,'DATABASE_URL':f'sqlite+pysqlite:///{db}','PYTHONPATH':'src'}
    def run(*args):subprocess.run([sys.executable,'-m','alembic',*args],env=env,text=True,capture_output=True,check=True)
    run('stamp','0115_rental_change_settlement');run('upgrade','0116_hosted_fare_snapshot')
    with sqlite3.connect(db) as conn:
        assert conn.execute('select version_num from alembic_version').fetchone()[0]=='0116_hosted_fare_snapshot'
        assert conn.execute('select count(*) from hosted_order_fare_snapshot').fetchone()[0]==0
        assert conn.execute('select * from hosted_direct_reservation').fetchone()==('historical',162000)
        conn.execute("insert into hosted_fare_rule_version values ('v1','o1',1,'{}','hash','test://authority','hotel','2026-09-07')")
        with pytest.raises(sqlite3.IntegrityError):conn.execute("insert into hosted_fare_rule_version values ('v2','o1',1,'{}','hash','test://authority','hotel','2026-09-07')")
    run('downgrade','0115_rental_change_settlement')
    with sqlite3.connect(db) as conn:
        assert conn.execute('select * from hosted_direct_reservation').fetchone()==('historical',162000)
        assert not conn.execute("select name from sqlite_master where name like 'hosted_fare_%'").fetchall()
    run('upgrade','0116_hosted_fare_snapshot')
