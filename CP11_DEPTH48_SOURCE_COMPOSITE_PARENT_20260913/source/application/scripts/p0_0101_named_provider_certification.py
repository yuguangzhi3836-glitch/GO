#!/usr/bin/env python3
"""P0 0101 named-provider external certification runner.

Named pair:
- PSP: Stripe Test Mode, because the 0099 truth chain requires distinct authorize/capture/refund facts.
- Hotel supplier: SiteMinder Channels Plus Test Environment.

The runner is deliberately fail-closed. It will not invent credentials, test-property data,
payment details, callback evidence, or PostgreSQL results. It writes an evidence JSON file and
returns 2 when required external inputs are absent, 1 on provider failure, and 0 only when the
requested external operations actually succeed.
"""
from __future__ import annotations
import hashlib, json, os, sys, uuid
from datetime import datetime, timezone
from pathlib import Path
import httpx

OUT=Path(os.getenv('P0_0101_EVIDENCE_PATH','verification/p0_0101_named_provider_external_evidence.json'))

def h(v):
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def redact(v):
    if v is None:return None
    s=str(v)
    return s[:6]+'...'+s[-4:] if len(s)>12 else '***'
def need(names):return [n for n in names if not os.getenv(n)]
def write(payload):
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(payload,indent=2,ensure_ascii=False,default=str)+'\n')
def req(method,url,**kwargs):
    with httpx.Client(timeout=float(os.getenv('P0_0101_HTTP_TIMEOUT','20')),follow_redirects=False) as c:
        r=c.request(method,url,**kwargs)
        try:b=r.json()
        except Exception:b={'raw':r.text[:1000]}
        return r,b

def stripe_run(evidence):
    key=os.environ['STRIPE_TEST_SECRET_KEY']; base=os.getenv('STRIPE_API_BASE','https://api.stripe.com')
    currency=os.getenv('P0_0101_STRIPE_CURRENCY','usd').lower(); amount=int(os.getenv('P0_0101_STRIPE_AMOUNT_MINOR','1200'))
    idem='go-p0-0101-'+uuid.uuid4().hex
    headers={'Authorization':f'Bearer {key}'}
    r,acct=req('GET',base+'/v1/account',headers=headers)
    evidence.append({'provider':'Stripe','operation':'CREDENTIAL_PROBE','http_status':r.status_code,'state':'PASS' if r.is_success else 'FAIL','external_reference':acct.get('id'),'response_hash':h(acct)})
    if not r.is_success: raise RuntimeError('STRIPE_TEST_KEY_PROBE_FAILED')
    form={'amount':str(amount),'currency':currency,'payment_method':'pm_card_visa','payment_method_types[]':'card','capture_method':'manual','confirm':'true','description':'GO P0 0101 certification'}
    r,pi=req('POST',base+'/v1/payment_intents',headers=headers|{'Idempotency-Key':idem},data=form)
    evidence.append({'provider':'Stripe','operation':'AUTHORIZE','http_status':r.status_code,'state':pi.get('status'),'external_reference':pi.get('id'),'request_hash':h(form),'response_hash':h(pi)})
    if not r.is_success or pi.get('status')!='requires_capture': raise RuntimeError('STRIPE_MANUAL_AUTHORIZATION_FAILED')
    pid=pi['id']; cap_form={'amount_to_capture':str(amount)}
    r,cap=req('POST',f'{base}/v1/payment_intents/{pid}/capture',headers=headers|{'Idempotency-Key':idem+'-capture'},data=cap_form)
    evidence.append({'provider':'Stripe','operation':'CAPTURE','http_status':r.status_code,'state':cap.get('status'),'external_reference':pid,'request_hash':h(cap_form),'response_hash':h(cap)})
    if not r.is_success or cap.get('status')!='succeeded': raise RuntimeError('STRIPE_CAPTURE_FAILED')
    refund_form={'payment_intent':pid,'amount':str(amount)}
    r,refund=req('POST',base+'/v1/refunds',headers=headers|{'Idempotency-Key':idem+'-refund'},data=refund_form)
    evidence.append({'provider':'Stripe','operation':'REFUND','http_status':r.status_code,'state':refund.get('status'),'external_reference':refund.get('id'),'request_hash':h(refund_form),'response_hash':h(refund)})
    if not r.is_success or refund.get('status') not in {'succeeded','pending'}: raise RuntimeError('STRIPE_REFUND_FAILED')
    return {'account':acct.get('id'),'payment_intent':pid,'refund':refund.get('id')}

