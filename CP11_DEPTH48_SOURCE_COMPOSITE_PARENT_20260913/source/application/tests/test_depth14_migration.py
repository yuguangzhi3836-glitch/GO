import os,sqlite3,subprocess,sys
import pytest

@pytest.mark.no_db
def test_cash_fare_migration_roundtrip_never_backfills_historical_consent(tmp_path):
    db=tmp_path/'cash_fare.db'
    with sqlite3.connect(db) as c:
        c.execute('create table order_change_runtime (change_id text primary key,status text)')
        c.execute("insert into order_change_runtime values ('historical-change','CONFIRMED')")
    env={**os.environ,'DATABASE_URL':f'sqlite+pysqlite:///{db}','PYTHONPATH':'src'}
    def run(*args):subprocess.run([sys.executable,'-m','alembic',*args],env=env,text=True,capture_output=True,check=True)
    run('stamp','0121_catalog_fare_snapshot');run('upgrade','0122_catalog_cash_fare')
    with sqlite3.connect(db) as c:
        for table in ['catalog_cash_fare_quote','catalog_cash_fare_operation','catalog_cash_fare_claim']:
            assert c.execute('select count(*) from '+table).fetchone()[0]==0
        assert c.execute('select * from order_change_runtime').fetchone()==('historical-change','CONFIRMED')
    run('downgrade','0121_catalog_fare_snapshot')
    with sqlite3.connect(db) as c:
        assert not c.execute("select name from sqlite_master where name like 'catalog_cash_fare%'").fetchall()
        assert c.execute('select * from order_change_runtime').fetchone()==('historical-change','CONFIRMED')
    run('upgrade','0122_catalog_cash_fare')
