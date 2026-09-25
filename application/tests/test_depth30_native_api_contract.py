"""Actual native domain helpers against isolated FastAPI/SQLite, over stdio.

This verifies API compatibility; it is not React Native/device/browser E2E.
"""
from registration_terms_test_support import register_synthetic_consumer
from datetime import date, timedelta
from pathlib import Path
import json
import os
import subprocess
from tests.test_master03_closure import profile
from go_hotel.services.personal_travel_vault import personal_travel_vault_service as vault


def bridge(client, headers, task):
    driver=Path(__file__).resolve().parents[1]/'tests_frontend/native_api_bridge.mjs'
    process=subprocess.Popen([os.environ.get('GO_NATIVE_NODE','node'),'--experimental-strip-types',str(driver)],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    process.stdin.write(json.dumps(task)+'\n');process.stdin.flush()
    try:
        for _ in range(20):
            text=process.stdout.readline()
            assert text,process.stderr.read()
            item=json.loads(text)
            if 'error' in item:raise AssertionError(item['error'])
            if 'result' in item:
                process.wait(timeout=10)
                assert process.returncode==0,process.stderr.read()
                return item['result']
            call=item['request']
            assert call['path'].startswith('/v1/')
            response=client.request(call['method'],call['path'],headers={**headers,**call['headers']},json=call['body'])
            process.stdin.write(json.dumps({'status':response.status_code,'body':response.json()})+'\n');process.stdin.flush()
        raise AssertionError('native request budget exceeded')
    finally:
        if process.poll() is None:process.kill();process.wait()
        process.stdin.close();process.stdout.close();process.stderr.close()


def test_native_six_vertical_creation_payment_and_refund_contracts(client):
    email='native-depth30@example.test'
    registered=register_synthetic_consumer(client, json={'email':email,'password':'StrongPass123!','display_name':'ISOLATED NATIVE TEST'})
    assert registered.status_code==200,registered.text
    uid=registered.json()['data']['profile']['user_id']
    token=client.post('/v1/mobile/auth/login',json={'email':email,'password':'StrongPass123!'}).json()['data']['access_token']
    client.cookies.clear();headers={'Authorization':'Bearer '+token}
    tid=profile(uid,name='ISOLATED TEST TRAVELER')
    vault.grant_consent(uid,{'traveler_id':tid,'purpose':'RENTAL_BOOKING','scope':['DRIVER_LICENSE_NUMBER']})
    day=(date.today()+timedelta(days=10)).isoformat();end=(date.today()+timedelta(days=13)).isoformat()
    def post(path,body=None):
        r=client.post(path,headers=headers,json=body);assert r.status_code==200,r.text;return r.json()['data']
    tasks={}
    hotel=post('/v1/search/hotels',{'destination':{'city_code':'TYO'},'stay':{'check_in':day,'check_out':end},'occupancy':{'rooms':1,'adults':1,'children':0},'currency':'CNY'})['hotels'][0]
    pb=post(f"/v1/offers/{hotel['best_offer']['offer_id']}/prebook",{'currency':'CNY'})
    tasks['HOTEL']={'prebook':pb}
    for v,base,body in [('FLIGHT','/v1/flights',{'origin':'PVG','destination':'NRT','departure_date':day}),('RAIL','/v1/rail',{'origin_station':'SHA','destination_station':'HZH','travel_date':day})]:
        offer=post(base+'/search',body)['items'][0];pb=post(f"{base}/offers/{offer['offer_id']}/prebook")
        tasks[v]={'prebook':pb,'offer':offer}
    for v,base,body in [('RIDE','/v1/mobility/rides',{'pickup':'PVG','dropoff':'Bund','pickup_at':day+'T10:00:00','currency':'CNY'}),('RENTAL','/v1/mobility/rentals',{'pickup_location':'NRT','return_location':'NRT','pickup_at':day+'T10:00:00','return_at':end+'T10:00:00','currency':'CNY'})]:
        tasks[v]={'search':body,'offer':post(base+'/search',body)['items'][0]}
    offer=post('/v1/attractions/search',{'destination':'东京','visit_date':day})['items'][0]
    pb=post('/v1/attractions/prebook',{'offer_id':offer['offer_id'],'visit_date':day,'session_time':offer.get('session_time'),'quantity':1,'currency':'CNY'})
    tasks['ATTRACTION']={'offer':{**offer,'visit_date':day},'prebook':pb,'quantity':1}
    for v,params in tasks.items():
        create={'action':'create','vertical':v,'params':params,'userId':uid,'travelerId':tid}
        order=bridge(client,headers,create)['data']
        assert order['status']=='PAYMENT_PENDING',(v,order)
        assert bridge(client,headers,create)['data']['order_id']==order['order_id']
        task={'vertical':v,'orderId':order['order_id']}
        paid=bridge(client,headers,{**task,'action':'pay'})
        assert paid['order']['status'] in {'CONFIRMED','TICKETED'},(v,paid)
        assert paid['order']['order_id']==order['order_id']
        refunded=bridge(client,headers,{**task,'action':'refund'})
        assert refunded['order']['status'] in {'CANCELLED','REFUNDED','REFUND_COMPLETED'},(v,refunded)
        assert refunded['notice']=='REFUND_SUBMITTED_CHECK_ORDER'
