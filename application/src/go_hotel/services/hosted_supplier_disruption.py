"""Independent, durable supplier cancellation for isolated direct hotel orders."""
from copy import deepcopy
from datetime import timedelta
import re
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    HostedSupplierDisruptionRow as Disruption,HostedFaultDebitMandateRow as Mandate,
    HostedDirectReservationRow as Reservation,HostedReservationStayRow as Stay,
    HostedDirectRoomOfferRow as Offer,GuestStayLifecycleRow as Guest,
    StayDisputeRow as Mirror,PostStayDisputeCaseRow as Case,PostStayDecisionRow as Decision,
    RefundEligibilityRow as Refund,HostedCreditRefundPlanRow as RefundPlan,
    HostedCreditAllocationRow as Allocation,HostedStayCreditRow as Credit,
    OmnichannelMoneyMovementRow as Movement,AlipayAuthorizationRow as Authorization)
from go_hotel.services.alipay_safeguarded_settlement import transaction
from go_hotel.services.hosted_direct_booking import ident,now,out
from go_hotel.services.omnichannel_payment import digest
from go_hotel.services.hosted_reservation_operations import hosted_reservation_operations_service as ops
from go_hotel.services import hosted_money as funds,hosted_credit_value as credit,hosted_credit_refunds as refunds,hosted_fare_rules as fare

POLICY={'id':'GO_V7_5_13_5_14','master_sha256':'877aa1d093d675155d20c4b6e424b70454ee89c9969f52810abfd5086d6db66d',
    'supplier_fault_refund_multiple':1,'supplier_fault_compensation_multiple':1,'external_compensation_multiple':0,
    'basis':'CONFIRMED_PAYMENT_WITH_PRIOR_REFUNDS_SEPARATELY_ACCOUNTED'}
SUPPLIER={'OVERBOOKING','NO_ROOM','HOTEL_OPERATIONAL_ERROR','HOTEL_SYSTEM_ERROR','PROPERTY_SELF_CLOSURE','ROOM_UNAVAILABLE','UNJUSTIFIED_CANCELLATION'}
EXTERNAL={'GOVERNMENT_ORDER','NATURAL_DISASTER','PUBLIC_SAFETY_EVENT','FORCE_MAJEURE'}
GUEST={'GUEST_FRAUD','GUEST_INELIGIBLE'}


def lock(s,case_id):
    probe=s.get(Disruption,case_id)
    if not probe:raise ValueError('SUPPLIER_DISRUPTION_NOT_FOUND')
    r,stay,guest,a=fare.locked(s,probe.hosted_reservation_id)
    c=s.get(Disruption,case_id,with_for_update=True,populate_existing=True)
    if digest(c.request_json)!=c.request_hash or digest(c.evidence_json)!=c.evidence_hash:raise ValueError('SUPPLIER_DISRUPTION_EVIDENCE_MISMATCH')
    if c.decision_json and digest(c.decision_json)!=c.decision_hash:raise ValueError('SUPPLIER_DISRUPTION_DECISION_MISMATCH')
    return c,r,stay,guest,a


