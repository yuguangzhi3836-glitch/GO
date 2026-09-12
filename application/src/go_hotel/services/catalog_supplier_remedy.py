"""Independent cancellation and durable remedies for catalog hotel orders.

The legacy supplier request is not a fault decision. Every financial plan uses
existing confirmed money facts and remains resumable without resending an
uncertain supplier operation.
"""
from copy import deepcopy
from sqlalchemy import select,or_
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (OrderRow as Order,PrebookRow,OfferRow,PaymentRow,RefundRow,
    SupplierFaultCaseRow as Case,CatalogSupplierRemedyRow as Plan,StayCreditRow,
    ChangeQuoteRow,OrderChangeRow,PaymentOrderRootRow as Root,OmnichannelPaymentIntentRow as Intent,
    OmnichannelMoneyMovementRow as Movement,CompensationPaymentRow as Compensation,SupplierLiabilityRow as Liability)
from go_hotel.services.hosted_direct_booking import ident,now
from go_hotel.services.omnichannel_payment import digest
from go_hotel.services.alipay_safeguarded_settlement import transaction
from go_hotel.services import hosted_money as funds,hosted_supplier_disruption as policy
from go_hotel.repositories.sql import repo
from go_hotel.domain.models import Event

ACTIVE={'EVIDENCE_REQUIRED','INDEPENDENT_REVIEW_REQUIRED','GUEST_LIABILITY_POLICY_REQUIRED','APPROVED',
    'SUPPLIER_CANCEL_PENDING','UNKNOWN_SUPPLIER_CANCEL','CANCELLED_REFUND_PENDING','COMPENSATION_PENDING'}


def event(s,order_id,typ,actor,payload):
    repo._append_event_and_outbox(s,Event(ident('evt'),typ,'HOTEL_ORDER',order_id,{**payload,'actor_id':actor,'data_mode':'SIMULATION'},now()))


def lock(s,case_id):
    probe=s.get(Plan,case_id)
    if not probe:raise ValueError('INDEPENDENT_CATALOG_REMEDY_REQUIRED')
    order=s.get(Order,probe.order_id,with_for_update=True,populate_existing=True)
    p=s.get(Plan,case_id,with_for_update=True,populate_existing=True);c=s.get(Case,case_id,with_for_update=True,populate_existing=True)
    if not order or (order.supplier_id,order.account_id)!=(p.supplier_id,p.account_id):raise ValueError('SUPPLIER_ORDER_FACT_CHANGED')
    if digest(p.request_json)!=p.request_hash or digest(p.evidence_json)!=p.evidence_hash:raise ValueError('SUPPLIER_DISRUPTION_EVIDENCE_MISMATCH')
    if p.decision_json and digest(p.decision_json)!=p.decision_hash:raise ValueError('SUPPLIER_DISRUPTION_DECISION_MISMATCH')
    if p.refund_lines_json is not None and digest(p.refund_lines_json)!=p.refund_lines_hash:raise ValueError('CATALOG_REFUND_PLAN_MISMATCH')
    return c,p,order


def roots(s,order):
    quotes=select(ChangeQuoteRow.quote_id).where(ChangeQuoteRow.order_id==order.order_id)
    rows=s.scalars(select(Root).where(or_((Root.business_type=='HOTEL_ORDER')&(Root.business_id==order.order_id),
        (Root.business_type=='CREDIT_DIFF')&(Root.business_id==order.order_id),
        (Root.business_type=='HOTEL_CHANGE')&Root.business_id.in_(quotes))).order_by(Root.payment_intent_id)).all()
    for row in rows:
        intent=s.get(Intent,row.payment_intent_id,with_for_update=True,populate_existing=True)
        if not intent or (intent.payer_id,intent.payee_id,intent.currency,intent.state)!=(order.account_id,order.supplier_id,order.currency,'SUCCEEDED'):raise ValueError('CATALOG_PAYMENT_FACT_RECONCILIATION_REQUIRED')
    return rows


