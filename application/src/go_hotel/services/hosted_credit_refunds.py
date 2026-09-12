"""Reserved refund plans for mixed cash and original hotel-credit captures."""
from sqlalchemy import select
from go_hotel.db.models import (HostedStayCreditRow as Credit,HostedCreditAllocationRow as Allocation,
    HostedCreditRefundPlanRow as Plan,OmnichannelMoneyMovementRow as Movement,OmnichannelPaymentIntentRow as Intent,
    RefundEligibilityRow as Refund,PostStayDecisionRow as Decision,PostStayDisputeCaseRow as Case,
    GuestStayLifecycleRow as Guest,HostedDirectReservationRow as Reservation,AlipayAuthorizationRow as Authorization)
from go_hotel.services import hosted_credit_value as value,hosted_money as funds
from go_hotel.services.hosted_direct_booking import ident,now,out
from go_hotel.services.omnichannel_payment import digest
from go_hotel.services.alipay_safeguarded_settlement import transaction
from go_hotel.services.unified_money_movement import unified_money_movement_service as money


def related(s,rid):return bool(s.get(Allocation,rid) or s.scalar(select(Credit).where(Credit.original_reservation_id==rid)))


def remaining(s,capture,exclude=None):
    actual=sum(m.amount_minor for m in s.scalars(select(Movement).where(Movement.parent_movement_id==capture.money_movement_id,Movement.movement_type.in_(['REFUND','COMPENSATION']),Movement.state=='CONFIRMED')))
    held=0
    for plan in s.scalars(select(Plan)):
        if plan.refund_eligibility_id==exclude:continue
        eligibility=s.get(Refund,plan.refund_eligibility_id)
        if eligibility and eligibility.decision in {'REFUND_ELIGIBLE_CONTRACT_ONLY','REFUND_PENDING_SIMULATION'}:
            held+=sum(x['amount_minor'] for x in plan.plan_json if x['capture_id']==capture.money_movement_id)
    return max(0,capture.amount_minor-actual-held)


def on_approval(s,r,d):
    """Reserve exact sources before an independent approval becomes visible."""
    if not d.refund_amount_minor or not related(s,r.hosted_reservation_id):return
    original=s.scalar(select(Credit).where(Credit.original_reservation_id==r.hosted_reservation_id))
    allocated=s.get(Allocation,r.hosted_reservation_id)
    candidates=[]
    if original:
        c=value.checked(s,original.credit_id);value.active(c)
        if c.state!='ACTIVE' or d.refund_amount_minor!=c.available_minor:raise ValueError('CREDIT_REFUND_MUST_CLOSE_UNUSED_AVAILABLE_VALUE')
        candidates=[(s.get(Movement,c.source_capture_id),c.available_minor,'ORIGINAL_CREDIT',c.credit_id)]
    else:
        c=value.checked(s,allocated.credit_id)
        a=s.scalar(select(Authorization).where(Authorization.hosted_reservation_id==r.hosted_reservation_id))
        candidates=[(m,m.amount_minor,'CASH',None) for m in funds.movements(s,a) if m.movement_type=='CAPTURE' and m.state=='CONFIRMED']
        assigned=sum(x['amount_minor'] for p in s.scalars(select(Plan).where(Plan.hosted_reservation_id==r.hosted_reservation_id)) for x in p.plan_json if x['kind']=='CREDIT')
        candidates.append((s.get(Movement,c.source_capture_id),max(0,value.prepaid(s,r.hosted_reservation_id)-assigned),'CREDIT',c.credit_id))
    amount=d.refund_amount_minor;lines=[]
    for capture,limit,kind,cid in candidates:
        take=min(amount,limit,remaining(s,capture))
        if take:
            lines.append({'capture_id':capture.money_movement_id,'payment_intent_id':capture.root_payment_intent_id,
                'amount_minor':take,'kind':kind,'credit_id':cid});amount-=take
        if not amount:break
    if amount:raise ValueError('CREDIT_REFUND_SOURCE_BUDGET_RESERVED_OR_SPENT')
    eligibility=Refund(refund_eligibility_id=ident('rei'),post_stay_decision_id=d.post_stay_decision_id,
        decision='REFUND_ELIGIBLE_CONTRACT_ONLY',eligible_amount_minor=d.refund_amount_minor,
        original_payment_reference=lines[0]['capture_id'],external_refund_invoked=False,blockers_json=[],
        evidence_hash=digest([d.post_stay_decision_id,lines]),created_at=now())
    s.add(eligibility);s.flush()
    s.add(Plan(refund_eligibility_id=eligibility.refund_eligibility_id,hosted_reservation_id=r.hosted_reservation_id,
        plan_json=lines,plan_hash=digest(lines),created_at=now()))
    if original:
        c.state='FROZEN_REFUND';value.event(s,c,'REFUND_RESERVED',0,r.hosted_reservation_id,
            ['approved-refund://'+d.post_stay_decision_id,{'reserved_minor':d.refund_amount_minor}],d.checker_id)
    funds.project(s,r,'REFUND_REQUESTED')


