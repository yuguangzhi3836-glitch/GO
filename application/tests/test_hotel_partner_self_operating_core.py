import os
os.environ['DATABASE_URL']='sqlite:////tmp/go_partner_core_test.db'
import pytest
from go_hotel.db.session import engine
from go_hotel.db.models import Base
from go_hotel.services.hotel_partner_core import hotel_partner_core_service as svc

SID='sup_demo';ACT='hotel_owner'
def setup_function():Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
def prop():return svc.create_property(SID,ACT,{'name_zh':'GO 测试酒店','name_en':'GO Test Hotel','property_type':'HOTEL','address':{'city':'Harbin'},'contacts':{'phone':'123'},'legal':{'company':'GO Hotel Ltd'}})
def room(pid):return svc.create_room_type(SID,ACT,pid,{'name_zh':'豪华房','physical_room_count':20,'occupancy':{'max_occupancy':4,'max_adults':2,'max_children':2},'bed_configurations':[{'bed_type':'KING','width_cm':180,'count':1}]})
def rate(pid):
    rt=room(pid);product=svc.create_product(SID,ACT,pid,{'room_type_id':rt['room_type_id'],'name':'双人入住'})
    return rt,svc.create_rate_plan(SID,ACT,pid,{'sellable_product_id':product['sellable_product_id'],'name':'灵活含早','payment_type':'PREPAID','cancellation_tiers':[{'before_arrival_hours':48,'charge_percent':0},{'before_arrival_hours':0,'charge_percent':100}],'default_ari':{'sell_status':'OPEN'}})

def test_property_low_risk_self_service_and_high_risk_change_request():
    p=prop();low=svc.patch_property(SID,ACT,p['property_id'],{'contacts':{'phone':'456'}});assert low['mode']=='IMMEDIATE'
    high=svc.patch_property(SID,ACT,p['property_id'],{'LEGAL':{'company':'New Co'},'evidence':['license://1']});assert high['mode']=='CHANGE_REQUEST' and high['change_request']['state']=='SUBMITTED'
def test_room_product_graph_preserves_distinct_layers_and_occupancy_rules():
    p=prop();rt,rp=rate(p['property_id']);g=svc.graph(SID,p['property_id']);assert len(g['room_types'])==len(g['sellable_products'])==len(g['rate_plans'])==1
    with pytest.raises(ValueError,match='INVALID_OCCUPANCY'):svc.create_room_type(SID,ACT,p['property_id'],{'name_zh':'坏房型','physical_room_count':1,'occupancy':{'max_occupancy':4,'max_adults':2,'max_children':1}})
def test_facility_unknown_is_not_no_and_policy_is_machine_readable():
    p=prop();f=svc.upsert_facility(SID,ACT,p['property_id'],{'code':'ACCESSIBLE_ROOM','category':'ACCESSIBILITY','name_zh':'无障碍客房','status':'UNKNOWN'});assert f['status']=='UNKNOWN'
    pol=svc.upsert_policy(SID,ACT,p['property_id'],{'policy_type':'BREAKFAST','rule':{'available':True,'adult_price_minor':8800,'currency':'CNY','schedule':{'MON':['06:30','10:00']}}});assert pol['rule_json']['adult_price_minor']==8800
def test_ari_separates_sell_status_inventory_and_price_with_date_override():
    p=prop();rt,rp=rate(p['property_id']);a=svc.upsert_ari(SID,ACT,p['property_id'],{'room_type_id':rt['room_type_id'],'rate_plan_id':rp['rate_plan_id'],'stay_date':'2026-10-01','sell_status':'OPEN','inventory_mode':'ALLOTMENT','remaining_rooms':3,'exhaustion_policy':'ON_REQUEST','inventory_sharing':'INDEPENDENT','price':{'guest_sell_price_minor':120000,'supplier_net_minor':110000,'currency':'CNY'}});assert a['remaining_rooms']==3 and a['price_json']['guest_sell_price_minor']==120000
