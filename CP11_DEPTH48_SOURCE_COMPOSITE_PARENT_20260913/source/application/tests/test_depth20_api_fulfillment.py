import sqlite3
from copy import deepcopy

import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (OrderSupplierFulfillmentRow as Fulfillment, RailOrderRow,
    RailChangeQuoteRow, OmnichannelMoneyMovementRow as Movement, VerticalPrebookContractRow as Contract)
from go_hotel.rail.service import rail_service
from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service as supplier
from tests.test_sprint3b_rail import auth


def rail_order(client,quantity=2,seat=0):
    h=auth(client)
    offer=client.post('/v1/rail/search',json={'origin_station':'SHA','destination_station':'HZH','travel_date':'2026-09-11'}).json()['data']['items'][seat]
    quote=client.post(f"/v1/rail/offers/{offer['offer_id']}/prebook",headers=h,json={'quantity':quantity}).json()['data']
    people=[{'full_name':f'ISOLATED ADULT {i}','type':'ADT'} for i in range(quantity)]
    response=client.post('/v1/rail/orders',headers=h,json={'prebook_id':quote['prebook_id'],'passengers':people})
    assert response.status_code==200,response.text
    return h,response.json()['data'],quote


def captured(client,quantity=2,seat=0):
    h,o,q=rail_order(client,quantity,seat);oid=o['order_id']
    response=client.post(f'/v1/rail/orders/{oid}/checkout',headers=h,json={'payment_method_id':'isolated-depth20'})
    assert response.status_code==200,response.text
    with SessionLocal() as s:
        f=s.scalar(select(Fulfillment).where(Fulfillment.business_id==oid));fid=f.order_supplier_fulfillment_id
    fact={'state':'SUPPLIER_CONFIRMED','external_operation_id':'operation-'+oid,'supplier_confirmation_reference':'booking-'+oid,
        'evidence_reference':'isolated://depth20/'+oid,'ticket_numbers':[f'TICKET-{i}-{oid}' for i in range(quantity)]}
    return h,o,q,fid,fact


@pytest.mark.parametrize('tickets',[[],['ONE'],['SAME','SAME'],[' A','B'],['A',123]])
def test_rail_supplier_cannot_ticket_wrong_count_or_invalid_identities(client,tickets):
    h,o,q,fid,fact=captured(client);fact['ticket_numbers']=tickets
    with pytest.raises(ValueError,match='TICKET_PARTY'):supplier.record_supplier_fact(fid,fact)
    with SessionLocal() as s:
        assert s.get(RailOrderRow,o['order_id']).status=='PAYMENT_CONFIRMED_AWAITING_SUPPLIER'
        assert s.get(Fulfillment,fid).state=='CAPTURE_CONFIRMED_READY_FOR_SUPPLIER'


def test_confirmed_rail_tickets_replay_exactly_and_cannot_be_replaced(client):
    h,o,q,fid,fact=captured(client);supplier.record_supplier_fact(fid,fact)
    assert supplier.record_supplier_fact(fid,fact)['replayed']
    changed=deepcopy(fact);changed['ticket_numbers'][0]='OTHER-PERSON-TICKET'
    with pytest.raises(ValueError,match='IDENTITY_IMMUTABLE'):supplier.record_supplier_fact(fid,changed)
    changed=deepcopy(fact);changed['supplier_confirmation_reference']='OTHER-BOOKING'
    with pytest.raises(ValueError,match='IDENTITY_IMMUTABLE'):supplier.record_supplier_fact(fid,changed)
    assert rail_service.order(o['account_id'],o['order_id'])['ticket_numbers']==fact['ticket_numbers']


def test_multi_person_change_refund_returns_to_original_and_adjustment_captures(client):
    h,o,q,fid,fact=captured(client);supplier.record_supplier_fact(fid,fact);oid=o['order_id'];owner=o['account_id']
    change=rail_service.change_quote(owner,oid,'2026-09-12')
    assert change['fare_difference_minor']==6000 and change['change_fee_minor']==1000
    rail_service.execute_change(owner,oid,change['quote_id'])
    rail_service.admin_external_state(oid,'TICKETED','isolated://reissue','ops','BOOKING-REISSUE',['R1','R2'])
    quote=rail_service.refund_quote(owner,oid)
    assert quote['refund_fee_minor']==2600 and quote['refund_amount_minor']==19100
    refund=rail_service.refund(owner,oid)
    assert refund['status']=='REFUND_COMPLETED' and refund['refund_amount_minor']==19100
    with SessionLocal() as s:
        refunds=list(s.scalars(select(Movement).where(Movement.movement_type=='REFUND')))
        assert len(refunds)==2 and sum(r.amount_minor for r in refunds)==19100
        assert len({r.parent_movement_id for r in refunds})==2
        assert all(r.state=='CONFIRMED' for r in refunds)


def test_business_class_change_uses_quoted_zero_fee(client):
    h,o,q,fid,fact=captured(client,1,2);supplier.record_supplier_fact(fid,fact)
    assert q['change_policy']['fee_minor']==0
    assert rail_service.change_quote(o['account_id'],o['order_id'],'2026-09-12')['change_fee_minor']==0