def paid_facts(s,order):
    from go_hotel.db.models import CatalogCreditAllocationRow
    allocation=s.get(CatalogCreditAllocationRow,order.order_id)
    if allocation:
        from go_hotel.services import catalog_credit_value as credit
        credit.checked(s,allocation.credit_id)
        if allocation.state!='ACTIVE':raise ValueError('CREDIT_ALLOCATION_NOT_ACTIVE')
        rr=roots(s,order)
        moves=s.scalars(select(Movement).where(Movement.root_payment_intent_id.in_([r.payment_intent_id for r in rr]))).all()
        if any(m.state!='CONFIRMED' for m in moves):raise ValueError('PAYMENT_RECONCILIATION_REQUIRED')
        caps=[m for m in moves if m.movement_type=='CAPTURE'];prior=0;lines=deepcopy(credit.allocation_lines(s,allocation))
        if sum(m.amount_minor for m in caps if m.business_type=='CREDIT_DIFF')!=allocation.cash_due_minor:raise ValueError('CREDIT_DIFFERENCE_CAPTURE_REQUIRED')
        for cap in caps:
            used=sum(m.amount_minor for m in moves if m.parent_movement_id==cap.money_movement_id and m.movement_type in {'REFUND','COMPENSATION'})
            if used>cap.amount_minor:raise ValueError('CATALOG_REFUND_BALANCE_MISMATCH')
            prior+=used
            if cap.amount_minor>used:lines.append({'capture_id':cap.money_movement_id,'payment_intent_id':cap.root_payment_intent_id,'amount_minor':cap.amount_minor-used})
        return allocation.applied_minor+sum(m.amount_minor for m in caps),prior,lines
    if s.scalar(select(StayCreditRow).where(StayCreditRow.original_order_id==order.order_id)):raise ValueError('CREDIT_SOURCE_FUNDS_RESERVED')
    if s.scalar(select(StayCreditRow).where(StayCreditRow.redemption_order_id==order.order_id)):raise ValueError('LEGACY_CREDIT_VALUE_RECONCILIATION_REQUIRED')
    rr=roots(s,order)
    original=next((r for r in rr if r.business_type=='HOTEL_ORDER'),None)
    if not original:raise ValueError('CONFIRMED_ORIGINAL_PAYMENT_ROOT_REQUIRED')
    payments=s.scalars(select(PaymentRow).where(PaymentRow.order_id==order.order_id,PaymentRow.payment_type=='ORIGINAL_BOOKING',PaymentRow.status=='CAPTURED')).all()
    original_intent=s.get(Intent,original.payment_intent_id)
    if len(payments)!=1 or (payments[0].amount_minor,payments[0].currency)!=(original_intent.amount_minor,original_intent.currency):raise ValueError('ORIGINAL_PAYMENT_ROOT_RECONCILIATION_REQUIRED')
    moves=s.scalars(select(Movement).where(Movement.root_payment_intent_id.in_([r.payment_intent_id for r in rr])).order_by(Movement.created_at,Movement.money_movement_id)).all()
    if any(x.state!='CONFIRMED' for x in moves):raise ValueError('PAYMENT_RECONCILIATION_REQUIRED')
    if s.scalar(select(RefundRow).where(RefundRow.order_id==order.order_id,RefundRow.status.in_(['PROCESSING','PENDING','REFUND_PENDING']))):raise ValueError('EXISTING_REFUND_RECONCILIATION_REQUIRED')
    caps=[m for m in moves if m.movement_type=='CAPTURE'];lines=[];prior=0
    for cap in caps:
        refunded=sum(m.amount_minor for m in moves if m.movement_type in {'REFUND','COMPENSATION'} and m.parent_movement_id==cap.money_movement_id)
        if refunded>cap.amount_minor:raise ValueError('CATALOG_REFUND_BALANCE_MISMATCH')
        prior+=refunded
        if cap.amount_minor>refunded:lines.append({'capture_id':cap.money_movement_id,'payment_intent_id':cap.root_payment_intent_id,'amount_minor':cap.amount_minor-refunded})
    if sum(m.amount_minor for m in caps if m.root_payment_intent_id==original.payment_intent_id)!=payments[0].amount_minor:raise ValueError('ORIGINAL_CAPTURE_RECONCILIATION_REQUIRED')
    return sum(m.amount_minor for m in caps),prior,lines


