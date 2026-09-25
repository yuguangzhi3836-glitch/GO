"""Explicit isolated identities and server provisioning; no global authority fixture."""
import json
from datetime import timedelta
from dataclasses import replace
import pytest
from sqlalchemy import select,func
from fastapi import FastAPI
from fastapi.testclient import TestClient
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (HostedStaffRoleRow,HostedContentSnapshotRow,HostedContentApprovalRow,IdentityUserRow,AuthSessionRow,HostedDirectHotelRow)
from go_hotel.security.service import identity_service
from go_hotel.security.mfa import totp
from go_hotel.services.hosted_content_acceptance import hosted_content_acceptance_service as svc,now,ident,ROLE,digest
from go_hotel.services.hosted_direct_booking import hosted_direct_booking_service as booking
from go_hotel.services.hosted_frontdesk_uat import hosted_frontdesk_uat_service as staff
from go_hotel.api.routes.hosted_direct_booking import router


def authenticated(name,roles=None):
 password='isolated-content-test-password'
 identity_service.ensure_user(name,password,'GO_ADMIN',None,roles or ['GO_GOVERNANCE'])
 enrollment=identity_service.begin_admin_mfa_enrollment(name,password)
 token=identity_service.confirm_admin_mfa_enrollment(enrollment['enrollment_token'],totp(enrollment['secret']))['access_token']
 return identity_service.authenticate(token),token


def provision(hotel,principal):
 """Explicit trusted TEST setup, not a product grant route or real hotel authority."""
 with SessionLocal.begin() as s:
  row=HostedStaffRoleRow(staff_role_id=ident('test_hsr'),hosted_hotel_id=hotel,staff_id=principal.user_id,role=ROLE,state='ACTIVE',evidence_reference='isolated://hosted-content-authority/v1',created_at=now())
  s.add(row);s.flush();return row.staff_role_id


def approval_body(snapshot,decision='APPROVE'):
 return {'decision':decision,'evidence_reference':'isolated://content-review','expected_content_hash':snapshot['content_hash']}


def setup_authority(hotel,monkeypatch):
 monkeypatch.setenv('GO_HOSTED_CONTENT_AUTHORITY_MODE','ISOLATED_FIXTURE')
 maker,_=authenticated('content-maker');checker,_=authenticated('content-checker')
 binding=provision(hotel,checker)
 return maker,checker,binding


@pytest.fixture
def context(monkeypatch):
 hotel=booking.create_hotel({'supplier_name':'哈尔滨敖麓谷雅酒店','page_slug':'isolated-content'},'fixture')['hosted_hotel_id']
 maker,checker,binding=setup_authority(hotel,monkeypatch)
 snap=svc.snapshot(hotel,maker)
 return hotel,maker,checker,binding,snap


def test_real_readonly_http_is_denied_before_snapshot_lookup():
 p,token=authenticated('readonly',['GO_READ_ONLY'])
 app=FastAPI();app.include_router(router)
 with SessionLocal() as s:before=s.scalar(select(func.count()).select_from(HostedContentApprovalRow))
 with TestClient(app) as client:
  r=client.post('/internal/v1/hosted-direct/content-snapshots/absent/approve',headers={'Authorization':'Bearer '+token},json={'approver_role':'HOTEL_AUTHORIZED_OPERATOR','decision':'APPROVE','evidence_reference':'claim'})
 assert r.status_code==403
 with SessionLocal() as s:assert s.scalar(select(func.count()).select_from(HostedContentApprovalRow))==before


def test_isolated_success_binds_snapshot_actor_and_role_not_caller_label(context):
 hotel,maker,checker,binding,snap=context
 row=svc.approve(snap['content_snapshot_id'],approval_body(snap)|{'approver_role':'ANY_CALLER_LABEL'},checker)
 data=row['approval_metadata']
 assert row['evidence_reference']=='isolated://content-review'
 assert data['binding_id']==binding and data['snapshot_hash']==snap['content_hash']
 assert row['approver_role']=='ISOLATED_CONTENT_APPROVER'
 assert svc.gate(hotel)['content_approval_verified'] is True
 assert svc.gate(hotel)['real_hotel_authority_state']=='HOLD_UNVERIFIED'
 assert svc.approve(snap['content_snapshot_id'],approval_body(snap),checker)['content_approval_id']==row['content_approval_id']


