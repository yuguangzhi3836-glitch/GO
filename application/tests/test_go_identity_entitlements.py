from datetime import datetime,timezone,timedelta
from go_hotel.services.go_identity_entitlements import go_identity_entitlement_service as svc
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import GoIdentityCredentialRow,GoIdentityEventRow,GoFriendsFamilyInvitationRow

def test_staff_rule_engine_uniform_sixty_percent_and_ff_weaker():
 c=svc.apply('consumer_staff','STAFF','supplier_hotel')
 active=svc.evidence(c['credential_id'],{'evidence_type':'EMPLOYMENT_ROSTER','source_type':'HOTEL_HR_API','source_reference':'hr://verified/1','subject_match':True,'confidence_bps':9200,'valid_until':(datetime.now(timezone.utc)+timedelta(days=120)).isoformat()},'admin_rules')
 assert active['state']=='ACTIVE'
 svc.program('supplier_hotel',{'program_type':'STAFF_RATE','enabled':True,'eligible_room_ids':['room_1'],'open_date_ranges':[{'start':'2026-09-01','end':'2026-09-30'}],'inventory_limit':2,'benefits':[],'authorization_reference':'auth://hotel/staff'},'supplier_user')
 e=svc.entitlement('consumer_staff','supplier_hotel','room_1','2026-09-10',10000)
 assert e['identity']=='STAFF' and e['price_minor']==6000 and e['stacking_allowed'] is False
 inv=svc.invite('consumer_staff',c['credential_id'],'consumer_friend','Named Friend',(datetime.now(timezone.utc)+timedelta(days=30)).isoformat(),2)
 assert inv['transferable'] is False
 svc.program('supplier_hotel',{'program_type':'FRIENDS_FAMILY','enabled':True,'eligible_room_ids':['room_1'],'open_date_ranges':[],'inventory_limit':1,'benefits':[],'authorization_reference':'auth://hotel/ff'},'supplier_user')
 ff=svc.entitlement('consumer_friend','supplier_hotel','room_1','2026-09-10',10000)
 assert ff['identity']=='FRIENDS_FAMILY' and ff['price_minor']>6000

def test_owner_paths_are_mutually_exclusive_and_recognition_remains():
 c=svc.apply('consumer_owner','OWNER','supplier_owner_hotel')
 svc.evidence(c['credential_id'],{'evidence_type':'OWNER_REGISTER','source_type':'GROUP_OWNERSHIP_SYSTEM','source_reference':'owner://verified/1','subject_match':True,'confidence_bps':9900},'admin_rules')
 for typ,benefits in [('OWNER_RATE',[]),('OWNER_BENEFITS',['SUITE_PRIORITY','BREAKFAST','LATE_CHECKOUT'])]:svc.program('supplier_owner_hotel',{'program_type':typ,'enabled':True,'eligible_room_ids':[],'open_date_ranges':[],'benefits':benefits,'authorization_reference':'auth://owner/'+typ},'supplier_user')
 svc.select_owner_privilege('consumer_owner',c['credential_id'],'OWNER_RATE')
 rate=svc.entitlement('consumer_owner','supplier_owner_hotel','room_x','2026-09-10',10000)
 assert rate['price_minor']==6000 and rate['benefits']==[] and rate['owner_recognition']=='OWNER'
 svc.select_owner_privilege('consumer_owner',c['credential_id'],'OWNER_BENEFITS')
 benefit=svc.entitlement('consumer_owner','supplier_owner_hotel','room_x','2026-09-10',10000)
 assert benefit['price_minor']==10000 and 'BREAKFAST' in benefit['benefits'] and benefit['owner_recognition']=='OWNER'

def test_staff_revocation_preserves_account_but_removes_entitlement():
 c=svc.apply('consumer_departed','STAFF','supplier_departed')
 svc.evidence(c['credential_id'],{'evidence_type':'EMPLOYMENT_ROSTER','source_type':'HOTEL_HR_API','source_reference':'hr://verified/departed','subject_match':True,'confidence_bps':9000},'admin_rules')
 revoked=svc.transition(c['credential_id'],'REVOKED','EMPLOYMENT_ENDED','admin_rules')
 assert revoked['state']=='REVOKED' and svc.list('consumer_departed')[0]['account_id']=='consumer_departed'
 with SessionLocal() as s:
  assert s.query(GoIdentityEventRow).filter_by(credential_id=c['credential_id'],event_type='STAFF_REVOKED').count()==1

def test_risk_revalidation_and_invitation_consumption_rules():
 c=svc.apply('consumer_risk_staff','STAFF','supplier_risk')
 svc.evidence(c['credential_id'],{'evidence_type':'EMPLOYMENT_ROSTER','source_type':'HOTEL_HR_API','source_reference':'hr://risk/1','subject_match':True,'confidence_bps':9000},'rules')
 review=svc.risk_signal(c['credential_id'],{'risk_score_bps':7500,'reason_code':'SUSPECTED_RESALE','evidence_reference':'risk://1'},'risk_engine')
 assert review['state']=='REVIEW'
 suspended=svc.risk_signal(c['credential_id'],{'risk_score_bps':9500,'reason_code':'CONFIRMED_ACCOUNT_SHARING','evidence_reference':'risk://2'},'risk_engine')
 assert suspended['state']=='SUSPENDED'
 c2=svc.apply('consumer_inviter','STAFF','supplier_risk')
 svc.evidence(c2['credential_id'],{'evidence_type':'EMPLOYMENT_ROSTER','source_type':'HOTEL_HR_API','source_reference':'hr://invite/1','subject_match':True,'confidence_bps':9000},'rules')
 inv=svc.invite('consumer_inviter',c2['credential_id'],'consumer_invitee','Legal Name',(datetime.now(timezone.utc)+timedelta(days=30)).isoformat(),1)
 used=svc.consume_invitation('consumer_invitee',inv['invitation_id'])
 assert used['used_count']==1 and used['state']=='CONSUMED'