def request(order_id,supplier_id,reason,evidence_ids,actor):
    funds.require_isolated()
    if not isinstance(reason,str) or not 1<=len(reason)<=64 or not isinstance(evidence_ids,list) or len(evidence_ids)>32 or any(not isinstance(x,str) or not 1<=len(x)<=512 for x in evidence_ids):raise ValueError('VALID_SUPPLIER_CANCELLATION_REQUEST_REQUIRED')
    with transaction() as s:
        order=s.get(Order,order_id,with_for_update=True,populate_existing=True)
        if not order or order.supplier_id!=supplier_id:raise ValueError('SUPPLIER_ORDER_NOT_FOUND')
        payload={'order_id':order_id,'supplier_id':supplier_id,'claimed_cause':reason,'submitted_references':evidence_ids,'requester_id':actor}
        existing=s.scalar(select(Case).where(Case.order_id==order_id))
        if existing:
            plan=s.get(Plan,existing.case_id)
            if not plan:raise ValueError('HISTORICAL_SUPPLIER_CASE_RECONCILIATION_REQUIRED')
            if plan.request_hash!=digest(payload):raise ValueError('SUPPLIER_CANCELLATION_REQUEST_CONFLICT')
            return public(s,existing,plan)
        if order.status!='CONFIRMED':raise ValueError('CONFIRMED_UNCOMPLETED_ORDER_REQUIRED')
        if s.scalar(select(OrderChangeRow).where(OrderChangeRow.order_id==order_id,OrderChangeRow.status=='SUPPLIER_PROCESSING')):raise ValueError('ORDER_CHANGE_RECONCILIATION_REQUIRED')
        paid_facts(s,order)
        cid=ident('sfc');t=now()
        c=Case(case_id=cid,order_id=order_id,supplier_id=supplier_id,reason_code=reason,status='EVIDENCE_REQUIRED',fault_party='UNRESOLVED',evidence_json=evidence_ids,decision_json=None,created_at=t)
        p=Plan(case_id=cid,order_id=order_id,supplier_id=supplier_id,account_id=order.account_id,requester_id=actor,request_json=payload,request_hash=digest(payload),
            evidence_json=[],evidence_hash=digest([]),created_at=t,updated_at=t)
        s.add_all([c,p]);s.flush();event(s,order_id,'SUPPLIER_CANCEL_REQUESTED',actor,{'case_id':cid,'request_hash':p.request_hash,'independent_review_required':True})
        return public(s,c,p)


def add_evidence(case_id,payload,actor):
    funds.require_isolated();record=policy.evidence_record(payload,actor)
    with transaction() as s:
        c,p,order=lock(s,case_id)
        if c.status not in {'EVIDENCE_REQUIRED','INDEPENDENT_REVIEW_REQUIRED','GUEST_LIABILITY_POLICY_REQUIRED'}:raise ValueError('DISRUPTION_EVIDENCE_ALREADY_LOCKED')
        if any((x['reference'],x['sha256'],x['type'])==(record['reference'],record['sha256'],record['type']) for x in p.evidence_json):return public(s,c,p)
        if len(p.evidence_json)>=32:raise ValueError('DISRUPTION_EVIDENCE_LIMIT_REACHED')
        if c.status=='GUEST_LIABILITY_POLICY_REQUIRED':
            event(s,order.order_id,'SUPPLIER_FAULT_REVIEW_REOPENED',actor,{'case_id':case_id,'prior_decision':deepcopy(p.decision_json),'prior_decision_hash':p.decision_hash})
            p.checker_id=None;p.decision_json=None;p.decision_hash=None;c.fault_party='UNRESOLVED';c.decision_json=None
        p.evidence_json=[*p.evidence_json,record];p.evidence_hash=digest(p.evidence_json);p.updated_at=now();c.status='INDEPENDENT_REVIEW_REQUIRED'
        event(s,order.order_id,'SUPPLIER_FAULT_EVIDENCE_ADDED',actor,{'case_id':case_id,'evidence_hash':p.evidence_hash,'evidence_id':record['evidence_id']})
        return public(s,c,p)