@pytest.mark.parametrize('kind',['readonly','disabled','session','forged'])
def test_service_rechecks_persistent_identity_and_session(context,kind):
 _,_,checker,_,snap=context
 if kind=='forged':checker=replace(checker,session_id='fake-session')
 else:
  with SessionLocal.begin() as s:
   if kind=='readonly':s.get(IdentityUserRow,checker.user_id).roles=['GO_READ_ONLY']
   if kind=='disabled':s.get(IdentityUserRow,checker.user_id).status='DISABLED'
   if kind=='session':s.get(AuthSessionRow,checker.session_id).status='REVOKED'
 with pytest.raises(PermissionError):svc.approve(snap['content_snapshot_id'],approval_body(snap),checker)


def test_unbound_wrong_hotel_and_maker_cannot_approve(context):
 hotel,maker,checker,binding,snap=context
 unbound,_=authenticated('unbound')
 with pytest.raises(PermissionError,match='SCOPED_AUTHORITY'):svc.approve(snap['content_snapshot_id'],approval_body(snap),unbound)
 other=booking.create_hotel({'supplier_name':'哈尔滨敖麓谷雅酒店','page_slug':'other'},'fixture')['hosted_hotel_id']
 provision(other,unbound)
 with pytest.raises(PermissionError,match='SCOPED_AUTHORITY'):svc.approve(snap['content_snapshot_id'],approval_body(snap),unbound)
 provision(hotel,maker)
 with pytest.raises(PermissionError,match='MAKER_CHECKER'):svc.approve(snap['content_snapshot_id'],approval_body(snap),maker)


def test_no_public_assign_role_can_self_grant_reserved_binding(context):
 hotel,maker,_,_,_=context
 with pytest.raises(ValueError,match='VALID_STAFF_ROLE'):staff.assign_role(hotel,{'staff_id':maker.user_id,'role':ROLE,'evidence_reference':'isolated://hosted-content-authority/v1'},maker.user_id)


@pytest.mark.parametrize('kind',['disabled_flag','production','wrong_source'])
def test_missing_real_authority_and_nonisolated_environment_hold(context,monkeypatch,kind):
 hotel,_,checker,binding,snap=context
 if kind=='disabled_flag':monkeypatch.delenv('GO_HOSTED_CONTENT_AUTHORITY_MODE')
 if kind=='production':
  from go_hotel.core.config import settings
  monkeypatch.setattr(settings,'app_env','production')
 if kind=='wrong_source':
  with SessionLocal.begin() as s:s.get(HostedStaffRoleRow,binding).evidence_reference='approved-by-hotel'
 with pytest.raises((PermissionError,ValueError)):svc.approve(snap['content_snapshot_id'],approval_body(snap),checker)
 assert svc.gate(hotel)['content_approval_verified'] is False


def test_latest_reject_blocks_prior_approve_even_at_same_clock(context,monkeypatch):
 hotel,_,checker,_,snap=context
 import go_hotel.services.hosted_content_acceptance as source
 fixed=now();monkeypatch.setattr(source,'now',lambda:fixed)
 approved=svc.approve(snap['content_snapshot_id'],approval_body(snap),checker)
 svc.approve(snap['content_snapshot_id'],approval_body(snap,'REJECT')|{'expected_decision_id':approved['content_approval_id']},checker)
 with pytest.raises(ValueError,match='DECISION_CHANGED'):svc.approve(snap['content_snapshot_id'],approval_body(snap),checker)
 assert svc.gate(hotel)['content_approval_verified'] is False
 assert svc.gate(hotel)['latest_content_decision']=='REJECT'


@pytest.mark.parametrize('kind',['binding_replaced','binding_revoked','snapshot_rehashed','actor_revoked'])
def test_gate_does_not_reanimate_old_approval(context,kind):
 hotel,_,checker,binding,snap=context
 svc.approve(snap['content_snapshot_id'],approval_body(snap),checker)
 with SessionLocal.begin() as s:
  if kind=='binding_replaced':s.delete(s.get(HostedStaffRoleRow,binding))
  if kind=='binding_revoked':s.get(HostedStaffRoleRow,binding).state='REVOKED'
  if kind=='actor_revoked':s.get(IdentityUserRow,checker.user_id).roles=['GO_READ_ONLY']
  if kind=='snapshot_rehashed':
   row=s.get(HostedContentSnapshotRow,snap['content_snapshot_id']);body=dict(row.content_json,payload={'changed':'new content'})
   row.content_json=body;row.content_hash=digest(body);s.get(HostedDirectHotelRow,hotel).contact_json=body['payload']
 if kind=='binding_replaced':provision(hotel,checker)
 assert svc.gate(hotel)['content_approval_verified'] is False


