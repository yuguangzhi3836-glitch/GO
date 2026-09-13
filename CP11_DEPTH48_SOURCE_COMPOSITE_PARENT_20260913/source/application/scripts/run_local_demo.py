#!/usr/bin/env python3
"""Run an isolated GO acceptance copy. No production credentials or database are used."""
import argparse
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,default=ROOT/'runtime_data'/'local_demo')
    parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--check',action='store_true',help='Exercise app routes in process without starting a web server')
    args=parser.parse_args()
    if os.environ.get('APP_ENV','local').lower() not in {'local','test','demo'}:
        parser.error('Refusing a non-local application environment')
    data=args.data_dir.resolve();data.mkdir(parents=True,exist_ok=True)
    os.environ.update(APP_ENV='demo',DATABASE_URL=f'sqlite+pysqlite:///{data / "go_demo.sqlite3"}',
        OUTBOX_TRANSPORT='logging',READINESS_REQUIRE_POSTGRES='false',
        HOSTED_RESERVATION_EXPIRY_WORKER_ENABLED='false' if args.check else 'true',
        MODEL_GATEWAY_EXTERNAL_EGRESS_ENABLED='false',GO_AI_PROVIDERS_JSON='')
    sys.path.insert(0,str(ROOT/'src'))
    from go_hotel.db.models import Base,HostedDirectHotelRow
    from go_hotel.db.session import engine,SessionLocal
    from sqlalchemy import select
    Base.metadata.create_all(engine)
    from go_hotel.security.service import identity_service
    identity_service.bootstrap()
    from go_hotel.services.hosted_direct_booking import hosted_direct_booking_service
    from go_hotel.services.official_hotel_catalog import configure_official_hotel,seed_demo_inventory
    with SessionLocal() as session:
        hotel=session.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug=='aoluguya-harbin'))
    if hotel is None:
        hosted_direct_booking_service.create_hotel({'supplier_name':'哈尔滨敖麓谷雅酒店','page_slug':'aoluguya-harbin'},'LOCAL_DEMO_SETUP')
    configured=configure_official_hotel();seed_demo_inventory(configured['hosted_hotel_id'])
    from go_hotel.services.hosted_fare_rules import seed_demo_rules
    seed_demo_rules(configured['hosted_hotel_id'])
    from go_hotel.main import app
    if args.check:
        from fastapi.testclient import TestClient
        with TestClient(app) as client:
            for path in ['/go-app/','/go-app/direct.html','/supplier-console/','/go-admin/']:
                response=client.get(path);assert response.status_code==200,(path,response.status_code)
            shell=client.get('/go-app/').text
            assert 'catalog-credit.js' in shell
            credit_script=client.get('/go-app/catalog-credit.js')
            assert credit_script.status_code==200 and 'GOCatalogCredit' in credit_script.text
            assert 'catalog-fare.js' in shell
            assert 'catalog-cash-fare.js' in shell
            for path,symbol in [('/go-app/catalog-cash-fare.js','GOCatalogCashFare'),('/go-app/catalog-fare.js','GOCatalogFare'),('/supplier-console/catalog-fare.js','GOCatalogFareSupplier')]:
                script=client.get(path);assert script.status_code==200 and symbol in script.text
            catalog=client.get('/v1/direct/aoluguya-harbin/catalog').json()['data']
            assert len(catalog['rooms'])==17
            from datetime import date,timedelta
            availability=client.post('/v1/direct/aoluguya-harbin/availability',json={
                'check_in':(date.today()+timedelta(days=1)).isoformat(),
                'check_out':(date.today()+timedelta(days=3)).isoformat(),'adults':2,'children':0}).json()['data']
            assert availability['data_mode']=='SIMULATION' and len(availability['items'])==34
        print('PASS: four application surfaces, catalog credit and customer/supplier fare scripts, official 17-room catalog, 34 isolated rate variants')
        return
    import uvicorn
    print(f'GO isolated demo: http://127.0.0.1:{args.port}/go-app/ (simulation; no real booking or charge)')
    uvicorn.run(app,host='127.0.0.1',port=args.port,log_level='warning')

if __name__=='__main__':main()
