"""Owner-scoped direct reservation after-sales, without customer approval powers."""
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (HostedDirectReservationRow as Reservation,HostedReservationStayRow as Stay,
    GuestStayLifecycleRow as Guest,PostStayDisputeCaseRow as Case,PostStayDecisionRow as Decision,
    RefundEligibilityRow as Refund)
from go_hotel.services import hosted_money
from go_hotel.services.post_stay_dispute import post_stay_dispute_service as dispute


def owned(s,account,rid):
    stay=s.get(Stay,rid);r=s.get(Reservation,rid)
    if not stay or not r or stay.created_by!=account:raise ValueError('RESERVATION_NOT_FOUND')
    return r,s.scalar(select(Guest).where(Guest.hosted_reservation_id==rid))


def status(s,account,rid):
    r,guest=owned(s,account,rid)
    cases=list(s.scalars(select(Case).where(Case.stay_lifecycle_id==guest.stay_lifecycle_id).order_by(Case.created_at.desc()))) if guest else []
    funds=hosted_money.summary(s,r)
    items=[]
    for case in cases:
        decision=s.scalar(select(Decision).where(Decision.dispute_case_id==case.dispute_case_id,Decision.state=='APPROVED_CONTRACT_ONLY'))
        refund=s.scalar(select(Refund).where(Refund.post_stay_decision_id==decision.post_stay_decision_id)) if decision else None
        items.append({'case_id':case.dispute_case_id,'type':case.dispute_type,'state':case.state,
            'approved_refund_minor':decision.refund_amount_minor if decision else None,
            'refund_eligibility_id':refund.refund_eligibility_id if refund else None,
            'refund_state':refund.decision if refund else 'UNDER_REVIEW',
            'retry_allowed':bool(funds and not funds['reconciliation_required'] and refund and refund.decision in {'REFUND_ELIGIBLE_CONTRACT_ONLY','REFUND_PENDING_SIMULATION'} and not refund.blockers_json)})
    from go_hotel.services.hosted_fare_rules import options
    fare=options(s,r,s.get(Stay,rid))
    from go_hotel.db.models import HostedSupplierDisruptionRow
    from go_hotel.services.hosted_supplier_disruption import public
    disruption=s.scalar(select(HostedSupplierDisruptionRow).where(HostedSupplierDisruptionRow.hosted_reservation_id==rid))
    remedy=public(s,disruption) if disruption else None
    if remedy:remedy['retry_allowed']=disruption.state in {'APPROVED','CANCELLED_REFUND_PENDING','COMPENSATION_PENDING'} and not (funds and funds['reconciliation_required'])
    return {'disruption':remedy,'fare':fare,'funds':funds,'stay_state':guest.state if guest else 'NOT_STARTED',
        'can_open_case':bool(guest and guest.state in {'IN_HOUSE','CHECKED_OUT','NO_SHOW','CANCELLED','CONVERTED_TO_CREDIT'}),'cases':items}


def open_case(account,rid,kind,description,key):
    if kind not in {'SERVICE','AMOUNT','FULFILLMENT','NO_SHOW','CANCELLATION'} or not isinstance(description,str) or not 1<=len(description.strip())<=2000:
        raise ValueError('VALID_CUSTOMER_DISPUTE_REQUIRED')
    if not isinstance(key,str) or not 1<=len(key)<=128:raise ValueError('IDEMPOTENCY_KEY_REQUIRED')
    with SessionLocal() as s:
        _,guest=owned(s,account,rid)
        if not guest or guest.state not in {'IN_HOUSE','CHECKED_OUT','NO_SHOW','CANCELLED','CONVERTED_TO_CREDIT'}:raise ValueError('ACTIVE_OR_COMPLETED_STAY_REQUIRED')
        sid=guest.stay_lifecycle_id
    case=dispute.open_case(sid,{'opened_by_party':'GUEST','dispute_type':kind,'assigned_to':'GO_DISPUTE_QUEUE',
        'description':description.strip(),'initial_evidence_reference':'consumer-request://'+rid},account,key)
    return {'case_id':case['dispute_case_id'],'state':case['state']}


def retry_refund(account,rid,eid):
    with SessionLocal() as s:
        _,guest=owned(s,account,rid)
        refund=s.get(Refund,eid);decision=s.get(Decision,refund.post_stay_decision_id) if refund else None
        case=s.get(Case,decision.dispute_case_id) if decision else None
        if not guest or not case or case.stay_lifecycle_id!=guest.stay_lifecycle_id:raise ValueError('REFUND_NOT_FOUND')
    from go_hotel.db.models import HostedSupplierDisruptionRow
    with SessionLocal() as s:
        disruption=s.scalar(select(HostedSupplierDisruptionRow).where(HostedSupplierDisruptionRow.refund_eligibility_id==eid))
        case_id=disruption.case_id if disruption else None
    if case_id:
        from go_hotel.services.hosted_supplier_disruption import execute
        return execute(case_id)
    return dispute.execute_refund(eid)
