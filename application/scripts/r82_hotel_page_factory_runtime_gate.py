#!/usr/bin/env python3
from __future__ import annotations
import os, shutil, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
work=Path(tempfile.mkdtemp(prefix='go-r82-factory-gate-'))
os.environ['DATABASE_URL']=f"sqlite+pysqlite:///{work/'factory.db'}"
os.environ['GO_MEDIA_CACHE_DIR']=str(work/'media')
sys.path.insert(0,str(ROOT/'src'))
try:
    from go_hotel.db.models import Base
    from go_hotel.db.session import engine
    Base.metadata.create_all(engine)
    from go_hotel.services.hotel_autopage_factory import hotel_autopage_factory_service as svc
    r=svc.ingest({'source_key':'official:gate','source_type':'OFFICIAL_WEBSITE','external_hotel_id':'gate-1','rights_status':'PUBLIC_BUSINESS_FACT','confidence_bps':9000,'payload':{'name':'RC12 Gate Hotel','address':'Gate Address','website':'https://example.com','rooms':[{'name':'King'}],'contacts':[{'channel':'EMAIL','value':'gate@example.com','is_public_business_contact':True}]}},'gate')
    hid=r['profile']['hotel_id']; slug=r['profile']['slug']
    overview=svc.factory_overview(10)
    assert overview['total_hotels']==1 and overview['items'][0]['hotel_id']==hid
    detail=svc.factory_detail(hid)
    assert detail['factory']['source_count']==1
    assert detail['factory']['room_count']==1
    assert detail['factory']['contact_count']==1
    svc.set_publication(hid,'UNPUBLISH','gate')
    try: svc.public_page(slug)
    except ValueError as exc: assert str(exc)=='HOTEL_PAGE_NOT_PUBLISHED'
    else: raise AssertionError('UNPUBLISH_NOT_FAIL_CLOSED')
    svc.set_publication(hid,'PUBLISH','gate')
    assert svc.public_page(slug)['identity']['name']=='RC12 Gate Hotel'
    print('factory_overview_runtime=PASS')
    print('factory_detail_runtime=PASS')
    print('publication_unpublish_fail_closed=PASS')
    print('publication_republish_runtime=PASS')
    print('R8.2_HOTEL_PAGE_FACTORY_RUNTIME_GATE: PASS')
finally:
    shutil.rmtree(work,ignore_errors=True)