def execute(eid):
    funds.require_isolated()
    def context(s):
        from go_hotel.services.post_stay_dispute import locked_case
        eligibility=s.get(Refund,eid);d=s.get(Decision,eligibility.post_stay_decision_id) if eligibility else None
        if not d:raise ValueError('REFUND_ELIGIBILITY_NOT_FOUND')
        case=locked_case(s,d.dispute_case_id);eligibility=s.get(Refund,eid,with_for_update=True,populate_existing=True)
        d=s.get(Decision,eligibility.post_stay_decision_id,populate_existing=True);plan=s.get(Plan,eid,with_for_update=True)
        guest=s.get(Guest,case.stay_lifecycle_id);r=s.get(Reservation,guest.hosted_reservation_id)
        if not plan or plan.hosted_reservation_id!=r.hosted_reservation_id or digest(plan.plan_json)!=plan.plan_hash:raise ValueError('CREDIT_REFUND_PLAN_MISMATCH')
        from go_hotel.db.models import HostedSupplierDisruptionRow
        disruption=s.scalar(select(HostedSupplierDisruptionRow).where(HostedSupplierDisruptionRow.refund_eligibility_id==eid))
        if disruption and disruption.state=='APPROVED':raise ValueError('SUPPLIER_CANCELLATION_BEFORE_REFUND_REQUIRED')
        if d.state!='APPROVED_CONTRACT_ONLY' or not d.checker_id or d.checker_id==d.requester_id:raise ValueError('APPROVED_INDEPENDENT_REFUND_DECISION_REQUIRED')
        if eligibility.external_refund_invoked or eligibility.blockers_json:raise ValueError('PAYMENT_RECONCILIATION_REQUIRED')
        if eligibility.eligible_amount_minor!=d.refund_amount_minor or sum(x['amount_minor'] for x in plan.plan_json)!=d.refund_amount_minor:raise ValueError('REFUND_APPROVED_AMOUNT_MISMATCH')
        a=s.scalar(select(Authorization).where(Authorization.hosted_reservation_id==r.hosted_reservation_id));funds.require_known(s,a)
        for line in plan.plan_json:
            capture=s.get(Movement,line['capture_id']);intent=s.get(Intent,line['payment_intent_id'])
            if not capture or capture.state!='CONFIRMED' or capture.movement_type!='CAPTURE' or capture.root_payment_intent_id!=line['payment_intent_id'] or not intent or intent.currency!=r.currency:raise ValueError('ORIGINAL_CONFIRMED_CAPTURE_REQUIRED')
            if line['credit_id']:value.checked(s,line['credit_id'])
        return eligibility,d,plan,r
    with transaction() as s:
        e,d,p,r=context(s)
        if e.decision not in {'REFUND_ELIGIBLE_CONTRACT_ONLY','REFUND_PENDING_SIMULATION','REFUND_CONFIRMED_SIMULATION'}:raise ValueError('REFUND_NOT_EXECUTABLE')
        if e.decision=='REFUND_ELIGIBLE_CONTRACT_ONLY':e.decision='REFUND_PENDING_SIMULATION';funds.project(s,r,'REFUND_REQUESTED')
    with transaction() as s:
        e,d,p,r=context(s);movements=[]
        for index,line in enumerate(p.plan_json):
            movement=money.create_in_session(s,line['payment_intent_id'],{'movement_type':'REFUND',
                'parent_movement_id':line['capture_id'],'amount_minor':line['amount_minor'],'mode':'CONTRACT_SIMULATOR',
                'evidence':['approved-refund://'+d.post_stay_decision_id,'credit-refund-plan://'+eid]},
                'credit-original-refund:'+eid+':'+str(index),'hosted-credit')
            movements.append(movement['money_movement_id'])
        if e.decision!='REFUND_CONFIRMED_SIMULATION':
            for line in p.plan_json:
                if line['kind']=='ORIGINAL_CREDIT':
                    c=s.get(Credit,line['credit_id'])
                    if c.state!='FROZEN_REFUND' or c.available_minor!=line['amount_minor']:raise ValueError('CREDIT_REFUND_RESERVATION_MISMATCH')
                    value.event(s,c,'UNUSED_VALUE_REFUNDED',-line['amount_minor'],r.hosted_reservation_id,['credit-refund-plan://'+eid],d.checker_id);c.state='REFUNDED'
                elif line['kind']=='CREDIT':
                    c=s.get(Credit,line['credit_id']);value.event(s,c,'ALLOCATED_VALUE_REFUNDED',0,r.hosted_reservation_id,
                        ['credit-refund-plan://'+eid,{'refund_minor':line['amount_minor']}],d.checker_id)
            e.decision='REFUND_CONFIRMED_SIMULATION';e.blockers_json=[];e.external_refund_invoked=False
            funds.project(s,r,'REFUND_COMPLETED')
            for cid in {x['credit_id'] for x in p.plan_json if x['kind']=='CREDIT'}:
                c=s.get(Credit,cid);funds.project(s,s.get(Reservation,c.original_reservation_id),'ALLOCATED_CREDIT_REFUND_COMPLETED')
        return {'refund_eligibility_id':eid,'state':'REFUND_COMPLETED','amount_minor':e.eligible_amount_minor,
            'currency':r.currency,'money_movement_ids':movements,'original_capture_ids':[x['capture_id'] for x in p.plan_json],
            'data_mode':'SIMULATION','external_live':False}