def siteminder_run(evidence):
    base=os.environ['SITEMINDER_CHANNELS_PLUS_BASE_URL'].rstrip('/')
    api_id=os.environ['SITEMINDER_CHANNELS_PLUS_API_ID']; api_key=os.environ['SITEMINDER_CHANNELS_PLUS_API_KEY']
    headers={'x-sm-api-id':api_id,'x-sm-api-key':api_key,'Content-Type':'application/json'}
    query=json.loads(os.environ['SITEMINDER_CERT_PROPERTIES_QUERY_JSON'])
    r,props=req('GET',base+'/properties',headers=headers,params=query)
    evidence.append({'provider':'SiteMinder Channels Plus','operation':'GET_PROPERTIES','http_status':r.status_code,'state':'PASS' if r.is_success else 'FAIL','response_hash':h(props)})
    if not r.is_success: raise RuntimeError('SITEMINDER_PROPERTIES_PROBE_FAILED')
    property_uuid=os.environ['SITEMINDER_CERT_PROPERTY_UUID']; lock_body=json.loads(os.environ['SITEMINDER_CERT_LOCK_BODY_JSON'])
    r,lock=req('POST',f'{base}/properties/{property_uuid}/reservations',headers=headers,json=lock_body)
    booking_ref=lock.get('bookingReferenceId') or lock.get('booking_reference_id') or lock.get('id')
    evidence.append({'provider':'SiteMinder Channels Plus','operation':'LOCK_RESERVATION','http_status':r.status_code,'state':'PASS' if r.is_success and booking_ref else 'FAIL','external_reference':booking_ref,'request_hash':h(lock_body),'response_hash':h(lock)})
    if not r.is_success or not booking_ref: raise RuntimeError('SITEMINDER_LOCK_RESERVATION_FAILED')
    confirm_body=json.loads(os.environ['SITEMINDER_CERT_CONFIRM_BODY_JSON'])
    r,conf=req('POST',f'{base}/reservations/{booking_ref}/confirmation',headers=headers,json=confirm_body)
    evidence.append({'provider':'SiteMinder Channels Plus','operation':'CONFIRM_RESERVATION','http_status':r.status_code,'state':'PASS' if r.is_success else 'FAIL','external_reference':booking_ref,'request_hash':h(confirm_body),'response_hash':h(conf)})
    if not r.is_success: raise RuntimeError('SITEMINDER_CONFIRM_RESERVATION_FAILED')
    r,detail=req('GET',f'{base}/reservations/{booking_ref}',headers=headers)
    evidence.append({'provider':'SiteMinder Channels Plus','operation':'QUERY_RESERVATION','http_status':r.status_code,'state':'PASS' if r.is_success else 'FAIL','external_reference':booking_ref,'response_hash':h(detail)})
    if not r.is_success: raise RuntimeError('SITEMINDER_RESERVATION_QUERY_FAILED')
    if os.getenv('P0_0101_CANCEL_TEST_RESERVATION','1')=='1':
        r,cancel=req('POST',f'{base}/reservations/{booking_ref}/cancellation',headers=headers,json={})
        evidence.append({'provider':'SiteMinder Channels Plus','operation':'CANCEL_RESERVATION','http_status':r.status_code,'state':'PASS' if r.is_success else 'FAIL','external_reference':booking_ref,'response_hash':h(cancel)})
        if not r.is_success: raise RuntimeError('SITEMINDER_CANCEL_RESERVATION_FAILED')
    return {'booking_reference':booking_ref,'property_uuid':property_uuid}

def main():
    required=['STRIPE_TEST_SECRET_KEY','SITEMINDER_CHANNELS_PLUS_BASE_URL','SITEMINDER_CHANNELS_PLUS_API_ID','SITEMINDER_CHANNELS_PLUS_API_KEY','SITEMINDER_CERT_PROPERTIES_QUERY_JSON','SITEMINDER_CERT_PROPERTY_UUID','SITEMINDER_CERT_LOCK_BODY_JSON','SITEMINDER_CERT_CONFIRM_BODY_JSON']
    missing=need(required)
    result={'sprint':'P0 0101','named_psp':'Stripe Test Mode','named_hotel_supplier':'SiteMinder Channels Plus Test Environment','started_at':datetime.now(timezone.utc).isoformat(),'missing_required_inputs':missing,'evidence':[],'gate':'BLOCK'}
    if missing:
        result['reason']='NAMED_PROVIDER_CREDENTIAL_OR_TEST_DATA_MISSING';write(result);print(json.dumps(result,indent=2));return 2
    try:
        result['stripe']=stripe_run(result['evidence']);result['siteminder']=siteminder_run(result['evidence']);result['gate']='NAMED_PROVIDER_EXTERNAL_CALLS_PASS'
        result['reason']='EXTERNAL_CALLS_EXECUTED; CALLBACK/SETTLEMENT/BANK/POSTGRES PROOFS STILL SEPARATE'
        rc=0
    except Exception as e:
        result['reason']=str(e);result['gate']='BLOCK';rc=1
    result['completed_at']=datetime.now(timezone.utc).isoformat();write(result);print(json.dumps(result,indent=2));return rc
if __name__=='__main__':sys.exit(main())
