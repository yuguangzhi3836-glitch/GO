import os,sqlite3,subprocess,sys
import pytest

@pytest.mark.no_db
def test_credit_migration_roundtrip_preserves_fare_rows_and_never_creates_unfunded_credit(tmp_path):
    db=tmp_path/'credit_migration.db'
    with sqlite3.connect(db) as c:
        c.execute('create table hosted_fare_quote (quote_id text primary key, quote_hash text)')
        c.execute("insert into hosted_fare_quote values ('historical','unchanged')")
    env={**os.environ,'DATABASE_URL':f'sqlite+pysqlite:///{db}','PYTHONPATH':'src'}
    def run(*args):subprocess.run([sys.executable,'-m','alembic',*args],env=env,text=True,capture_output=True,check=True)
    run('stamp','0116_hosted_fare_snapshot');run('upgrade','0117_hosted_stay_credit')
    with sqlite3.connect(db) as c:
        for name in ['hosted_stay_credit','hosted_credit_allocation','hosted_credit_value_event','hosted_credit_refund_plan']:
            assert c.execute('select count(*) from '+name).fetchone()[0]==0
        assert 'fulfilled_minor' in {x[1] for x in c.execute('pragma table_info(hosted_credit_allocation)')}
        assert c.execute('select * from hosted_fare_quote').fetchone()==('historical','unchanged')
    run('downgrade','0116_hosted_fare_snapshot')
    with sqlite3.connect(db) as c:
        assert not c.execute("select name from sqlite_master where name like 'hosted_credit_%' or name='hosted_stay_credit'").fetchall()
        assert c.execute('select * from hosted_fare_quote').fetchone()==('historical','unchanged')
    run('upgrade','0117_hosted_stay_credit')
