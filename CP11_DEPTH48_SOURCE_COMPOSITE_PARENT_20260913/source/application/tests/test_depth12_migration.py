import os,sqlite3,subprocess,sys
import pytest

@pytest.mark.no_db
def test_catalog_credit_migration_preserves_historical_credit_without_invented_funding(tmp_path):
    db=tmp_path/'catalog_credit.db'
    with sqlite3.connect(db) as c:
        c.execute('create table stay_credit_runtime (stay_credit_id text primary key, status text, credit_value_minor integer)')
        c.execute("insert into stay_credit_runtime values ('historical','ACTIVE',12345)")
        c.execute('create table catalog_supplier_remedy (case_id text primary key, decision_hash text)')
        c.execute("insert into catalog_supplier_remedy values ('existing-case','decision-fingerprint')")
    env={**os.environ,'DATABASE_URL':f'sqlite+pysqlite:///{db}','PYTHONPATH':'src'}
    def run(*args):subprocess.run([sys.executable,'-m','alembic',*args],env=env,text=True,capture_output=True,check=True)
    run('stamp','0119_catalog_supplier_remedy');run('upgrade','0120_catalog_stay_credit')
    with sqlite3.connect(db) as c:
        for name in ['catalog_credit_contract','catalog_credit_source','catalog_credit_quote','catalog_credit_allocation','catalog_credit_value_event']:
            assert c.execute('select count(*) from '+name).fetchone()[0]==0
        assert c.execute('select * from stay_credit_runtime').fetchone()==('historical','ACTIVE',12345)
    run('downgrade','0119_catalog_supplier_remedy')
    with sqlite3.connect(db) as c:
        assert not c.execute("select name from sqlite_master where name like 'catalog_credit_%'").fetchall()
        assert c.execute('select * from catalog_supplier_remedy').fetchone()==('existing-case','decision-fingerprint')
    run('upgrade','0120_catalog_stay_credit')