def test_wrong_reissued_party_cannot_capture_adjustment(client):
    h,o,q,fid,fact=captured(client);supplier.record_supplier_fact(fid,fact)
    change=rail_service.change_quote(o['account_id'],o['order_id'],'2026-09-12')
    rail_service.execute_change(o['account_id'],o['order_id'],change['quote_id'])
    with pytest.raises(ValueError,match='TICKET_PARTY'):
        rail_service.admin_external_state(o['order_id'],'TICKETED','isolated://reissue','ops','BOOKING',['ONE'])
    with SessionLocal() as s:
        assert len(list(s.scalars(select(Movement).where(Movement.movement_type=='CAPTURE'))))==1
        assert s.get(RailChangeQuoteRow,change['quote_id']).status=='PENDING_SUPPLIER'


def test_missing_confirmed_adjustment_cannot_mark_change_executed(client,monkeypatch):
    from go_hotel.rail.service import vertical_money_bridge
    h,o,q,fid,fact=captured(client);supplier.record_supplier_fact(fid,fact)
    change=rail_service.change_quote(o['account_id'],o['order_id'],'2026-09-12')
    rail_service.execute_change(o['account_id'],o['order_id'],change['quote_id'])
    monkeypatch.setattr(vertical_money_bridge,'capture_adjustment',lambda *a:None)
    with pytest.raises(ValueError,match='MONEY_NOT_CONFIRMED'):
        rail_service.admin_external_state(o['order_id'],'TICKETED','isolated://reissue','ops','BOOKING',['ONE','TWO'])
    with SessionLocal() as s:
        assert s.get(RailChangeQuoteRow,change['quote_id']).status=='PENDING_SUPPLIER'
        assert s.get(RailOrderRow,o['order_id']).status=='UNKNOWN_EXTERNAL_STATE'


def test_signed_in_prebook_cannot_be_claimed_by_another_consumer(client):
    h=auth(client,'quote-owner@example.com')
    other=auth(client,'quote-other@example.com')
    offer=rail_service.search('SHA','HZH','2026-09-11')[0]
    q=client.post(f"/v1/rail/offers/{offer['offer_id']}/prebook",headers=h,json={'quantity':1}).json()['data']
    response=client.post('/v1/rail/orders',headers=other,json={'prebook_id':q['prebook_id'],'passengers':[{'full_name':'OTHER'}]})
    assert response.status_code==404
    with SessionLocal() as s:assert s.get(Contract,q['prebook_id']).state=='QUOTED'
    aq=client.post('/v1/attractions/prebook',headers=h,json={'offer_id':'tokyo_skytree','visit_date':'2026-09-11'}).json()['data']
    response=client.post('/v1/attractions/orders',headers=other,json={'prebook_id':aq['prebook_id'],'offer_id':'tokyo_skytree','visit_date':'2026-09-11','attendees':[{'name':'OTHER'}]})
    assert response.status_code==404


@pytest.mark.parametrize('quantity',[True,1.2,'2',0,10])
def test_rail_http_rejects_ambiguous_or_unsupported_quantities(client,quantity):
    offer=rail_service.search('SHA','HZH','2026-09-11')[0]
    response=client.post(f"/v1/rail/offers/{offer['offer_id']}/prebook",json={'quantity':quantity})
    assert response.status_code==422


def test_invalid_authentication_never_falls_back_to_anonymous_quote(client):
    response=client.post('/v1/attractions/prebook',headers={'Authorization':'Bearer invalid'},json={'offer_id':'tokyo_skytree','visit_date':'2026-09-11'})
    assert response.status_code==401


def test_changed_vault_identity_with_same_name_cannot_reuse_prebook():
    offer=rail_service.search('SHA','HZH','2026-09-11')[0];q=rail_service.prebook(offer['offer_id'])
    party=[{'full_name':'SAME NAME','type':'ADT'}]
    rail_service.create_order('owner',q['prebook_id'],party,['person-a'])
    with pytest.raises(ValueError,match='CONSUMPTION_CONFLICT'):
        rail_service.create_order('owner',q['prebook_id'],party,['person-b'])


@pytest.mark.no_db
def test_migration_roundtrip_preserves_history_and_refuses_prebook_evidence_loss(tmp_path,monkeypatch):
    from alembic import command
    from alembic.config import Config
    from go_hotel.core.config import settings
    db=tmp_path/'migration.sqlite3';url='sqlite+pysqlite:///'+str(db)
    monkeypatch.setattr(settings,'database_url',url)
    config=Config('alembic.ini');config.set_main_option('sqlalchemy.url',url)
    with sqlite3.connect(db) as c:c.execute('CREATE TABLE historical_order (id TEXT)');c.execute("INSERT INTO historical_order VALUES ('keep')")
    command.stamp(config,'0126_travel_operational_facts');command.upgrade(config,'0127_vertical_prebook_contract')
    command.downgrade(config,'0126_travel_operational_facts');command.upgrade(config,'0127_vertical_prebook_contract')
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO vertical_prebook_contract (prebook_id,vertical,state,terms_json,terms_hash,expires_ms,created_ms) VALUES ('q','RAIL','QUOTED','{}','hash',1,0)")
    with pytest.raises(RuntimeError,match='DATA_PRESENT'):command.downgrade(config,'0126_travel_operational_facts')
    with sqlite3.connect(db) as c:
        assert c.execute('SELECT id FROM historical_order').fetchone()[0]=='keep'
        assert c.execute('SELECT count(*) FROM vertical_prebook_contract').fetchone()[0]==1
        assert c.execute('SELECT version_num FROM alembic_version').fetchone()[0]=='0127_vertical_prebook_contract'
