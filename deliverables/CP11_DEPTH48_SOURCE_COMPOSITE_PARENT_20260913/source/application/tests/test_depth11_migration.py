import os,sqlite3,subprocess,sys
import pytest

@pytest.mark.no_db
def test_catalog_remedy_migration_preserves_historical_cases_and_hosted_mandates(tmp_path):
    db=tmp_path/'catalog_remedy.db'
    with sqlite3.connect(db) as c:
        c.execute('create table supplier_fault_case (case_id text primary key, status text)')
        c.execute("insert into supplier_fault_case values ('historical','SUPPLIER_FAULT_CONFIRMED')")
        c.execute('create table hosted_fault_debit_mandate (mandate_id text primary key, state text)')
        c.execute("insert into hosted_fault_debit_mandate values ('hosted-authority','REVOKED')")
    env={**os.environ,'DATABASE_URL':f'sqlite+pysqlite:///{db}','PYTHONPATH':'src'}
    def run(*args):subprocess.run([sys.executable,'-m','alembic',*args],env=env,text=True,capture_output=True,check=True)
    run('stamp','0118_hosted_supplier_disruption');run('upgrade','0119_catalog_supplier_remedy')
    with sqlite3.connect(db) as c:
        for name in ['catalog_supplier_remedy','catalog_fault_debit_mandate','catalog_fault_recovery']:
            assert c.execute('select count(*) from '+name).fetchone()[0]==0
        assert c.execute('select * from supplier_fault_case').fetchone()==('historical','SUPPLIER_FAULT_CONFIRMED')
    run('downgrade','0118_hosted_supplier_disruption')
    with sqlite3.connect(db) as c:
        assert not c.execute("select name from sqlite_master where name like 'catalog_%'").fetchall()
        assert c.execute('select * from hosted_fault_debit_mandate').fetchone()==('hosted-authority','REVOKED')
    run('upgrade','0119_catalog_supplier_remedy')
