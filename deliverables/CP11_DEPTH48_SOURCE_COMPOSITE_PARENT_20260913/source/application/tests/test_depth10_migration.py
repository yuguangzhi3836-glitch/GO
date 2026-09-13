import os,sqlite3,subprocess,sys
import pytest

@pytest.mark.no_db
def test_supplier_fault_migration_roundtrip_preserves_original_credit_and_allocations(tmp_path):
    db=tmp_path/'supplier_fault_migration.db'
    with sqlite3.connect(db) as c:
        c.execute('create table hosted_stay_credit (credit_id text primary key, available_minor integer)')
        c.execute("insert into hosted_stay_credit values ('funded-credit',162000)")
        c.execute('create table hosted_credit_allocation (reservation_id text primary key, state text)')
        c.execute("insert into hosted_credit_allocation values ('historical-reservation','ACTIVE')")
    env={**os.environ,'DATABASE_URL':f'sqlite+pysqlite:///{db}','PYTHONPATH':'src'}
    def run(*args):subprocess.run([sys.executable,'-m','alembic',*args],env=env,text=True,capture_output=True,check=True)
    run('stamp','0117_hosted_stay_credit');run('upgrade','0118_hosted_supplier_disruption')
    with sqlite3.connect(db) as c:
        for name in ['hosted_supplier_disruption','hosted_fault_debit_mandate','hosted_fault_recovery']:
            assert c.execute('select count(*) from '+name).fetchone()[0]==0
    run('downgrade','0117_hosted_stay_credit')
    with sqlite3.connect(db) as c:
        assert not c.execute("select name from sqlite_master where name in ('hosted_supplier_disruption','hosted_fault_debit_mandate','hosted_fault_recovery')").fetchall()
        assert c.execute('select * from hosted_stay_credit').fetchone()==('funded-credit',162000)
        assert c.execute('select * from hosted_credit_allocation').fetchone()==('historical-reservation','ACTIVE')
    run('upgrade','0118_hosted_supplier_disruption')