def review(case_id,cause,accepted,reference,actor,expected_evidence_hash):
    funds.require_isolated()
    if cause not in policy.SUPPLIER|policy.EXTERNAL|policy.GUEST or not isinstance(reference,str) or not 1<=len(reference.strip())<=512:raise ValueError('INDEPENDENT_FAULT_DECISION_REQUIRED')
    with transaction() as s:
        c,p,order=lock(s,case_id)
        if actor==p.requester_id:raise ValueError('MAKER_CHECKER_SEPARATION_REQUIRED')
        if p.evidence_hash!=expected_evidence_hash:raise ValueError('DISRUPTION_EVIDENCE_CHANGED_REVIEW_REQUIRED')
        if c.status!='INDEPENDENT_REVIEW_REQUIRED' or order.status!='CONFIRMED':raise ValueError('DISRUPTION_NOT_AWAITING_REVIEW')
        if not accepted or len(accepted)!=len(set(accepted)) or not set(accepted).issubset({x['evidence_id'] for x in p.evidence_json}):raise ValueError('ACCEPTED_DISRUPTION_EVIDENCE_REQUIRED')
        gross,prior,lines=paid_facts(s,order);party='SUPPLIER' if cause in policy.SUPPLIER else 'EXTERNAL' if cause in policy.EXTERNAL else 'GUEST'
        decision={'decision_id':ident('cfd'),'confirmed_cause':cause,'fault_party':party,'accepted_evidence_ids':accepted,'evidence_hash':p.evidence_hash,
            'reference':reference,'checker_id':actor,'policy':policy.POLICY,'actual_paid_minor':gross,'prior_refund_minor':prior,'refund_due_minor':sum(x['amount_minor'] for x in lines),
            'compensation_due_minor':gross if party=='SUPPLIER' else 0,'currency':order.currency,'order_version':order.version,'supplier_confirmation_no':order.supplier_confirmation_no}
        p.checker_id=actor;p.decision_json=decision;p.decision_hash=digest(decision);p.updated_at=now()
        c.fault_party=party;c.decision_json=deepcopy(decision);c.decided_at=now()
        if party=='GUEST':c.status='GUEST_LIABILITY_POLICY_REQUIRED'
        else:
            p.refund_lines_json=lines;p.refund_lines_hash=digest(lines);c.status='APPROVED'
        event(s,order.order_id,'SUPPLIER_FAULT_DECIDED' if party!='GUEST' else 'SUPPLIER_FAULT_GUEST_POLICY_REQUIRED',actor,{'case_id':case_id,'decision':decision,'decision_hash':p.decision_hash,'financial_execution_approved':party!='GUEST'})
        return public(s,c,p)


def public(s,c,p,internal=False):
    s.flush()
    d=p.decision_json or {};approved=p.refund_lines_json is not None
    keys=['catalog-fault-refund:'+p.case_id+':'+x['capture_id'] for x in p.refund_lines_json or []]
    refunds=s.scalars(select(Movement).where(Movement.idempotency_key.in_(keys))).all()
    complete=approved and (not keys or len(refunds)==len(keys) and all(r.state=='CONFIRMED' and r.movement_type=='REFUND' for r in refunds))
    result={'case_id':c.case_id,'order_id':p.order_id,'supplier_id':p.supplier_id,'status':c.status,'state':c.status,'case_state':c.status,
        'reason_code':c.reason_code,'claimed_cause':c.reason_code,'fault_party':c.fault_party,'confirmed_cause':d.get('confirmed_cause'),
        'evidence_hash':p.evidence_hash,'decision_hash':p.decision_hash,'evidence_ids':[x['evidence_id'] for x in p.evidence_json],
        'financial_decision_approved':approved,'actual_paid_minor':d.get('actual_paid_minor'),
        'refund_due_minor':d.get('refund_due_minor') if approved else None,'compensation_due_minor':d.get('compensation_due_minor') if approved else None,'currency':d.get('currency'),
        'refund_state':'REFUND_CONFIRMED_SIMULATION' if complete else 'REFUND_ELIGIBLE_CONTRACT_ONLY' if c.status in {'APPROVED','SUPPLIER_CANCEL_PENDING','UNKNOWN_SUPPLIER_CANCEL'} else 'REFUND_PENDING_SIMULATION' if approved else 'NOT_APPROVED',
        'compensation_state':'NOT_APPROVED' if not approved else 'NOT_REQUIRED' if not d.get('compensation_due_minor') else 'COMPLETED' if c.status=='COMPLETED' else 'PENDING',
        'refund':{'amount_minor':d['refund_due_minor'],'currency':d['currency'],'status':'COMPLETED' if complete else 'PROCESSING'} if approved else None,
        'compensation':{'amount_minor':d['compensation_due_minor'],'currency':d['currency'],'status':'COMPLETED' if c.status=='COMPLETED' else 'PENDING'} if approved and d.get('compensation_due_minor') else None,
        'double_compensation':approved and c.fault_party=='SUPPLIER','total_return_minor':d.get('actual_paid_minor',0)+d.get('compensation_due_minor',0) if approved else None,
        'retry_allowed':c.status in {'APPROVED','CANCELLED_REFUND_PENDING','COMPENSATION_PENDING'},'data_mode':'SIMULATION','external_live':False}
    if internal:
        li=s.scalar(select(Liability).where(Liability.case_id==p.case_id));comp=s.scalar(select(Compensation).where(Compensation.liability_id==li.liability_id)) if li else None
        result.update(requester_id=p.requester_id,evidence=deepcopy(p.evidence_json),submitted_references=p.request_json['submitted_references'],decision=deepcopy(p.decision_json),
            liability={col.name:getattr(li,col.name) for col in li.__table__.columns} if li else None,
            compensation={'compensation_id':comp.compensation_id,'amount_minor':comp.amount_minor,'currency':comp.currency,'status':comp.status} if comp else None)
    return result


