"""C13 independent HTTP rejection checks; synthetic rooms, actual JWT/DB.
Run with the application tests/conftest.py fixtures loaded (normal application
CI collection or `pytest -p tests.conftest <this-file>` from application root).
No real hotel attestation, PSP calls or dependency overrides.
"""
from copy import deepcopy
from datetime import timedelta
import pytest
from sqlalchemy import select
from tests.test_c01_aoluguya_business_day import http, business, purchase, post
from tests.hosted_review_support import identity, provision
from go_hotel.db import models as m
from go_hotel.db.session import SessionLocal
from go_hotel.services.hosted_operation_authority import ROOT_ROLE, scoped
from go_hotel.services.hosted_direct_booking import now


def registry_payload(h):
    with SessionLocal() as s:
        registry=deepcopy(s.get(m.HostedDirectInventoryPoolRow,h['pool']).room_details_json['room_registry'])
    return {**registry,'expected_version':registry['version']}


def observed(h):
    with SessionLocal() as s:
        return {
            'pool':deepcopy(s.get(m.HostedDirectInventoryPoolRow,h['pool']).room_details_json),
            'registry_audits':[(r.audit_id,deepcopy(r.after_state)) for r in s.scalars(
                select(m.AuditEventRow).where(m.AuditEventRow.action=='HOSTED_ISOLATED_ROOM_REGISTRY_UPDATED')
                .order_by(m.AuditEventRow.audit_id))],
            'stays':[(r.stay_lifecycle_id,r.state,r.assigned_room_reference) for r in s.scalars(
                select(m.GuestStayLifecycleRow).order_by(m.GuestStayLifecycleRow.stay_lifecycle_id))],
            'stay_events':s.query(m.GuestStayEventRow).count(),
        }


@pytest.mark.parametrize('state',['ARRIVED','IN_HOUSE'])
@pytest.mark.parametrize('change',['remove','block'])
def test_occupied_room_registry_rejection_has_zero_business_writes(http,business,state,change):
    h=business
    rid,_=purchase(http,h,'independent-occupied-'+state+'-'+change)
    sid=post(http,f'/internal/v1/stays/reservations/{rid}',h['maker_headers'])['stay_lifecycle_id']
    base=f'/internal/v1/stays/{sid}'
    post(http,base+'/arrive',h['maker_headers'])
    reference='ISOLATED-ROUND-DREAM-101'
    post(http,base+'/room-assignment',h['maker_headers'],{'room_reference':reference})
    if state=='IN_HOUSE':
        post(http,base+'/identity-evidence',h['maker_headers'],
             {'identity_evidence_hash':'d'*64,'verification_method':'HOTEL_DESK_DOCUMENT_CHECK'})
        h['clock']['at']+=timedelta(hours=6)
        post(http,base+'/check-in',h['maker_headers'],{'registration_evidence_reference':'isolated://independent-registration'})
    with SessionLocal() as s:
        assert s.get(m.GuestStayLifecycleRow,sid).state==state
    body=registry_payload(h)
    if change=='remove':
        body['rooms']=[room for room in body['rooms'] if room['room_reference']!=reference]
    else:
        next(room for room in body['rooms'] if room['room_reference']==reference)['state']='BLOCKED'
    before=observed(h)
    response=http.put(f"/internal/v1/hosted-direct/inventory-pools/{h['pool']}/room-registry",
                      headers=h['maker_headers'],json=body)
    assert response.status_code==409,response.text
    assert response.json()['detail']=='ROOM_REGISTRY_ACTIVE_STAY_CONFLICT'
    assert observed(h)==before


@pytest.mark.parametrize('fault',['other_hotel_root','revoked_root','revoked_session'])
def test_registry_write_rejects_wrong_or_revoked_authority_without_mutation(http,business,fault):
    h=business
    if fault=='other_hotel_root':
        principal,headers=identity('independent-other-root')
        other_id='independent-other-hotel'
        with SessionLocal.begin() as s:
            s.add(m.HostedDirectHotelRow(hosted_hotel_id=other_id,supplier_name='ISOLATED OTHER',
                page_slug='independent-other-hotel',city='TEST',contact_json={'inventory_data_mode':'SIMULATION'},
                state='ACTIVE',updated_at=now()))
        provision(other_id,principal)
        # Prove this is a legitimately provisioned hotel root, not merely an outsider.
        with SessionLocal() as s:
            scoped(s,principal,other_id,'admin:rules',root_only=True)
    else:
        principal,headers=h['maker'],h['maker_headers']
        with SessionLocal.begin() as s:
            if fault=='revoked_root':
                grant=s.scalar(select(m.HostedStaffRoleRow).where(
                    m.HostedStaffRoleRow.hosted_hotel_id==h['hotel'],
                    m.HostedStaffRoleRow.staff_id==principal.user_id,m.HostedStaffRoleRow.role==ROOT_ROLE))
                assert grant is not None
                grant.state='REVOKED'
            else:
                session=s.get(m.AuthSessionRow,principal.session_id)
                assert session is not None
                session.status='REVOKED'
    body=registry_payload(h);before=observed(h)
    response=http.put(f"/internal/v1/hosted-direct/inventory-pools/{h['pool']}/room-registry",
                      headers=headers,json=body)
    assert response.status_code in {401,403},response.text
    assert observed(h)==before
