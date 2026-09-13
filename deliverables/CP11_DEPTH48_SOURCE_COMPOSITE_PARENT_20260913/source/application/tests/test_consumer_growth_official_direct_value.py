import pytest
from sqlalchemy import text
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HotelPartnerPropertyRow,ConsumerProfileRow,TravelerProfileRow,GoJourneyRow
from go_hotel.services.consumer_growth_direct_value import consumer_growth_direct_value_service as svc,now

def seed_property(supplier='sup_v53',hotel='prop_v53'):
    with SessionLocal() as s:
        if not s.get(HotelPartnerPropertyRow,hotel):s.add(HotelPartnerPropertyRow(property_id=hotel,supplier_id=supplier,name_zh='V53 Hotel',name_en='V53 Hotel',property_type='HOTEL',group_name=None,brand_name=None,address_json={},latitude=None,longitude=None,contacts_json={},legal_json={},operations_json={},poi_json=[],publication_state='PUBLISHED',version=1,created_at=now(),updated_at=now()));s.commit()
    return supplier,hotel

def test_official_direct_value_priority_and_three_percent_anchor_does_not_touch_recommendation():
    supplier,hotel=seed_property();r=svc.upsert_offer(supplier,hotel,{'upgrade_priority':True,'late_checkout_priority':True,'late_checkout_time':'14:00','cash_discount_bps':300,'breakfast_option':'DOUBLE','consumer_perceived_value_minor':9000,'supplier_incremental_cost_minor':2500,'currency':'CNY','authorization_reference':'test'})
    assert r['cash_value_health']=='HEALTHY_CASH_VALUE_BAND' and r['recommendation_pool_unchanged'] is True
    layers=svc.value_layers(hotel);types=[x['type'] for x in layers['official_direct_value']['benefits_priority'][:4]]
    assert types==['UPGRADE_PRIORITY_WHEN_AVAILABLE','LATE_CHECKOUT_PRIORITY_WHEN_AVAILABLE','CASH_PRICE_ADVANTAGE','BREAKFAST']
    assert layers['go_recommendation']['commercial_value_can_buy_recommendation'] is False

def test_channel_economics_supplier_can_share_small_value_and_still_earn_more():
    supplier,hotel=seed_property('sup_v53b','prop_v53b');svc.upsert_offer(supplier,hotel,{'upgrade_priority':True,'cash_discount_bps':300,'breakfast_option':'NONE','consumer_perceived_value_minor':3000,'supplier_incremental_cost_minor':500,'authorization_reference':'test'})
    r=svc.simulate_economics(supplier,hotel,{'market_rate_minor':100000,'direct_rate_minor':97000,'ota_channel_cost_bps':1500,'go_direct_cost_bps':300,'cash_discount_bps':300,'consumer_value_shared_minor':3000,'supplier_incremental_cost_minor':500,'currency':'CNY'})
    assert r['go_net_revenue_minor']>r['ota_net_revenue_minor'] and r['net_revenue_uplift_minor']>0
    assert r['recommendation_pool_unchanged'] is True

def test_market_benchmark_comparable_gate():
    supplier,hotel=seed_property('sup_v53c','prop_v53c');base={'hotel_id':hotel,'check_in':'2026-09-01','check_out':'2026-09-02','room_type_key':'KING','occupancy_key':'2A','meal_plan_key':'RO','cancellation_key':'FREE_24H','tax_fee_key':'INCLUDED','eligibility_key':'PUBLIC','currency':'CNY'}
    svc.add_benchmark(base|{'source_provider':'OTA_A','total_amount_minor':100000})
    layers=svc.value_layers(hotel,base|{'direct_rate_minor':97000})
    assert layers['comparison']['comparable_rate_gate'] is True and layers['comparison']['direct_cash_advantage_bps']==300

def test_trip_invite_join_and_growth_k_contract():
    with SessionLocal() as s:
        if not s.get(GoJourneyRow,'jny_v53'):s.add(GoJourneyRow(journey_id='jny_v53',account_id='u_owner',title='Tokyo',destination_summary='Tokyo',starts_at=None,ends_at=None,status='UPCOMING',created_at=now(),updated_at=now()));s.commit()
    inv=svc.create_trip_invite('u_owner','jny_v53',{'invitee_hint':'friend@example.com'});joined=svc.join_trip('u_join',inv['invite_token'])
    assert joined['joined'] is True and joined['journey_id']=='jny_v53'
    from go_hotel.journey.service import journey_service
    shared=journey_service.get('u_join','jny_v53')
    assert shared['journey_id']=='jny_v53' and any(x['journey_id']=='jny_v53' for x in journey_service.list('u_join'))
    assert svc.growth_metrics(30)['events']>=2

def test_adult_traveler_claim_requires_target_account_identity_and_minor_is_blocked():
    with SessionLocal() as s:
        if not s.get(ConsumerProfileRow,'u_claim'):s.add(ConsumerProfileRow(user_id='u_claim',go_id='GO-CLAIM',email='claim@example.com',display_name='Claim',phone_ciphertext=None,locale='zh-CN',status='ACTIVE',created_at=now(),updated_at=now()))
        if not s.get(TravelerProfileRow,'trav_adult'):s.add(TravelerProfileRow(traveler_id='trav_adult',user_id='u_owner2',full_name='Adult Traveler',date_of_birth='1990-01-01',nationality='CHN',document_type=None,document_ciphertext=None,relationship_type='SPOUSE',booking_permission=True,guardian_traveler_id=None,guardian_consent_status=None,source_type='MANUAL',is_primary=False,status='ACTIVE',created_at=now(),updated_at=now()))
        if not s.get(TravelerProfileRow,'trav_child'):s.add(TravelerProfileRow(traveler_id='trav_child',user_id='u_owner2',full_name='Child Traveler',date_of_birth='2015-01-01',nationality='CHN',document_type=None,document_ciphertext=None,relationship_type='CHILD',booking_permission=True,guardian_traveler_id=None,guardian_consent_status='GRANTED',source_type='MANUAL',is_primary=False,status='ACTIVE',created_at=now(),updated_at=now()))
        s.commit()
    c=svc.create_claim('u_owner2','trav_adult','claim@example.com');a=svc.accept_claim('u_claim',c['claim_token']);assert a['claimed'] is True and a['data_transfer']=='NO_AUTOMATIC_SENSITIVE_FACT_TRANSFER'
    with pytest.raises(ValueError,match='MINOR_TRAVELER_USES_GUARDIAN_MODEL'):svc.create_claim('u_owner2','trav_child','claim@example.com')

def test_immutable_growth_and_market_evidence_trigger_contract_is_in_migration():
    from pathlib import Path
    m=Path('alembic/versions/0110_consumer_growth_official_direct_value.py').read_text()
    assert "('market_benchmark_quote','IMMUTABLE_MARKET_BENCHMARK_EVIDENCE')" in m
    assert "('consumer_growth_event','IMMUTABLE_CONSUMER_GROWTH_EVENT')" in m