def status(case_id,account=None,internal=False):
    with SessionLocal() as s:
        p=s.get(Plan,case_id);c=s.get(Case,case_id)
        if not p or not c or account is not None and p.account_id!=account:raise ValueError('SUPPLIER_REMEDY_NOT_FOUND')
        return public(s,c,p,internal)


def connector(s,order):
    from go_hotel.connectors.registry import registry
    from go_hotel.connectors.mock_hotel import MockHotelConnector
    pb=s.get(PrebookRow,order.prebook_id);offer=s.get(OfferRow,pb.offer_id) if pb else None
    if not offer:raise ValueError('HOTEL_ORDER_CONTEXT_REQUIRED')
    conn=registry.get(offer.connector_id)
    if type(conn) is not MockHotelConnector:raise ValueError('ISOLATED_SUPPLIER_EXECUTOR_REQUIRED')
    return conn


def cancel_commit(s,c,p,order,reference):
    from go_hotel.services.catalog_credit_value import reserve_supplier
    reserve_supplier(s,order.order_id)
    for root in roots(s,order):
        moves=s.scalars(select(Movement).where(Movement.root_payment_intent_id==root.payment_intent_id)).all()
        if any(m.state!='CONFIRMED' for m in moves):raise ValueError('PAYMENT_RECONCILIATION_REQUIRED')
        for auth in [m for m in moves if m.movement_type=='AUTHORIZATION']:
            used=sum(m.amount_minor for m in moves if m.parent_movement_id==auth.money_movement_id and m.movement_type in {'CAPTURE','RELEASE'})
            if used>auth.amount_minor:raise ValueError('AUTHORIZATION_RECONCILIATION_REQUIRED')
            if used<auth.amount_minor:funds.money.create_in_session(s,root.payment_intent_id,{'movement_type':'RELEASE','parent_movement_id':auth.money_movement_id,'amount_minor':auth.amount_minor-used,'mode':'CONTRACT_SIMULATOR','evidence':['approved-catalog-cancel://'+c.case_id]},'catalog-fault-release:'+c.case_id+':'+auth.money_movement_id,'catalog-fault')
    order.status='CANCELLED';order.version+=1;order.updated_at=now();p.supplier_cancel_reference=reference;p.updated_at=now();c.status='CANCELLED_REFUND_PENDING'
    event(s,order.order_id,'CANCEL_CONFIRMED',p.checker_id,{'case_id':c.case_id,'supplier_confirmation_no':order.supplier_confirmation_no,'supplier_cancel_reference':reference})