def test_old_snapshot_wrong_hash_and_changed_source_rejected(context):
 hotel,maker,checker,_,snap=context
 with pytest.raises(ValueError,match='HASH_CHANGED'):svc.approve(snap['content_snapshot_id'],approval_body(snap)|{'expected_content_hash':'0'*64},checker)
 new=svc.snapshot(hotel,maker)
 with pytest.raises(ValueError,match='SUPERSEDED'):svc.approve(snap['content_snapshot_id'],approval_body(snap),checker)
 with SessionLocal.begin() as s:s.get(HostedDirectHotelRow,hotel).contact_json={'changed':True}
 with pytest.raises(ValueError,match='SOURCE_CHANGED'):svc.approve(new['content_snapshot_id'],approval_body(new),checker)


def test_legacy_snapshot_and_weak_approval_are_not_upgraded(context):
 hotel,_,checker,_,snap=context
 with SessionLocal.begin() as s:
  row=s.get(HostedContentSnapshotRow,snap['content_snapshot_id']);row.content_json={};row.content_hash=digest({})
  s.add(HostedContentApprovalRow(content_approval_id=ident('old'),content_snapshot_id=row.content_snapshot_id,approver_id=checker.user_id,approver_role='HOTEL_AUTHORIZED_OPERATOR',decision='APPROVE',evidence_reference='old claim',decided_at=now()))
 assert svc.gate(hotel)['content_approval_verified'] is False
 with pytest.raises(ValueError,match='LEGACY'):svc.approve(snap['content_snapshot_id'],approval_body(snap),checker)


def test_session_expiry_does_not_retroactively_revoke_valid_approval(context):
 hotel,_,checker,_,snap=context
 svc.approve(snap['content_snapshot_id'],approval_body(snap),checker)
 with SessionLocal.begin() as s:s.get(AuthSessionRow,checker.session_id).expires_at=now()-timedelta(days=1)
 assert svc.gate(hotel)['content_approval_verified'] is True


def test_concurrent_snapshot_versions_are_unique(context):
 from concurrent.futures import ThreadPoolExecutor
 hotel,maker,_,_,_=context
 with ThreadPoolExecutor(max_workers=2) as executor:rows=list(executor.map(lambda _:svc.snapshot(hotel,maker),range(2)))
 assert sorted(x['version'] for x in rows)==[2,3]


@pytest.mark.parametrize('field,value',[('decision',[]),('decision',{}),('expected_content_hash',[]),('expected_content_hash',{})])
def test_malformed_approval_inputs_are_clear_rejections_without_write(context,field,value):
 _,_,checker,_,snap=context
 with pytest.raises(ValueError):svc.approve(snap['content_snapshot_id'],approval_body(snap)|{field:value},checker)
 with SessionLocal() as s:assert s.scalar(select(func.count()).select_from(HostedContentApprovalRow))==0


def test_reference_envelope_fits_db_limit_and_oversize_is_atomic(context):
 _,_,checker,_,snap=context
 with pytest.raises(ValueError,match='REFERENCE_TOO_LONG'):svc.approve(snap['content_snapshot_id'],approval_body(snap)|{'evidence_reference':'x'*512},checker)
 with SessionLocal() as s:assert s.scalar(select(func.count()).select_from(HostedContentApprovalRow))==0
 result=svc.approve(snap['content_snapshot_id'],approval_body(snap)|{'evidence_reference':'酒店隔离核对'},checker)
 assert result['evidence_reference']=='酒店隔离核对'
 with SessionLocal() as s:
  row=s.get(HostedContentApprovalRow,result['content_approval_id']);assert len(row.evidence_reference)<=512
  assert json.loads(row.evidence_reference)['reference']=='酒店隔离核对'


def test_concurrent_duplicate_decisions_commit_one_approval(context):
 from concurrent.futures import ThreadPoolExecutor
 _,_,checker,_,snap=context
 with ThreadPoolExecutor(max_workers=2) as executor:
  results=list(executor.map(lambda _:svc.approve(snap['content_snapshot_id'],approval_body(snap),checker),range(2)))
 assert results[0]['content_approval_id']==results[1]['content_approval_id']
 with SessionLocal() as s:assert s.scalar(select(func.count()).select_from(HostedContentApprovalRow))==1