def evidence_record(payload,actor):
    if not isinstance(payload,dict) or set(payload)!={'reference','sha256','type'}:raise ValueError('STRUCTURED_DISRUPTION_EVIDENCE_REQUIRED')
    if not isinstance(payload['reference'],str) or not 1<=len(payload['reference'])<=512 or not isinstance(payload['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',payload['sha256']) or payload['type'] not in {'HOTEL_RECORD','GUEST_RECORD','OFFICIAL_NOTICE','COMMUNICATION'}:
        raise ValueError('STRUCTURED_DISRUPTION_EVIDENCE_REQUIRED')
    return {**payload,'evidence_id':'hde_'+digest([payload,actor])[:32],'submitted_by':actor,'submitted_at':now().isoformat()}


def request(rid,hotel_id,cause,evidence,actor,key):
    funds.require_isolated()
    if cause not in SUPPLIER|EXTERNAL|GUEST or not isinstance(key,str) or not 1<=len(key)<=128:raise ValueError('VALID_SUPPLIER_CANCELLATION_REQUEST_REQUIRED')
    if not isinstance(evidence,list) or len(evidence)>32:raise ValueError('VALID_DISRUPTION_EVIDENCE_LIST_REQUIRED')
    records=[evidence_record(x,actor) for x in evidence]
    payload={'reservation_id':rid,'hotel_id':hotel_id,'claimed_cause':cause,'requester_id':actor,'idempotency_key':key,
        'initial_evidence':[{'reference':x['reference'],'sha256':x['sha256'],'type':x['type']} for x in records]}
    with transaction() as s:
        r,stay,guest,a=fare.locked(s,rid)
        offer=s.get(Offer,r.hosted_offer_id)
        if offer.hosted_hotel_id!=hotel_id:raise ValueError('SUPPLIER_RESERVATION_NOT_FOUND')
        old=s.scalar(select(Disruption).where(Disruption.hosted_reservation_id==rid))
        if old:
            if old.request_hash!=digest(payload):raise ValueError('SUPPLIER_CANCELLATION_REQUEST_CONFLICT')
            return public(s,old)
        if stay.operational_state!='CONFIRMED' or guest and guest.state not in {'PRE_ARRIVAL','IN_HOUSE'}:raise ValueError('CONFIRMED_UNCOMPLETED_STAY_REQUIRED')
        if a:funds.require_known(s,a)
        if guest and s.scalar(select(Mirror).where(Mirror.stay_lifecycle_id==guest.stay_lifecycle_id,Mirror.state=='OPEN_SETTLEMENT_FROZEN')):raise ValueError('EXISTING_DISPUTE_REVIEW_REQUIRED')
        t=now()
        if not guest:
            guest=Guest(stay_lifecycle_id=ident('gsl'),hosted_reservation_id=rid,state='PRE_ARRIVAL',assigned_room_reference=None,
                planned_check_out=r.check_out,actual_check_in_at=None,actual_check_out_at=None,updated_at=t);s.add(guest);s.flush()
        case=Case(dispute_case_id=ident('pdc'),stay_lifecycle_id=guest.stay_lifecycle_id,opened_by_party='HOTEL',dispute_type='FULFILLMENT',
            assigned_to='GO_INDEPENDENT_FAULT_REVIEW',state='OPEN_EVIDENCE_COLLECTION',response_due_at=t+timedelta(hours=24),
            evidence_due_at=t+timedelta(hours=72),closure_hash=None,created_at=t);s.add(case);s.flush()
        s.add(Mirror(stay_dispute_id='sdp_'+case.dispute_case_id,stay_lifecycle_id=guest.stay_lifecycle_id,dispute_type='FULFILLMENT',
            description='供应商主动取消待独立判责',evidence_reference='supplier-cancellation://'+case.dispute_case_id,state='OPEN_SETTLEMENT_FROZEN',opened_at=t))
        c=Disruption(case_id=ident('hdc'),hosted_reservation_id=rid,hosted_hotel_id=hotel_id,account_id=stay.created_by,
            requester_id=actor,request_json=payload,request_hash=digest(payload),evidence_json=records,evidence_hash=digest(records),checker_id=None,
            state='EVIDENCE_REQUIRED' if not records else 'INDEPENDENT_REVIEW_REQUIRED',decision_json=None,decision_hash=None,
            post_stay_case_id=case.dispute_case_id,refund_eligibility_id=None,compensation_intent_id=None,created_at=t,updated_at=t)
        s.add(c);s.flush();ops._event(s,rid,'SUPPLIER_CANCELLATION_REQUESTED',actor,{'case_id':c.case_id,'request_hash':c.request_hash,'evidence_hash':c.evidence_hash})
        return public(s,c)


def add_evidence(case_id,payload,actor):
    funds.require_isolated();record=evidence_record(payload,actor)
    with transaction() as s:
        c,r,stay,guest,a=lock(s,case_id)
        if c.state not in {'EVIDENCE_REQUIRED','INDEPENDENT_REVIEW_REQUIRED','GUEST_LIABILITY_POLICY_REQUIRED'}:raise ValueError('DISRUPTION_EVIDENCE_ALREADY_LOCKED')
        if any(x['reference']==record['reference'] and x['sha256']==record['sha256'] and x['type']==record['type'] for x in c.evidence_json):return public(s,c)
        if len(c.evidence_json)>=32:raise ValueError('DISRUPTION_EVIDENCE_LIMIT_REACHED')
        if c.state=='GUEST_LIABILITY_POLICY_REQUIRED':
            ops._event(s,r.hosted_reservation_id,'SUPPLIER_FAULT_REVIEW_REOPENED',actor,
                {'case_id':case_id,'prior_decision':deepcopy(c.decision_json),'prior_decision_hash':c.decision_hash,'new_evidence_id':record['evidence_id']})
            c.decision_json=None;c.decision_hash=None;c.checker_id=None
        c.evidence_json=[*c.evidence_json,record];c.evidence_hash=digest(c.evidence_json);c.updated_at=now()
        ops._event(s,r.hosted_reservation_id,'SUPPLIER_FAULT_EVIDENCE_ADDED',actor,{'case_id':case_id,'evidence_id':record['evidence_id'],'evidence_hash':c.evidence_hash})
        c.state='INDEPENDENT_REVIEW_REQUIRED';return public(s,c)


def paid_sources(s,r,a):
    if a:funds.require_known(s,a)
    own=[m for m in funds.movements(s,a) if m.movement_type=='CAPTURE' and m.state=='CONFIRMED']
    lines=[];gross=sum(m.amount_minor for m in own);already=0
    for m in own:
        left=refunds.remaining(s,m);already+=m.amount_minor-left
        if left:lines.append({'capture_id':m.money_movement_id,'payment_intent_id':m.root_payment_intent_id,'amount_minor':left,'kind':'CASH','credit_id':None})
    alloc=s.get(Allocation,r.hosted_reservation_id)
    if alloc:
        source=credit.checked(s,alloc.credit_id);gross+=credit.prepaid(s,r.hosted_reservation_id)
        previous=[x for p in s.scalars(select(RefundPlan).where(RefundPlan.hosted_reservation_id==r.hosted_reservation_id)) for x in p.plan_json if x['kind']=='CREDIT']
        used=sum(x['amount_minor'] for x in previous);amount=credit.prepaid(s,r.hosted_reservation_id)-used
        capture=s.get(Movement,source.source_capture_id)
        if amount<0 or refunds.remaining(s,capture)<amount:raise ValueError('ORIGINAL_REFUND_FUNDS_RESERVED_OR_SPENT')
        already+=used
        if amount:lines.append({'capture_id':capture.money_movement_id,'payment_intent_id':capture.root_payment_intent_id,'amount_minor':amount,'kind':'CREDIT','credit_id':source.credit_id})
    return gross,already,lines


def review(case_id,cause,accepted_ids,reference,actor,expected_evidence_hash=None):
    funds.require_isolated()
    if cause not in SUPPLIER|EXTERNAL|GUEST or not isinstance(reference,str) or not 1<=len(reference.strip())<=512:raise ValueError('INDEPENDENT_FAULT_DECISION_REQUIRED')
    with transaction() as s:
        c,r,stay,guest,a=lock(s,case_id)
        if expected_evidence_hash is not None and expected_evidence_hash!=c.evidence_hash:raise ValueError('DISRUPTION_EVIDENCE_CHANGED_REVIEW_REQUIRED')
        if actor==c.requester_id:raise ValueError('MAKER_CHECKER_SEPARATION_REQUIRED')
        if c.state!='INDEPENDENT_REVIEW_REQUIRED':raise ValueError('DISRUPTION_NOT_AWAITING_REVIEW')
        if not accepted_ids or len(set(accepted_ids))!=len(accepted_ids) or not set(accepted_ids).issubset({x['evidence_id'] for x in c.evidence_json}):raise ValueError('ACCEPTED_DISRUPTION_EVIDENCE_REQUIRED')
        others=s.scalars(select(Mirror).where(Mirror.stay_lifecycle_id==guest.stay_lifecycle_id,Mirror.state=='OPEN_SETTLEMENT_FROZEN',Mirror.stay_dispute_id!='sdp_'+c.post_stay_case_id)).all()
        if others:raise ValueError('EXISTING_DISPUTE_REVIEW_REQUIRED')
        party='SUPPLIER' if cause in SUPPLIER else 'EXTERNAL' if cause in EXTERNAL else 'GUEST'
        gross,already,lines=paid_sources(s,r,a)
        decision={'decision_id':ident('hfd'),'confirmed_cause':cause,'fault_party':party,'accepted_evidence_ids':accepted_ids,
            'evidence_hash':c.evidence_hash,'reference':reference,'checker_id':actor,'policy':POLICY,
            'actual_paid_minor':gross,'prior_refund_or_reservation_minor':already,'refund_due_minor':sum(x['amount_minor'] for x in lines),
            'compensation_due_minor':gross if party=='SUPPLIER' else 0,'currency':r.currency,'source_lines':lines}
        c.checker_id=actor;c.decision_json=decision;c.decision_hash=digest(decision);c.updated_at=now()
        if party=='GUEST':
            # The platform compensation clause does not define guest fraud fees.
            # Preserve funds until an applicable guest-liability rule is reviewed.
            c.state='GUEST_LIABILITY_POLICY_REQUIRED'
            ops._event(s,r.hosted_reservation_id,'SUPPLIER_FAULT_GUEST_POLICY_REQUIRED',actor,
                {'case_id':case_id,'decision':deepcopy(decision),'decision_hash':c.decision_hash,'financial_execution_approved':False})
            return public(s,c)
        d=Decision(post_stay_decision_id=ident('psd'),dispute_case_id=c.post_stay_case_id,
            outcome='PARTIAL_REFUND' if decision['refund_due_minor'] else 'NO_REFUND',refund_amount_minor=decision['refund_due_minor'],
            requester_id=c.requester_id,checker_id=actor,evidence_reference=reference,state='APPROVED_CONTRACT_ONLY',created_at=now());s.add(d);s.flush()
        case=s.get(Case,c.post_stay_case_id);case.state='DECIDED'
        e=Refund(refund_eligibility_id=ident('rei'),post_stay_decision_id=d.post_stay_decision_id,
            decision='REFUND_ELIGIBLE_CONTRACT_ONLY' if d.refund_amount_minor else 'NO_REFUND_ELIGIBLE',eligible_amount_minor=d.refund_amount_minor,
            original_payment_reference=lines[0]['capture_id'] if lines else None,external_refund_invoked=False,blockers_json=[],evidence_hash=digest(decision),created_at=now())
        s.add(e);s.flush();c.refund_eligibility_id=e.refund_eligibility_id
        if lines:s.add(RefundPlan(refund_eligibility_id=e.refund_eligibility_id,hosted_reservation_id=r.hosted_reservation_id,plan_json=lines,plan_hash=digest(lines),created_at=now()))
        c.state='APPROVED';ops._event(s,r.hosted_reservation_id,'SUPPLIER_FAULT_DECIDED',actor,{'case_id':case_id,'decision_id':decision['decision_id'],'decision_hash':c.decision_hash})
        return public(s,c)


def public(s,c):
    d=c.decision_json or {};e=s.get(Refund,c.refund_eligibility_id) if c.refund_eligibility_id else None
    financial_approved=bool(e and d and d.get('fault_party') in {'SUPPLIER','EXTERNAL'})
    return {'case_id':c.case_id,'reservation_id':c.hosted_reservation_id,'state':c.state,'claimed_cause':c.request_json['claimed_cause'],
        'evidence_hash':c.evidence_hash,'decision_hash':c.decision_hash,'evidence_ids':[x['evidence_id'] for x in c.evidence_json],'confirmed_cause':d.get('confirmed_cause'),'fault_party':d.get('fault_party'),
        'actual_paid_minor':d.get('actual_paid_minor'),'financial_decision_approved':financial_approved,
        'refund_due_minor':d.get('refund_due_minor') if financial_approved else None,'compensation_due_minor':d.get('compensation_due_minor') if financial_approved else None,
        'currency':d.get('currency'),'refund_state':e.decision if e else 'NOT_APPROVED','compensation_state':'NOT_APPROVED' if not financial_approved else 'COMPLETED' if c.state=='COMPLETED' and d.get('compensation_due_minor') else 'NOT_REQUIRED' if c.decision_json and not d.get('compensation_due_minor') else 'PENDING',
        'data_mode':'SIMULATION','external_live':False}


def status(case_id,account=None):
    with SessionLocal() as s:
        c=s.get(Disruption,case_id)
        if not c or account is not None and c.account_id!=account:raise ValueError('SUPPLIER_DISRUPTION_NOT_FOUND')
        return public(s,c)


def execute(case_id,expected_decision_hash=None):
    funds.require_isolated()
    with transaction() as s:
        c,r,stay,guest,a=lock(s,case_id)
        if expected_decision_hash is not None and expected_decision_hash!=c.decision_hash:raise ValueError('DISRUPTION_DECISION_CHANGED_REVIEW_REQUIRED')
        if c.state=='COMPLETED':return public(s,c)
        if c.state not in {'APPROVED','CANCELLED_REFUND_PENDING','COMPENSATION_PENDING'}:raise ValueError('APPROVED_SUPPLIER_CANCELLATION_REQUIRED')
        if c.state=='APPROVED':
            if c.checker_id==c.requester_id or not c.checker_id:raise ValueError('INDEPENDENT_FAULT_DECISION_REQUIRED')
            if stay.operational_state!='CONFIRMED':raise ValueError('SUPPLIER_CANCELLATION_ORDER_CHANGED')
            if a:
                funds.require_known(s,a);cash=funds.summary(s,r)['held_minor']
                if cash:
                    auth=next(m for m in funds.active_movements(s,a) if m.movement_type=='AUTHORIZATION' and m.state=='CONFIRMED')
                    funds.money.create_in_session(s,auth.root_payment_intent_id,{'movement_type':'RELEASE','amount_minor':cash,
                        'parent_movement_id':auth.money_movement_id,'mode':'CONTRACT_SIMULATOR','evidence':['supplier-fault-decision://'+c.decision_hash]},'supplier-cancel-release:'+case_id,'hotel-fault')
                a.state='CONTRACT_RELEASED_NOT_ALIPAY';a.updated_at=now()
            alloc=s.get(Allocation,r.hosted_reservation_id)
            if alloc:
                alloc.state='REFUND_RESERVED';source=credit.checked(s,alloc.credit_id)
                credit.event(s,source,'SUPPLIER_REFUND_RESERVED',0,r.hosted_reservation_id,['supplier-fault-decision://'+c.decision_hash],c.checker_id)
            r.reservation_state=stay.operational_state='CANCELLED';guest.state='CANCELLED';r.updated_at=stay.updated_at=guest.updated_at=now()
            r.payment_state='CONTRACT_CREDIT_PAID' if alloc else 'NO_PAYMENT_NO_REFUND_REQUIRED' if not c.decision_json['actual_paid_minor'] else 'CONTRACT_CAPTURED_NOT_ALIPAY'
            ops._release(s,r.hosted_reservation_id);c.state='CANCELLED_REFUND_PENDING';c.updated_at=now()
            ops._event(s,r.hosted_reservation_id,'SUPPLIER_CANCELLATION_APPROVED',c.checker_id,{'case_id':case_id,'decision_hash':c.decision_hash})
        eid=c.refund_eligibility_id;refund_amount=c.decision_json['refund_due_minor']
    if refund_amount:funds.execute_refund(eid)
    with transaction() as s:
        c,r,stay,guest,a=lock(s,case_id)
        e=s.get(Refund,c.refund_eligibility_id)
        if c.decision_json['refund_due_minor'] and e.decision!='REFUND_CONFIRMED_SIMULATION':raise ValueError('ORIGINAL_REFUND_COMPLETION_REQUIRED')
        if c.state=='COMPLETED':return public(s,c)
        alloc=s.get(Allocation,r.hosted_reservation_id)
        if alloc and alloc.state=='REFUND_RESERVED':
            alloc.state='REFUNDED';source=credit.checked(s,alloc.credit_id)
            credit.event(s,source,'SUPPLIER_REFUND_CONFIRMED',0,r.hosted_reservation_id,['supplier-fault-decision://'+c.decision_hash],c.checker_id)
        c.state='COMPENSATION_PENDING';c.updated_at=now()
    with transaction() as s:
        c,r,stay,guest,a=lock(s,case_id)
        if c.state=='COMPLETED':return public(s,c)
        if a:funds.require_known(s,a)
        from go_hotel.services.hosted_fault_funding import compensate
        result=compensate(s,c)
        if result['state']=='AWAITING_FUNDS':return {**public(s,c),'retry_required':True}
        c.state='COMPLETED';c.updated_at=now()
        case=s.get(Case,c.post_stay_case_id);case.state='CLOSED';case.closure_hash=digest([c.decision_hash,result,c.refund_eligibility_id])
        s.get(Mirror,'sdp_'+c.post_stay_case_id).state='CLOSED'
        ops._event(s,r.hosted_reservation_id,'SUPPLIER_REMEDY_COMPLETED',c.checker_id,{'case_id':case_id,'decision_hash':c.decision_hash,'compensation':result})
        ops._notify(s,r.hosted_reservation_id,'GUEST','SUPPLIER_REMEDY_COMPLETED',{'case_id':case_id,'refund_minor':c.decision_json['refund_due_minor'],'compensation_minor':c.decision_json['compensation_due_minor']})
        return public(s,c)


def admin_cases(offset=0):
    from go_hotel.db.models import HostedDirectHotelRow as Hotel
    with SessionLocal() as s:
        rows=s.scalars(select(Disruption).order_by(Disruption.created_at.desc(),Disruption.case_id).offset(offset).limit(51)).all()
        items=[]
        for c in rows[:50]:
            r=s.get(Reservation,c.hosted_reservation_id);o=s.get(Offer,r.hosted_offer_id);h=s.get(Hotel,c.hosted_hotel_id)
            items.append({**public(s,c),'hotel_id':c.hosted_hotel_id,'hotel_name':h.supplier_name,'room_name':o.room_name,'check_in':r.check_in,'check_out':r.check_out})
        return {'items':items,'next_offset':offset+50 if len(rows)>50 else None}


def admin_detail(case_id):
    with SessionLocal() as s:
        c=s.get(Disruption,case_id)
        if not c:raise ValueError('SUPPLIER_DISRUPTION_NOT_FOUND')
        return {**public(s,c),'hotel_id':c.hosted_hotel_id,'requester_id':c.requester_id,'evidence':deepcopy(c.evidence_json)}


def candidates(offset=0):
    from go_hotel.db.models import HostedDirectHotelRow as Hotel
    with SessionLocal() as s:
        rows=s.execute(select(Reservation,Offer,Hotel).join(Stay,Stay.hosted_reservation_id==Reservation.hosted_reservation_id)
            .join(Offer,Offer.hosted_offer_id==Reservation.hosted_offer_id).join(Hotel,Hotel.hosted_hotel_id==Offer.hosted_hotel_id)
            .outerjoin(Guest,Guest.hosted_reservation_id==Reservation.hosted_reservation_id)
            .where(Stay.operational_state=='CONFIRMED',~Reservation.hosted_reservation_id.in_(select(Disruption.hosted_reservation_id)),
                (Guest.state.is_(None))|Guest.state.in_(['PRE_ARRIVAL','IN_HOUSE']))
            .order_by(Reservation.created_at.desc(),Reservation.hosted_reservation_id).offset(offset).limit(51)).all()
        return {'items':[{'reservation_id':r.hosted_reservation_id,'hotel_id':h.hosted_hotel_id,'hotel_name':h.supplier_name,
            'room_name':o.room_name,'check_in':r.check_in,'check_out':r.check_out} for r,o,h in rows[:50]],'next_offset':offset+50 if len(rows)>50 else None}
