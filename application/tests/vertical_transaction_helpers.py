from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OrderSupplierFulfillmentRow
from go_hotel.security.service import identity_service

def admin_headers():
    t=identity_service.login('go_admin','change-me-admin')
    return {'Authorization':'Bearer '+t['access_token']}

def confirm_existing_fulfillment(client,business_id,confirmation_reference,ticket_numbers=None,voucher_code=None):
    with SessionLocal() as s:
        f=s.scalar(select(OrderSupplierFulfillmentRow).where(OrderSupplierFulfillmentRow.business_id==business_id))
        assert f is not None
        fid=f.order_supplier_fulfillment_id
    body={'state':'SUPPLIER_CONFIRMED','external_operation_id':'supplier-op-'+business_id,'supplier_confirmation_reference':confirmation_reference,'evidence_reference':'supplier://confirmation/'+business_id}
    if ticket_numbers:body['ticket_numbers']=ticket_numbers
    if voucher_code:body['voucher_code']=voucher_code
    r=client.post(f'/internal/v1/order-supplier-fulfillments/{fid}/supplier-fact',headers=admin_headers(),json=body)
    assert r.status_code==200,r.text
    return r.json()['data']

def pay_and_confirm(client,consumer_headers,business_type,business_id,confirmation_reference,ticket_numbers=None,voucher_code=None):
    key='pay-'+business_id
    r=client.post('/v1/payments/intents',headers=consumer_headers|{'Idempotency-Key':key},json={'business_type':business_type,'business_id':business_id,'channel_priority':['LOCAL_MARKET']})
    assert r.status_code==200,r.text;i=r.json()['data'];iid=i['payment_intent_id']
    r=client.post(f'/v1/payments/intents/{iid}/channel',headers=consumer_headers,json={'channel':'LOCAL_MARKET'});assert r.status_code==200,r.text
    ah=admin_headers();r=client.post(f'/internal/v1/payments/intents/{iid}/execute',headers=ah,json={'mode':'CONTRACT_SIMULATOR'});assert r.status_code==200,r.text;aid=r.json()['data']['payment_attempt_id']
    r=client.post(f'/internal/v1/payments/attempts/{aid}/simulate',headers=ah,json={'result':'SUCCEEDED'});assert r.status_code==200,r.text
    r=client.post(f'/internal/v1/finance/payment-intents/{iid}/movements',headers=ah|{'Idempotency-Key':'auth-'+business_id},json={'movement_type':'AUTHORIZATION','mode':'CONTRACT_SIMULATOR','evidence':['test://auth/'+business_id]});assert r.status_code==200,r.text;auth=r.json()['data']
    r=client.post(f'/internal/v1/finance/payment-intents/{iid}/movements',headers=ah|{'Idempotency-Key':'cap-'+business_id},json={'movement_type':'CAPTURE','parent_movement_id':auth['money_movement_id'],'mode':'CONTRACT_SIMULATOR','evidence':['test://cap/'+business_id]});assert r.status_code==200,r.text
    return confirm_existing_fulfillment(client,business_id,confirmation_reference,ticket_numbers,voucher_code)
