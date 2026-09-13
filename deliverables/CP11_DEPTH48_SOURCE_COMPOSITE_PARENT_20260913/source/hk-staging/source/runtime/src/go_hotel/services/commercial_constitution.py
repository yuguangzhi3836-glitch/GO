from datetime import datetime,timezone,timedelta
import hashlib,json,uuid
from sqlalchemy import select,func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import CommercialPolicyVersionRow,CommercialDecisionRow,CommercialEvidenceRow,SupplierSubscriptionRow,DistributionAuthorityRow,CommercialPoolMembershipRow,HotelNetGuardAssessmentRow,CommercialCaseRow,RecommendationDecisionRow,JudgmentRuntimeRow,T20QualifyingOrderRow,SupplierCommercialCohortRow,SubscriptionInvoiceRow,SubscriptionWaiverRow,CommercialAuditEventRow
def now():return datetime.now(timezone.utc)
def ident(p):return f'{p}_{uuid.uuid4().hex}'
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def out(r):return {c.name:(getattr(r,c.name).isoformat() if isinstance(getattr(r,c.name),datetime) else getattr(r,c.name)) for c in r.__table__.columns}
class CommercialConstitutionService:
 def create_policy(self,key,scope,rule,actor):
  forbidden={'recommendation_price_threshold','recommendation_commission_gate','recommendation_subscription_gate','recommendation_advertising_gate'}
  if forbidden&set(rule):raise ValueError('COMMERCIAL_INTEREST_CANNOT_BUY_RECOMMENDATION')
  with SessionLocal() as s:
   n=(s.scalar(select(func.max(CommercialPolicyVersionRow.version_no)).where(CommercialPolicyVersionRow.policy_key==key)) or 0)+1;r=CommercialPolicyVersionRow(policy_version_id=ident('cpv'),policy_key=key,version_no=n,scope=scope,rule_json=rule,content_hash=digest(rule),state='DRAFT',requested_by=actor,created_at=now());s.add(r);s.commit();return out(r)
 def approve_policy(self,pid,actor):
  with SessionLocal() as s:
   r=s.get(CommercialPolicyVersionRow,pid)
   if not r:raise ValueError('POLICY_NOT_FOUND')
   if r.requested_by==actor:raise ValueError('MAKER_CHECKER_REQUIRED')
   for old in s.scalars(select(CommercialPolicyVersionRow).where(CommercialPolicyVersionRow.policy_key==r.policy_key,CommercialPolicyVersionRow.state=='ACTIVE')).all():old.state='SUPERSEDED'
   r.state='ACTIVE';r.approved_by=actor;r.effective_at=now();s.commit();return out(r)
 def _decision(self,s,typ,supplier,prop,inputs,outputs,reasons,policies=None,evidence=None):
  r=CommercialDecisionRow(commercial_decision_id=ident('cdec'),decision_type=typ,supplier_id=supplier,property_id=prop,policy_version_ids_json=policies or [],input_json=inputs,output_json=outputs,reason_codes_json=reasons,decided_at=now());s.add(r);s.flush()
  for e in evidence or []:s.add(CommercialEvidenceRow(commercial_evidence_id=ident('cev'),decision_id=r.commercial_decision_id,evidence_type=e.get('type','REFERENCE'),reference=e['reference'],payload_hash=digest(e),captured_at=now()))
  return r
 def evaluate_pools(self,prop,judgment_decision_id,value_eligible,basis,actor):
  with SessionLocal() as s:
   rec=s.get(RecommendationDecisionRow,judgment_decision_id)
   if not rec:raise ValueError('INDEPENDENT_JUDGMENT_DECISION_REQUIRED')
   if rec.hotel_id!=prop:raise ValueError('JUDGMENT_PROPERTY_MISMATCH')
   judgment=s.get(JudgmentRuntimeRow,rec.judgment_id)
   if not judgment or judgment.status!='ACTIVE' or judgment.valid_to is not None or rec.valid_to is not None:raise ValueError('ACTIVE_INDEPENDENT_JUDGMENT_REQUIRED')
   if not rec.good_hotel_standard_version_id or rec.good_hotel_standard_version_id!=judgment.good_hotel_standard_version_id:raise ValueError('GOOD_HOTEL_STANDARD_BINDING_REQUIRED')
   recommendation_eligible=rec.status=='GO_RECOMMENDED'
   d=self._decision(s,'POOL_ELIGIBILITY',None,prop,{'judgment_decision_id':judgment_decision_id,'good_hotel_standard_version_id':rec.good_hotel_standard_version_id,'basis':basis},{'recommendation_eligible':recommendation_eligible,'value_eligible':value_eligible},['RECOMMENDATION_FROM_GO_GOOD_HOTEL_STANDARD','VALUE_EVALUATED_SEPARATELY'],evidence=[{'type':'JUDGMENT_DECISION','reference':f'judgment://{judgment_decision_id}'},{'type':'GOOD_HOTEL_STANDARD','reference':f'good-hotel-standard://{rec.good_hotel_standard_version_id}'}])
   for typ,eligible in [('RECOMMENDATION',recommendation_eligible),('VALUE',value_eligible)]:
    r=s.scalar(select(CommercialPoolMembershipRow).where(CommercialPoolMembershipRow.property_id==prop,CommercialPoolMembershipRow.pool_type==typ))
    if not r:r=CommercialPoolMembershipRow(commercial_pool_membership_id=ident('pool'),property_id=prop,pool_type=typ,eligible=eligible,basis_json=basis if typ=='VALUE' else {'independent_judgment':True},decision_id=d.commercial_decision_id,evaluated_at=now());s.add(r)
    else:r.eligible=eligible;r.basis_json=basis if typ=='VALUE' else {'independent_judgment':True};r.decision_id=d.commercial_decision_id;r.evaluated_at=now()
   s.commit();return out(d)
 def set_distribution(self,supplier,prop,b,actor):
  if b.get('fallback_enabled') and not b.get('fallback_connectors'):raise ValueError('FALLBACK_AUTHORITY_REQUIRED')
  with SessionLocal() as s:
   r=s.scalar(select(DistributionAuthorityRow).where(DistributionAuthorityRow.property_id==prop))
   v=dict(supplier_id=supplier,property_id=prop,direct_enabled=b.get('direct_enabled',True),fallback_enabled=b.get('fallback_enabled',False),fallback_connectors_json=b.get('fallback_connectors',[]),authority_evidence_json=b.get('evidence',[]),state='ACTIVE',updated_at=now())
   if not r:r=DistributionAuthorityRow(distribution_authority_id=ident('dist'),**v);s.add(r)
   else:
    for k,x in v.items():setattr(r,k,x)
   d=self._decision(s,'DIRECT_FIRST_ROUTING',supplier,prop,b,{'primary':'DIRECT' if r.direct_enabled else 'FALLBACK','fallback_governed':r.fallback_enabled},['DIRECT_FIRST','FALLBACK_REQUIRES_AUTHORITY'],evidence=b.get('evidence'));s.commit();return {'authority':out(r),'decision':out(d)}
 def _audit(self,s,event,aggregate,actor,payload):
  previous=s.scalar(select(CommercialAuditEventRow).order_by(CommercialAuditEventRow.created_at.desc()).limit(1));ph=previous.event_hash if previous else None;t=now();eh=digest({'event':event,'aggregate':aggregate,'actor':actor,'payload':payload,'previous_hash':ph,'created_at':t.isoformat()});s.add(CommercialAuditEventRow(commercial_audit_event_id=ident('cae'),event_type=event,aggregate_id=aggregate,actor_id=actor,payload_json=payload,previous_hash=ph,event_hash=eh,created_at=t))
 def record_order_evidence(self,supplier,prop,b,actor):
  if not b.get('order_id') or not b.get('evidence'):raise ValueError('ORDER_AND_EVIDENCE_REQUIRED')
  source=b.get('source_type');state=b.get('order_state');valid_states={'CONFIRMED','FULFILLED','CHECKED_OUT','COMPLETED'}
  qualifies=source=='OFFICIAL_DIRECT' and state in valid_states;reason=None if qualifies else ('FALLBACK_EXCLUDED_FROM_T20' if source=='AUTHORIZED_FALLBACK' else 'NOT_VALID_OFFICIAL_DIRECT_ORDER')
  with SessionLocal() as s:
   existing=s.scalar(select(T20QualifyingOrderRow).where(T20QualifyingOrderRow.order_id==b['order_id']))
   if existing:return {'order':out(existing),'subscription':out(s.scalar(select(SupplierSubscriptionRow).where(SupplierSubscriptionRow.supplier_id==supplier))),'idempotent_replay':True}
   r=s.scalar(select(SupplierSubscriptionRow).where(SupplierSubscriptionRow.supplier_id==supplier))
   if not r:r=SupplierSubscriptionRow(supplier_subscription_id=ident('sub'),supplier_id=supplier,qualifying_order_count=0,free_order_limit=20,state='T20_FREE',updated_at=now());s.add(r)
   if qualifies:r.qualifying_order_count+=1
   q=T20QualifyingOrderRow(t20_order_id=ident('t20o'),order_id=b['order_id'],supplier_id=supplier,property_id=prop,source_type=source,order_state=state,qualifies=qualifies,exclusion_reason=reason,counted_sequence=r.qualifying_order_count if qualifies else None,evidence_json=b['evidence'],evidence_hash=digest(b['evidence']),occurred_at=now());s.add(q)
   if r.qualifying_order_count>=r.free_order_limit and r.state=='T20_FREE':r.state='SUBSCRIPTION_REQUIRED';r.triggered_at=now()
   r.updated_at=now();self._decision(s,'T20_SUBSCRIPTION',supplier,prop,{'order_id':b['order_id'],'source_type':source,'order_state':state},{'qualifies':qualifies,'count':r.qualifying_order_count,'state':r.state},[reason] if reason else ['VALID_OFFICIAL_DIRECT_ORDER'],evidence=b['evidence']);self._audit(s,'T20_ORDER_EVALUATED',b['order_id'],actor,{'qualifies':qualifies,'sequence':q.counted_sequence,'subscription_state':r.state});s.commit();return {'order':out(q),'subscription':out(r),'idempotent_replay':False}
 def record_qualifying_order(self,supplier,actor):raise ValueError('EVIDENCE_DRIVEN_T20_REQUIRED')
 def cohort(self,supplier,prop):
  with SessionLocal() as s:
   sub=s.scalar(select(SupplierSubscriptionRow).where(SupplierSubscriptionRow.supplier_id==supplier));pool=s.scalar(select(CommercialPoolMembershipRow).where(CommercialPoolMembershipRow.property_id==prop,CommercialPoolMembershipRow.pool_type=='RECOMMENDATION'));rec='RECOMMENDED' if pool and pool.eligible else 'NON_RECOMMENDED';act='T20' if sub and sub.qualifying_order_count>=sub.free_order_limit else 'PRE_T20';r=s.scalar(select(SupplierCommercialCohortRow).where(SupplierCommercialCohortRow.supplier_id==supplier,SupplierCommercialCohortRow.property_id==prop));vals=dict(supplier_id=supplier,property_id=prop,recommendation_cohort=rec,activation_cohort=act,t20_reached_at=sub.triggered_at if sub else None,updated_at=now())
   if not r:r=SupplierCommercialCohortRow(commercial_cohort_id=ident('cohort'),**vals);s.add(r)
   else:
    for k,v in vals.items():setattr(r,k,v)
   s.commit();return out(r)
 def request_waiver(self,supplier,period,reason,evidence,actor):
  if not reason or not evidence:raise ValueError('WAIVER_REASON_AND_EVIDENCE_REQUIRED')
  with SessionLocal() as s:
   if s.scalar(select(SubscriptionWaiverRow).where(SubscriptionWaiverRow.supplier_id==supplier,SubscriptionWaiverRow.billing_period==period)):raise ValueError('WAIVER_ALREADY_EXISTS')
   r=SubscriptionWaiverRow(subscription_waiver_id=ident('waiver'),supplier_id=supplier,billing_period=period,reason=reason,evidence_reference=evidence,state='REQUESTED',requested_by=actor,created_at=now());s.add(r);self._audit(s,'WAIVER_REQUESTED',r.subscription_waiver_id,actor,{'supplier_id':supplier,'period':period});s.commit();return out(r)
 def approve_waiver(self,wid,actor):
  with SessionLocal() as s:
   r=s.get(SubscriptionWaiverRow,wid)
   if not r:raise ValueError('WAIVER_NOT_FOUND')
   if r.requested_by==actor:raise ValueError('MAKER_CHECKER_REQUIRED')
   r.state='APPROVED';r.approved_by=actor;r.decided_at=now();self._audit(s,'WAIVER_APPROVED',wid,actor,{'supplier_id':r.supplier_id,'period':r.billing_period});s.commit();return out(r)
 def issue_invoice(self,supplier,period,actor):
  with SessionLocal() as s:
   old=s.scalar(select(SubscriptionInvoiceRow).where(SubscriptionInvoiceRow.supplier_id==supplier,SubscriptionInvoiceRow.billing_period==period))
   if old:return out(old)
   sub=s.scalar(select(SupplierSubscriptionRow).where(SupplierSubscriptionRow.supplier_id==supplier))
   if not sub or sub.state not in {'SUBSCRIPTION_REQUIRED','ACTIVE'}:raise ValueError('T20_SUBSCRIPTION_NOT_ELIGIBLE')
   policy=s.scalar(select(CommercialPolicyVersionRow).where(CommercialPolicyVersionRow.policy_key=='T20_SUBSCRIPTION',CommercialPolicyVersionRow.state=='ACTIVE').order_by(CommercialPolicyVersionRow.version_no.desc()))
   if not policy:raise ValueError('ACTIVE_SUBSCRIPTION_POLICY_REQUIRED')
   waiver=s.scalar(select(SubscriptionWaiverRow).where(SubscriptionWaiverRow.supplier_id==supplier,SubscriptionWaiverRow.billing_period==period,SubscriptionWaiverRow.state=='APPROVED'));rule=policy.rule_json;plan=rule.get('plan','PREMIUM');
   if 'amount_minor' not in rule:raise ValueError('SUBSCRIPTION_POLICY_AMOUNT_REQUIRED')
   amount=int(rule['amount_minor'])
   if amount<=0:raise ValueError('SUBSCRIPTION_POLICY_AMOUNT_INVALID')
   state='WAIVED' if waiver else 'ISSUED';r=SubscriptionInvoiceRow(subscription_invoice_id=ident('inv'),invoice_number=f'GO-{period}-{supplier}',supplier_id=supplier,billing_period=period,plan=plan,amount_minor=0 if waiver else amount,currency=rule.get('currency','CNY'),state=state,policy_version_id=policy.policy_version_id,due_at=now()+timedelta(days=15),created_at=now());s.add(r);self._audit(s,'SUBSCRIPTION_INVOICE_'+state,r.subscription_invoice_id,actor,{'supplier_id':supplier,'period':period,'amount_minor':r.amount_minor,'waiver_id':waiver.subscription_waiver_id if waiver else None});s.commit();return out(r)
 def finance_status(self,supplier=None):
  with SessionLocal() as s:
   filt=[] if supplier is None else [SupplierSubscriptionRow.supplier_id==supplier];subs=s.scalars(select(SupplierSubscriptionRow).where(*filt)).all();invs=s.scalars(select(SubscriptionInvoiceRow).where(*([] if supplier is None else [SubscriptionInvoiceRow.supplier_id==supplier]))).all();waivers=s.scalars(select(SubscriptionWaiverRow).where(*([] if supplier is None else [SubscriptionWaiverRow.supplier_id==supplier]))).all();orders=s.scalars(select(T20QualifyingOrderRow).where(*([] if supplier is None else [T20QualifyingOrderRow.supplier_id==supplier])).order_by(T20QualifyingOrderRow.occurred_at.desc())).all();return {'subscriptions':[out(x) for x in subs],'orders':[out(x) for x in orders],'invoices':[out(x) for x in invs],'waivers':[out(x) for x in waivers],'equivalent_revenue_policy':{'benchmark_months':10,'meaning':'SUBSCRIPTION_PLUS_CAPPED_PRE_T20_FALLBACK_REVENUE','not_literal_invoice_months':True},'recommendation_independent':True}
 def assess_net_guard(self,prop,supplier_net,floor,currency,evidence):
  state='PASS' if supplier_net>=floor else 'BLOCK';reasons=[] if state=='PASS' else ['HOTEL_NET_BELOW_AUTHORIZED_FLOOR']
  with SessionLocal() as s:
   d=self._decision(s,'HOTEL_NET_GUARD',None,prop,{'supplier_net_minor':supplier_net,'authorized_floor_minor':floor},{'state':state},reasons,evidence=evidence);r=HotelNetGuardAssessmentRow(hotel_net_guard_assessment_id=ident('hng'),property_id=prop,currency=currency,supplier_net_minor=supplier_net,authorized_floor_minor=floor,assessment_state=state,reason_codes_json=reasons,decision_id=d.commercial_decision_id,assessed_at=now());s.add(r);s.commit();return out(r)
 def open_case(self,b,actor):
  with SessionLocal() as s:
   t=now();r=CommercialCaseRow(commercial_case_id=ident('ccase'),case_type=b['case_type'],supplier_id=b.get('supplier_id'),property_id=b.get('property_id'),priority=b.get('priority','MEDIUM'),owner_id=b.get('owner_id'),state='OPEN',sla_due_at=t+timedelta(minutes=b.get('sla_minutes',60)),payload_json=b.get('payload',{}),evidence_json=b.get('evidence',[]),created_at=t,updated_at=t);s.add(r);s.commit();return out(r)
 def dashboard(self):
  with SessionLocal() as s:return {'policies':dict(s.execute(select(CommercialPolicyVersionRow.state,func.count()).group_by(CommercialPolicyVersionRow.state)).all()),'subscriptions':dict(s.execute(select(SupplierSubscriptionRow.state,func.count()).group_by(SupplierSubscriptionRow.state)).all()),'invoices':dict(s.execute(select(SubscriptionInvoiceRow.state,func.count()).group_by(SubscriptionInvoiceRow.state)).all()),'waivers':dict(s.execute(select(SubscriptionWaiverRow.state,func.count()).group_by(SubscriptionWaiverRow.state)).all()),'cases':dict(s.execute(select(CommercialCaseRow.state,func.count()).group_by(CommercialCaseRow.state)).all()),'constitution':{'recommendation_value_separated':True,'direct_first':True,'t20_evidence_driven':True,'fallback_excluded':True,'commercial_interest_cannot_buy_judgment':True}}
commercial_constitution_service=CommercialConstitutionService()
