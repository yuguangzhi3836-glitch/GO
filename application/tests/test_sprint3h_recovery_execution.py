from datetime import datetime,timezone
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import JourneyRecoveryExecutionItemRow
from test_sprint3g_journey_recovery import auth,seed,journey,disruption

def selected_plan(client,h,j,d):
    p=client.post(f"/v1/trips/journeys/{j['journey_id']}/recovery-plans",headers=h,json={'advice_id':d['advice']['advice_id']}).json()['data']
    picks=[];seen=set()
    for o in p['options']:
        if o['impact_id'] not in seen:
            picks.append(o['option_id']);seen.add(o['impact_id'])
    r=client.post(f"/v1/trips/journeys/{j['journey_id']}/recovery-plans/{p['plan_id']}/select",headers=h,json={'option_ids':picks})
    assert r.status_code==200,r.text
    return r.json()['data']

def test_atomic_intent_is_idempotent_and_supplier_execution_is_non_atomic(client):
    h,uid=auth(client,'sprint3h@example.com');seed(uid);j=journey(client,h);d=disruption(client,h,j);p=selected_plan(client,h,j,d)
    body={'plan_id':p['plan_id'],'authorized_delta_minor':50000,'payment_method_ref':'pm_tok_ref'}
    a=client.post(f"/v1/trips/journeys/{j['journey_id']}/recovery-executions",headers=h|{'Idempotency-Key':'intent-1'},json=body);assert a.status_code==200,a.text
    b=client.post(f"/v1/trips/journeys/{j['journey_id']}/recovery-executions",headers=h|{'Idempotency-Key':'intent-1'},json=body);assert b.status_code==200
    x=a.json()['data'];assert x['execution_id']==b.json()['data']['execution_id'];assert x['atomic_user_intent'] is True and x['atomic_supplier_transaction'] is False
    c=client.post(f"/v1/trips/journeys/{j['journey_id']}/recovery-executions/{x['execution_id']}/confirm",headers=h);assert c.status_code==200,c.text
    out=c.json()['data'];assert out['status']=='COMPLETED';assert out['completed_items']==out['total_items'];assert all(i['supplier_command_id'] and i['supplier_confirmation_id'] for i in out['items'])
    commands=[i['supplier_command_id'] for i in out['items']]
    again=client.post(f"/v1/trips/journeys/{j['journey_id']}/recovery-executions/{x['execution_id']}/confirm",headers=h).json()['data']
    assert [i['supplier_command_id'] for i in again['items']]==commands

def test_price_change_pauses_only_one_item_and_requires_reauthorization(client):
    h,uid=auth(client,'sprint3h-price@example.com');seed(uid);j=journey(client,h);d=disruption(client,h,j);p=selected_plan(client,h,j,d)
    e=client.post(f"/v1/trips/journeys/{j['journey_id']}/recovery-executions",headers=h,json={'plan_id':p['plan_id'],'authorized_delta_minor':50000}).json()['data']
    with SessionLocal.begin() as s:
        item=s.execute(select(JourneyRecoveryExecutionItemRow).where(JourneyRecoveryExecutionItemRow.execution_id==e['execution_id'],JourneyRecoveryExecutionItemRow.vertical=='RAIL')).scalars().first()
        item.facts_json=dict(item.facts_json or {})|{'revalidated_delta_minor':item.quoted_delta_minor+22000}
    out=client.post(f"/v1/trips/journeys/{j['journey_id']}/recovery-executions/{e['execution_id']}/confirm",headers=h).json()['data']
    rail=next(i for i in out['items'] if i['vertical']=='RAIL');assert rail['status']=='PRICE_CHANGED';assert out['status']=='PARTIALLY_COMPLETED';assert out['completed_items']>=1
    bad=client.post(f"/v1/trips/journeys/{j['journey_id']}/recovery-executions/{e['execution_id']}/items/{rail['execution_item_id']}/resolve",headers=h,json={'action':'ACCEPT_PRICE_CHANGE','authorized_delta_minor':rail['revalidated_delta_minor']-1});assert bad.status_code==409
    good=client.post(f"/v1/trips/journeys/{j['journey_id']}/recovery-executions/{e['execution_id']}/items/{rail['execution_item_id']}/resolve",headers=h,json={'action':'ACCEPT_PRICE_CHANGE','authorized_delta_minor':rail['revalidated_delta_minor']});assert good.status_code==200,good.text
    final=good.json()['data'];assert next(i for i in final['items'] if i['vertical']=='RAIL')['status']=='CONFIRMED';assert final['status']=='COMPLETED'

def test_unknown_external_state_reconciles_without_second_supplier_mutation(client):
    h,uid=auth(client,'sprint3h-unknown@example.com');seed(uid);j=journey(client,h);d=disruption(client,h,j);p=selected_plan(client,h,j,d)
    e=client.post(f"/v1/trips/journeys/{j['journey_id']}/recovery-executions",headers=h,json={'plan_id':p['plan_id'],'authorized_delta_minor':50000}).json()['data']
    with SessionLocal.begin() as s:
        item=s.execute(select(JourneyRecoveryExecutionItemRow).where(JourneyRecoveryExecutionItemRow.execution_id==e['execution_id'],JourneyRecoveryExecutionItemRow.vertical=='RIDE')).scalars().first()
        item.facts_json=dict(item.facts_json or {})|{'force_unknown_external_state':True,'reconciliation_result':'CONFIRMED'}
    out=client.post(f"/v1/trips/journeys/{j['journey_id']}/recovery-executions/{e['execution_id']}/confirm",headers=h).json()['data']
    ride=next(i for i in out['items'] if i['vertical']=='RIDE');assert ride['status']=='UNKNOWN_EXTERNAL_STATE';cmd=ride['supplier_command_id'];assert ride['attempt_count']==1
    final=client.post(f"/v1/trips/journeys/{j['journey_id']}/recovery-executions/{e['execution_id']}/items/{ride['execution_item_id']}/resolve",headers=h,json={'action':'RECONCILE'}).json()['data']
    r2=next(i for i in final['items'] if i['vertical']=='RIDE');assert r2['status']=='CONFIRMED';assert r2['supplier_command_id']==cmd;assert r2['attempt_count']==1;assert r2['reconciliation_state']=='RESOLVED_CONFIRMED'
