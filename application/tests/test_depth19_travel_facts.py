"""Signed source facts, current ownership, and per-traveler/per-leg check-in."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select, func
from go_hotel.autonomy.durable import canonical
from go_hotel.db.models import (FlightOrderRow, TravelOperationalFactRow as Fact,
    TravelFactAuthorityRow as Authority, FlightCheckInStateRow)
from go_hotel.db.session import SessionLocal
from go_hotel.services.travel_operational_facts import TravelFacts, checkin_subject

svc=TravelFacts()


def seed_flight(order_id='flight19', account='u19'):
    now=datetime.now(timezone.utc); day=now.date().isoformat()
    legs=[{'origin':'PVG','destination':'NRT','carrier_code':'MU','flight_number':'523','departure_date':day},
          {'origin':'NRT','destination':'PVG','carrier_code':'MU','flight_number':'524','departure_date':(now.date()+timedelta(days=7)).isoformat()}]
    with SessionLocal.begin() as s:
        s.add(FlightOrderRow(order_id=order_id,account_id=account,prebook_id='pb19',status='TICKETED',
            total_amount_minor=10000,currency='CNY',passengers=[{'full_name':'ONE TEST'},{'full_name':'TWO TEST'}],
            payment_method_id=None,pnr='ISOLATED19',ticket_numbers=['T1','T2','T3','T4'],current_itinerary=legs,created_at=now,updated_at=now))
    return legs


def authority(provider='provider19', **overrides):
    key=Ed25519PrivateKey.generate(); now=int(time.time()*1000)
    body={'provider_id':provider,'environment':'ENGINEERING','source_type':'AUTHORIZED_AIRLINE_PROVIDER',
        'contract':{'reference':'isolated-test-contract','kinds':['CHECK_IN','FLIGHT_ARRIVAL'],'carriers':['MU'],
            'link_hosts':['airline.example'],'max_age_ms':3600000},
        'public_key_hex':key.public_key().public_bytes_raw().hex(),'valid_from_ms':now-10000,'valid_until_ms':now+7200000}
    body.update(overrides)
    row=svc.register(body,'maker19')
    svc.review(row['authority_id'],'checker19',1,'APPROVE')
    return row['authority_id'],key,body


def signed(auth, subject, data, kind='CHECK_IN', seq=1, event=None, **overrides):
    aid,key,registered=auth; now=int(time.time()*1000)-10
    fact={'authority_id':aid,'provider_id':registered['provider_id'],'event_id':event or f'event{seq}',
        'kind':kind,'source_sequence':seq,'observed_ms':now,'expires_ms':now+300000,
        'subject':subject,'data':data}
    fact.update(overrides)
    return {'fact':fact,'signature_hex':key.sign(canonical(fact).encode()).hex()}


def checkin(auth, leg=0, passenger=0, state='CHECK_IN_OPEN', seq=1, **overrides):
    with SessionLocal() as s:
        subject,_=checkin_subject(s.get(FlightOrderRow,'flight19'),leg,passenger)
    return signed(auth,subject,{'state':state,**overrides},seq=seq,event=f'cell-{leg}-{passenger}-{seq}')


def test_read_is_owner_scoped_and_does_not_invent_or_write_fact():
    seed_flight()
    with pytest.raises(ValueError,match='NOT_FOUND'):svc.checkin('other','flight19')
    result=svc.checkin('u19','flight19')
    assert result['state']=='CHECK_IN_UNVERIFIED' and len(result['items'])==4
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(FlightCheckInStateRow))==0
        assert s.scalar(select(func.count()).select_from(Fact))==0


def test_four_cells_and_official_correction_use_source_order_not_state_rank():
    seed_flight(); auth=authority()
    for leg in range(2):
        for passenger in range(2):
            svc.ingest_checkin('flight19',checkin(auth,leg,passenger,state='BOARDING_PASS_AVAILABLE',boarding_pass_reference=f'https://airline.example/pass/{leg}/{passenger}'),'admin')
    result=svc.checkin('u19','flight19')
    assert result['state']=='BOARDING_PASS_AVAILABLE'
    assert len({x['boarding_pass_reference'] for x in result['items']})==4
    svc.ingest_checkin('flight19',checkin(auth,1,1,state='CHECK_IN_NOT_OPEN',seq=2),'admin')
    result=svc.checkin('u19','flight19')
    assert result['state']=='MIXED' and result['items'][3]['state']=='CHECK_IN_NOT_OPEN'
    assert result['items'][3]['boarding_pass_reference'] is None


def test_unsigned_legacy_source_string_is_not_authority():
    seed_flight()
    with pytest.raises(ValueError,match='SIGNED_CHECK_IN'):svc.ingest_checkin('flight19',{'state':'CHECKED_IN','source_type':'AIRLINE_OFFICIAL','source_authority_reference':'anything'},'admin')


def test_signature_binds_exact_body_and_event_identity():
    seed_flight(); auth=authority(); value=checkin(auth)
    wrong=deepcopy(value);wrong['fact']['data']['state']='CHECKED_IN'
    with pytest.raises(ValueError,match='SIGNATURE'):svc.ingest_checkin('flight19',wrong,'admin')
    assert svc.ingest_checkin('flight19',value,'admin')['created']
    assert not svc.ingest_checkin('flight19',value,'admin')['created']
    wrong['signature_hex']=auth[1].sign(canonical(wrong['fact']).encode()).hex()
    with pytest.raises(ValueError,match='CONTENT_CONFLICT'):svc.ingest_checkin('flight19',wrong,'admin')


@pytest.mark.parametrize('url',['javascript:alert(1)','http://airline.example/pass','https://airline.example.evil.test/pass',
    'https://user@airline.example/pass','https://airline.example:8080/pass','https://airline.example/\npass','https://evil.example/pass'])
def test_untrusted_links_cannot_become_official(url):
    seed_flight();auth=authority()
    with pytest.raises(ValueError,match='LINK_NOT_AUTHORIZED'):
        svc.ingest_checkin('flight19',checkin(auth,official_check_in_url=url),'admin')


def test_independent_review_revision_and_revocation_remove_pass_on_read():
    seed_flight(); auth=authority()
    with pytest.raises(ValueError,match='REVISION'):svc.review(auth[0],'checker19',1,'REVOKE')
    svc.ingest_checkin('flight19',checkin(auth,state='BOARDING_PASS_AVAILABLE',boarding_pass_reference='https://airline.example/pass'),'admin')
    svc.review(auth[0],'checker19',2,'REVOKE')
    result=svc.checkin('u19','flight19')['items'][0]
    assert result['state']=='CHECK_IN_UNVERIFIED' and result['boarding_pass_reference'] is None
    with pytest.raises(ValueError,match='NOT_CURRENT'):svc.ingest_checkin('flight19',checkin(auth,seq=2),'admin')


def test_maker_cannot_approve_and_registered_key_cannot_silently_change():
    seed_flight(); auth=authority()
    with SessionLocal.begin() as s:
        a=s.get(Authority,auth[0]);a.status='DRAFT';a.approved_by=None
    with pytest.raises(ValueError,match='INDEPENDENT'):svc.review(auth[0],'maker19',2,'APPROVE')
    with SessionLocal.begin() as s:s.get(Authority,auth[0]).public_key_hex=Ed25519PrivateKey.generate().public_key().public_bytes_raw().hex()
    with pytest.raises(ValueError,match='INTEGRITY'):svc.review(auth[0],'checker19',2,'APPROVE')


@pytest.mark.parametrize('change',['ticket','itinerary','traveler','refund'])
def test_changed_order_never_reuses_prior_pass(change):
    seed_flight(); auth=authority()
    original=checkin(auth,state='BOARDING_PASS_AVAILABLE',boarding_pass_reference='https://airline.example/pass')
    svc.ingest_checkin('flight19',original,'admin')
    with SessionLocal.begin() as s:
        o=s.get(FlightOrderRow,'flight19')
        if change=='ticket':o.ticket_numbers=['NEW','T2','T3','T4']
        if change=='itinerary':o.current_itinerary=[dict(o.current_itinerary[0],flight_number='525'),o.current_itinerary[1]]
        if change=='traveler':o.passengers=[{'full_name':'OTHER TEST'},o.passengers[1]]
        if change=='refund':o.status='REFUNDED'
    assert svc.checkin('u19','flight19')['items'][0]['boarding_pass_reference'] is None
    with pytest.raises(ValueError):svc.ingest_checkin('flight19',original,'admin')


@pytest.mark.parametrize('time_case',['expired','future','too_old','beyond_authority'])
def test_fact_validity_window(time_case):
    seed_flight(); auth=authority(); value=checkin(auth); body=value['fact']; now=int(time.time()*1000)
    if time_case=='expired':body['expires_ms']=now-100
    if time_case=='future':body['observed_ms']=now+60000
    if time_case=='too_old':body['observed_ms']=now-3700000
    if time_case=='beyond_authority':body['expires_ms']=now+9000000
    value['signature_hex']=auth[1].sign(canonical(body).encode()).hex()
    with pytest.raises(ValueError,match='FACT_(NOT_CURRENT|TIME_INVALID)'):svc.ingest_checkin('flight19',value,'admin')


def test_no_fallback_to_older_fact_when_newest_is_expired_or_corrupt():
    seed_flight();auth=authority()
    svc.ingest_checkin('flight19',checkin(auth,state='CHECKED_IN'),'admin')
    last=svc.ingest_checkin('flight19',checkin(auth,seq=2),'admin')
    with SessionLocal.begin() as s:s.get(Fact,last['fact_id']).payload_hash='0'*64
    assert svc.checkin('u19','flight19')['items'][0]['state']=='CHECK_IN_UNVERIFIED'


def test_sequence_and_provider_switch_are_explicit():
    seed_flight();auth=authority()
    svc.ingest_checkin('flight19',checkin(auth,seq=2),'admin')
    with pytest.raises(ValueError,match='OUT_OF_ORDER'):svc.ingest_checkin('flight19',checkin(auth,seq=1),'admin')
    other=authority('other19')
    with pytest.raises(ValueError,match='PROVIDER_SWITCH'):svc.ingest_checkin('flight19',checkin(other,seq=3),'admin')


def test_carrier_scope_and_production_gate(monkeypatch):
    seed_flight();auth=authority(contract={'reference':'x','kinds':['CHECK_IN'],'carriers':['CA'],'link_hosts':[],'max_age_ms':1000})
    with pytest.raises(ValueError,match='SCOPE_MISMATCH'):svc.ingest_checkin('flight19',checkin(auth),'admin')
    from go_hotel.core.config import settings
    monkeypatch.setattr(settings,'app_env','production')
    with pytest.raises(ValueError,match='LIVE_PROVIDER_ACCEPTANCE'):authority('production19')
