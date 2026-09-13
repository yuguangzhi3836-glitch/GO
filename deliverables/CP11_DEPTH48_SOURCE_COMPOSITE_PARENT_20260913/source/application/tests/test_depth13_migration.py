import os,sqlite3,subprocess,sys
import pytest

@pytest.mark.no_db
def test_rule_snapshot_migration_preserves_historical_credit_and_order_without_fabrication(tmp_path):
    db=tmp_path/'fare_snapshots.db'
    with sqlite3.connect(db) as c:
        c.execute('create table catalog_credit_contract (credit_id text primary key,contract_hash text)')
        c.execute("insert into catalog_credit_contract values ('old-credit','frozen-contract')")
        c.execute('create table hotel_order_runtime (order_id text primary key,status text)')
        c.execute("insert into hotel_order_runtime values ('old-order','CONFIRMED')")
    env={**os.environ,'DATABASE_URL':f'sqlite+pysqlite:///{db}','PYTHONPATH':'src'}
    def run(*args):subprocess.run([sys.executable,'-m','alembic',*args],env=env,text=True,capture_output=True,check=True)
    run('stamp','0120_catalog_stay_credit');run('upgrade','0121_catalog_fare_snapshot')
    with sqlite3.connect(db) as c:
        for name in ['catalog_fare_family','catalog_fare_rule_version','catalog_offer_fare_snapshot','catalog_order_fare_snapshot']:
            assert c.execute('select count(*) from '+name).fetchone()[0]==0
        assert c.execute('select * from catalog_credit_contract').fetchone()==('old-credit','frozen-contract')
    run('downgrade','0120_catalog_stay_credit')
    with sqlite3.connect(db) as c:
        assert c.execute('select * from hotel_order_runtime').fetchone()==('old-order','CONFIRMED')
        assert not c.execute("select name from sqlite_master where name like 'catalog_%fare%'").fetchall()
    run('upgrade','0121_catalog_fare_snapshot')