async def execute(case_id,expected_decision_hash=None):
    funds.require_isolated();dispatch=False
    with transaction() as s:
        c,p,order=lock(s,case_id)
        if expected_decision_hash is not None and p.decision_hash!=expected_decision_hash:raise ValueError('DISRUPTION_DECISION_CHANGED_REVIEW_REQUIRED')
        if c.status in {'COMPLETED','SUPPLIER_CANCEL_PENDING','UNKNOWN_SUPPLIER_CANCEL'}:return public(s,c,p,True)
        if c.status not in {'APPROVED','CANCELLED_REFUND_PENDING','COMPENSATION_PENDING'}:raise ValueError('APPROVED_CATALOG_REMEDY_OR_RECONCILIATION_REQUIRED')
        if c.status=='APPROVED':
            if order.status!='CONFIRMED' or order.version!=p.decision_json['order_version'] or order.supplier_confirmation_no!=p.decision_json['supplier_confirmation_no']:raise ValueError('SUPPLIER_CANCELLATION_ORDER_CHANGED')
            conn=connector(s,order);confirmation=order.supplier_confirmation_no
            c.status='SUPPLIER_CANCEL_PENDING';p.updated_at=now();dispatch=True
            event(s,order.order_id,'SUPPLIER_CANCEL_DISPATCH_PLANNED',p.checker_id,{'case_id':case_id,'decision_hash':p.decision_hash})
    if dispatch:
        try:result=await conn.cancel(confirmation)
        except BaseException as exc:
            with transaction() as s:
                c,p,order=lock(s,case_id);c.status='UNKNOWN_SUPPLIER_CANCEL';p.updated_at=now()
                event(s,order.order_id,'SUPPLIER_CANCEL_RESULT_UNKNOWN',p.checker_id,{'case_id':case_id})
                result=public(s,c,p,True)
            if isinstance(exc,Exception):return result
            raise
        with transaction() as s:
            c,p,order=lock(s,case_id)
            if result!='CANCELLED':
                c.status='UNKNOWN_SUPPLIER_CANCEL';p.updated_at=now()
                return public(s,c,p,True)
            cancel_commit(s,c,p,order,'isolated-supplier-cancel://'+case_id)
    with transaction() as s:
        c,p,order=lock(s,case_id)
        if c.status=='COMPLETED':return public(s,c,p,True)
        if c.status not in {'CANCELLED_REFUND_PENDING','COMPENSATION_PENDING'}:raise ValueError('SUPPLIER_CANCELLATION_COMPLETION_REQUIRED')
        # Refunds are one transaction with stable identities for every original capture.
        if c.status=='CANCELLED_REFUND_PENDING':
            for line in p.refund_lines_json:
                cap=s.get(Movement,line['capture_id'],with_for_update=True)
                if not cap or cap.state!='CONFIRMED' or cap.root_payment_intent_id!=line['payment_intent_id'] or cap.currency!=order.currency:raise ValueError('CATALOG_REFUND_SOURCE_RECONCILIATION_REQUIRED')
                move=funds.money.create_in_session(s,line['payment_intent_id'],{'movement_type':'REFUND','amount_minor':line['amount_minor'],'parent_movement_id':line['capture_id'],
                    'mode':'CONTRACT_SIMULATOR','evidence':['catalog-supplier-fault://'+case_id+'/'+p.decision_hash]},'catalog-fault-refund:'+case_id+':'+line['capture_id'],'catalog-fault')
                rid='crf_'+digest([case_id,line['capture_id']])[:32]
                original_root=s.scalar(select(Root).where(Root.payment_intent_id==line['payment_intent_id'],Root.business_type=='HOTEL_ORDER'))
                if original_root and original_root.business_id==order.order_id and not s.get(RefundRow,rid):
                    original=s.scalar(select(PaymentRow).where(PaymentRow.order_id==order.order_id,PaymentRow.payment_type=='ORIGINAL_BOOKING',PaymentRow.status=='CAPTURED'))
                    s.add(RefundRow(refund_id=rid,order_id=order.order_id,payment_id=original.payment_id,amount_minor=line['amount_minor'],currency=order.currency,
                        status='COMPLETED',provider_refund_id=move['money_movement_id'],created_at=now(),completed_at=now()))
            from go_hotel.services.catalog_credit_value import complete_supplier
            complete_supplier(s,order.order_id)
            c.status='COMPENSATION_PENDING';p.updated_at=now()
            event(s,order.order_id,'REFUND_COMPLETED',p.checker_id,{'case_id':case_id,'amount_minor':p.decision_json['refund_due_minor']})
    with transaction() as s:
        c,p,order=lock(s,case_id)
        if c.status=='COMPLETED':return public(s,c,p,True)
        known_roots=roots(s,order)
        if s.scalar(select(Movement).where(Movement.root_payment_intent_id.in_([r.payment_intent_id for r in known_roots]),Movement.state!='CONFIRMED')):raise ValueError('PAYMENT_RECONCILIATION_REQUIRED')
        from go_hotel.services.catalog_fault_funding import compensate
        result=compensate(s,p)
        if result['state']=='AWAITING_FUNDS':return public(s,c,p,True)
        c.status='COMPLETED';p.updated_at=now()
        event(s,order.order_id,'SUPPLIER_REMEDY_COMPLETED',p.checker_id,{'case_id':case_id,'decision_hash':p.decision_hash,'compensation':result})
        return public(s,c,p,True)