def test_free_sale_cannot_carry_fake_room_count():
    p=prop();rt,rp=rate(p['property_id'])
    with pytest.raises(ValueError,match='FREE_SALE_MUST_NOT'):svc.upsert_ari(SID,ACT,p['property_id'],{'room_type_id':rt['room_type_id'],'rate_plan_id':rp['rate_plan_id'],'stay_date':'2026-10-01','sell_status':'OPEN','inventory_mode':'FREE_SALE','remaining_rooms':9,'exhaustion_policy':'STOP_SELL','price':{'currency':'CNY'}})
def test_operational_inbox_has_priority_sla_owner_state_and_evidence():
    p=prop();i=svc.create_inbox(SID,ACT,p['property_id'],{'item_type':'GO_OFFER_QUOTE','priority':'HIGH','subject':'报价待处理','owner_id':'revenue','sla_minutes':30});x=svc.transition_inbox(SID,ACT,i['inbox_item_id'],{'state':'ACKNOWLEDGED','evidence':['ack://1']});assert x['state']=='ACKNOWLEDGED' and x['sla_due_at'] and x['owner_id']=='revenue'
def test_go_offer_system_generation_requires_isolated_authorized_supply():
    p=prop()
    with pytest.raises(ValueError,match='DEDICATED_AUTHORIZED_SUPPLY'):svc.upsert_offer_authority(SID,ACT,p['property_id'],{'requirement_type':'ROOM_ONLY','quote_mode':'SYSTEM_GENERATED'})
    ok=svc.upsert_offer_authority(SID,ACT,p['property_id'],{'requirement_type':'ROOM_ONLY','quote_mode':'SYSTEM_GENERATED','authorized_inventory':{'rooms':10},'authorized_rules':{'min_rooms':5},'price_floor':{'amount_minor':500000},'source_scope':'GO_OFFER_DEDICATED'});assert ok['source_scope']=='GO_OFFER_DEDICATED'
def test_go_offer_and_commercial_value_never_buy_recommendation():
    p=prop();svc.upsert_offer_authority(SID,ACT,p['property_id'],{'requirement_type':'MEETING_OR_EVENT','quote_mode':'MANUAL_QUOTE'})
    c=svc.command_center(SID,p['property_id']);assert c['guardrails']['recommendation_value_separated'] is True and c['guardrails']['ai_may_mutate_supplier_price_inventory_rule'] is False

def test_one_click_hotel_library_import_requires_owner_and_rejects_ota_credentials():
    p=prop();pid=p['property_id']
    with pytest.raises(ValueError,match='OTA_CREDENTIALS_NOT_ACCEPTED'):
        svc.one_click_import(SID,ACT,pid,{'provider':'CTRIP','method':'DATA_EXPORT','password':'secret','hotel_package':{}})
    result=svc.one_click_import(SID,ACT,pid,{'provider':'CTRIP','method':'DATA_EXPORT','hotel_package':{'hotel':{'brand_name':'GO Brand'},'room_types':[{'name_zh':'大床房','physical_room_count':2,'occupancy':{'max_occupancy':2,'max_adults':2,'max_children':0}}]}})
    assert result['status']=='IMPORTED' and result['room_types_created']==1
    with pytest.raises(ValueError,match='PROPERTY_NOT_FOUND'):
        svc.one_click_import('another_supplier',ACT,pid,{'provider':'CTRIP','method':'DATA_EXPORT','hotel_package':{}})

def test_one_click_media_import_is_fail_closed_without_rights_evidence():
    p=prop()
    with pytest.raises(ValueError,match='MEDIA_RIGHTS_EVIDENCE_REQUIRED'):
        svc.one_click_import(SID,ACT,p['property_id'],{'provider':'MEITUAN','method':'FILE_UPLOAD','hotel_package':{'media':[{'url':'https://example.test/hotel.jpg'}]}})
