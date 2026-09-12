import os,sqlite3,subprocess,sys
import pytest

def setup(tmp_path):
    db=tmp_path/'credit_exclusion.db'
    with sqlite3.connect(db) as c:
        c.execute('create table catalog_credit_source (capture_id text primary key,credit_id text,payment_intent_id text,funded_minor integer,prior_refund_minor integer)')
        c.execute("insert into catalog_credit_source values ('old-capture','old-credit','old-intent',1443200,0)")
    env={**os.environ,'DATABASE_URL':f'sqlite+pysqlite:///{db}','PYTHONPATH':'src'}
    def run(*args,check=True):return subprocess.run([sys.executable,'-m','alembic',*args],env=env,text=True,capture_output=True,check=check)
    run('stamp','0122_catalog_cash_fare');run('upgrade','0123_catalog_credit_exclusion')
    return db,run

@pytest.mark.no_db
def test_source_exclusion_migration_roundtrip_preserves_old_full_capture_allocation(tmp_path):
    db,run=setup(tmp_path)
    with sqlite3.connect(db) as c:
        assert c.execute('select funded_minor,prior_refund_minor,excluded_minor from catalog_credit_source').fetchone()==(1443200,0,0)
    run('downgrade','0122_catalog_cash_fare')
    with sqlite3.connect(db) as c:
        assert c.execute('select funded_minor,prior_refund_minor from catalog_credit_source').fetchone()==(1443200,0)
    run('upgrade','0123_catalog_credit_exclusion')

@pytest.mark.no_db
def test_downgrade_cannot_drop_a_nonzero_exclusion_and_revive_forfeited_source_value(tmp_path):
    db,run=setup(tmp_path)
    with sqlite3.connect(db) as c:c.execute('update catalog_credit_source set funded_minor=1400000,excluded_minor=43200')
    rejected=run('downgrade','0122_catalog_cash_fare',check=False)
    assert rejected.returncode!=0 and 'CREDIT_EXCLUSION_DATA_REQUIRES_RECONCILED_ROLLBACK' in rejected.stderr
    with sqlite3.connect(db) as c:
        assert c.execute('select funded_minor,excluded_minor from catalog_credit_source').fetchone()==(1400000,43200)
        assert c.execute('select version_num from alembic_version').fetchone()[0]=='0123_catalog_credit_exclusion'