async def reconcile(case_id,actor):
    """Query the isolated supplier; never re-send an uncertain cancellation."""
    funds.require_isolated()
    with transaction() as s:
        c,p,order=lock(s,case_id)
        if c.status not in {'SUPPLIER_CANCEL_PENDING','UNKNOWN_SUPPLIER_CANCEL'}:raise ValueError('SUPPLIER_CANCEL_RECONCILIATION_NOT_REQUIRED')
        conn=connector(s,order);confirmation=order.supplier_confirmation_no
    result=await conn.status(confirmation)
    with transaction() as s:
        c,p,order=lock(s,case_id)
        if c.status not in {'SUPPLIER_CANCEL_PENDING','UNKNOWN_SUPPLIER_CANCEL'}:return public(s,c,p,True)
        if result=='CANCELLED':cancel_commit(s,c,p,order,'isolated-supplier-status://'+case_id)
        else:c.status='UNKNOWN_SUPPLIER_CANCEL'
        event(s,order.order_id,'SUPPLIER_CANCEL_RECONCILED',actor,{'case_id':case_id,'observed_state':result})
        return public(s,c,p,True)


def assert_money_action(s,intent,typ,amount,parent_id,key):
    """The shared money entry cannot spend funds frozen by a supplier review."""
    oid=intent.business_id if intent.business_type=='HOTEL_ORDER' else None
    if intent.business_type=='HOTEL_CHANGE':
        quote=s.get(ChangeQuoteRow,intent.business_id);oid=quote.order_id if quote else None
    if not oid or typ=='RELEASE':return
    c=s.scalar(select(Case).where(Case.order_id==oid))
    if not c or c.status=='COMPLETED':return
    p=s.get(Plan,c.case_id)
    if not p:raise ValueError('HISTORICAL_SUPPLIER_CASE_RECONCILIATION_REQUIRED')
    if typ=='REFUND' and c.status=='CANCELLED_REFUND_PENDING':
        if digest(p.refund_lines_json)!=p.refund_lines_hash:raise ValueError('CATALOG_REFUND_PLAN_MISMATCH')
        for line in p.refund_lines_json or []:
            if key=='catalog-fault-refund:'+c.case_id+':'+line['capture_id'] and (intent.payment_intent_id,parent_id,amount)==(line['payment_intent_id'],line['capture_id'],line['amount_minor']):return
    raise ValueError('SUPPLIER_REMEDY_FUNDS_RESERVED')


def admin_cases(offset=0):
    with SessionLocal() as s:
        rows=s.scalars(select(Case).order_by(Case.created_at.desc(),Case.case_id).offset(offset).limit(51)).all()
        items=[]
        for c in rows[:50]:
            order=s.get(Order,c.order_id);pb=s.get(PrebookRow,order.prebook_id);offer=s.get(OfferRow,pb.offer_id) if pb else None
            p=s.get(Plan,c.case_id)
            changed=s.scalar(select(OrderChangeRow).where(OrderChangeRow.order_id==order.order_id,OrderChangeRow.status=='CONFIRMED').order_by(OrderChangeRow.confirmed_at.desc()))
            items.append({'case_id':c.case_id,'order_id':c.order_id,'supplier_id':c.supplier_id,'hotel_id':order.hotel_id,
                'room_type_id':offer.room_type_id if offer else None,'check_in':changed.new_check_in if changed else offer.check_in if offer else None,'check_out':changed.new_check_out if changed else offer.check_out if offer else None,
                'state':c.status,'has_independent_plan':p is not None})
        return {'items':items,'next_offset':offset+50 if len(rows)>50 else None}
