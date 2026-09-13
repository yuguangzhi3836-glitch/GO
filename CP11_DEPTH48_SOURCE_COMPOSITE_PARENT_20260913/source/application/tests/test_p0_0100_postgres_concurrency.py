import os,threading,uuid
import pytest
from sqlalchemy import create_engine,select
from sqlalchemy.orm import sessionmaker
from go_hotel.db.models import OmnichannelPaymentIntentRow as Intent,PaymentOrderRootRow as Root

pytestmark=[pytest.mark.postgres,pytest.mark.concurrency]
URL=os.getenv('POSTGRES_TEST_DATABASE_URL')

@pytest.mark.skipif(not URL,reason='POSTGRES_TEST_DATABASE_URL not configured')
def test_order_payment_root_unique_under_postgres_race():
    """The 0099/0100 root uniqueness must be proven by PostgreSQL, not SQLite scheduling."""
    eng=create_engine(URL,pool_pre_ping=True);Session=sessionmaker(bind=eng,expire_on_commit=False)
    business_id='pg-race-'+uuid.uuid4().hex;barrier=threading.Barrier(2);results=[]
    def worker(n):
        try:
            with Session() as s:
                barrier.wait(timeout=5)
                r=Root(payment_order_root_id='por-'+uuid.uuid4().hex,business_type='HOTEL_ORDER',business_id=business_id,payment_intent_id='pi-'+uuid.uuid4().hex,legal_entity_id='GO_CN',state='ACTIVE',root_hash=uuid.uuid4().hex,created_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc));s.add(r);s.commit();results.append('COMMIT')
        except Exception:results.append('REJECT')
    ts=[threading.Thread(target=worker,args=(x,)) for x in range(2)]
    [t.start() for t in ts];[t.join(10) for t in ts]
    assert results.count('COMMIT')==1 and results.count('REJECT')==1
