"""Role-scoped ticket operations, with optimistic commands in the native audit chain.

A supplier records a receipt; an order operator applies it through the existing
resolution authority. Verification and follow-up are separate durable actions.
"""
from copy import deepcopy
from sqlalchemy import select
from go_hotel.autonomy.durable import transaction, digest
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import FlightOrderRow, RailOrderRow, AttractionOrderRow, AttractionChangeQuoteRow, JourneyRecoveryEvidenceChainRow
from go_hotel.services.transaction_order_view import supplier_query
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence, _stable_hash

MODELS={'FLIGHT':FlightOrderRow,'RAIL':RailOrderRow,'ATTRACTION':AttractionOrderRow}


def _order(s,v,oid,p,lock=False):
    if v not in MODELS:raise ValueError('TICKET_ORDER_NOT_FOUND')
    if p.actor_type=='SUPPLIER_USER' and p.supplier_id:
        query=supplier_query(v,p.supplier_id).where(MODELS[v].order_id==oid)
    elif p.actor_type=='GO_ADMIN':query=select(MODELS[v]).where(MODELS[v].order_id==oid)
    else:raise ValueError('TICKET_ORDER_NOT_FOUND')
    order=s.scalar(query.with_for_update() if lock else query)
    if order is None:raise ValueError('TICKET_ORDER_NOT_FOUND')
    return order


def _events(s,v,oid):
    entries=list(s.scalars(select(JourneyRecoveryEvidenceChainRow).where(
        JourneyRecoveryEvidenceChainRow.execution_id==f'rc20:{v}:{oid}').order_by(JourneyRecoveryEvidenceChainRow.sequence_no)))
    previous='GENESIS';events=[]
    for sequence,r in enumerate(entries,1):
        b=r.evidence_json
        if (r.sequence_no!=sequence or r.previous_hash!=previous or b.get('previous_hash')!=previous
            or b.get('sequence_no')!=sequence or b.get('vertical')!=v or b.get('order_id')!=oid
            or b.get('kind')!=r.evidence_kind or b.get('status')!=r.observed_status
            or r.evidence_hash!=_stable_hash(b) or r.entry_hash!=_stable_hash({'evidence_hash':r.evidence_hash,'previous_hash':previous,'sequence_no':sequence})):
            raise ValueError('TICKET_OPERATIONS_AUDIT_INVALID')
        previous=r.entry_hash
        if r.evidence_kind=='TICKET_OPERATIONS':events.append(deepcopy(b['payload']))
    return events


def _state(events):
    state={'revision':len(events),'stage':'NONE','assignee':None,'receipt':None,'receipt_actor':None,'applied_by':None,'verified_order_hash':None,'contributors':sorted({e['actor_id'] for e in events if e['action'] in {'APPLY_ATTEMPT','APPLY','RECEIPT'}})}
    for e in events:
        if e['action']=='REGISTER':state.update(stage='REGISTERED',assignee=None,receipt=None,receipt_actor=None,applied_by=None,verified_order_hash=None)
        elif e['action']=='CLAIM':state.update(stage='ASSIGNED',assignee=e['actor_id'],receipt=None,receipt_actor=None,applied_by=None)
        elif e['action']=='RECEIPT':state.update(stage='RECEIPT_RECORDED',receipt=e['receipt'],receipt_actor=e['actor_id'])
        elif e['action']=='APPLY':state.update(stage='APPLIED',applied_by=e['actor_id'])
        elif e['action']=='VERIFY':state.update(stage='VERIFIED',verified_order_hash=e.get('order_fingerprint'))
        elif e['action']=='FOLLOW_UP':state.update(stage='CLOSED')
    return state


def _attraction_fingerprint(order):
    return digest([order.order_id,order.status,order.visit_date,order.session_time,order.quantity,
        order.total_amount_minor,order.currency,order.voucher_code,order.supplier_reference,str(order.updated_at)])


def _verify_attraction_outcome(s,order,state):
    if order.status not in {'CONFIRMED','FULFILLED','REFUNDED'}:
        raise ValueError('TICKET_OPERATIONS_OUTCOME_UNRESOLVED')
    if state.get('verified_order_hash') and state['verified_order_hash']!=_attraction_fingerprint(order):
        raise ValueError('TICKET_OPERATIONS_OUTCOME_CHANGED')
    from go_hotel.flight.money_view import read
    money=read(order,vertical='ATTRACTION')
    if not money['verified'] or money.get('has_pending') or money['captured_minor']!=order.total_amount_minor:
        raise ValueError('TICKET_OPERATIONS_MONEY_UNRESOLVED')
    if order.status=='REFUNDED':
        from go_hotel.services import vertical_refund_recovery as recovery
        op=recovery._operation(s,'ATTRACTION',order.order_id)
        if not op or op.state!='COMPLETED':raise ValueError('TICKET_OPERATIONS_MONEY_UNRESOLVED')
        recovery._verify(op,order.account_id)
        recovery._completed_in(s,op,order)
    elif state['receipt']['state']=='CLOSED_BY_SUPPLIER' or money['refunded_minor']:
        raise ValueError('TICKET_OPERATIONS_MONEY_UNRESOLVED')


def view(v,oid,p):
    with SessionLocal() as s:
        order=_order(s,v,oid,p);events=_events(s,v,oid);account=order.account_id
        if v=='ATTRACTION':
            from go_hotel.flight.money_view import read
            attraction_money=read(order,vertical=v)
    if v=='ATTRACTION':
        from go_hotel.attractions.service import attraction_service
        data=attraction_service.get(account,oid)
        data['attendees']=[{'full_name':x.get('full_name'),'type':x.get('type')} for x in data.get('attendees',[])]
        # Only the pending quote identity and requested session are needed by operators.
        with SessionLocal() as s:
            data['change_quotes']=[{'quote_id':q.quote_id,'status':q.status,
                'changes':{'visit_date':q.new_visit_date,'session_time':q.new_session_time}}
                for q in s.scalars(select(AttractionChangeQuoteRow).where(
                    AttractionChangeQuoteRow.order_id==oid,AttractionChangeQuoteRow.status=='PENDING_SUPPLIER'))]
        data.pop('evidence',None)
        data['money_summary']=attraction_money
    elif v=='FLIGHT':
        from go_hotel.flight.service import flight_service as svc
        data=svc.order(account,oid)
    else:
        from go_hotel.rail.service import rail_service as svc
        data=svc.order(account,oid)
    # Traveler documents/account identifiers are not needed in an operations workbench.
    data.pop('account_id',None)
    data['passengers']=[{'full_name':x.get('full_name'),'type':x.get('type')} for x in data.get('passengers',[])]
    for c in data.get('coupons',[]):c.pop('account_id',None)
    data.pop('coupon_refunds',None)
    return {'order':data,'workflow':_state(events),'events':events,
        'can_operate':('admin:orders' if p.actor_type=='GO_ADMIN' else 'supplier:orders') in p.permissions,
        'can_apply':p.actor_type=='GO_ADMIN' and 'admin:orders' in p.permissions}


def command(v,oid,p,body):
    permission='admin:orders' if p.actor_type=='GO_ADMIN' else 'supplier:orders'
    if permission not in p.permissions:raise ValueError('TICKET_OPERATIONS_PERMISSION_DENIED')
    action=body['action'];request_hash=digest({'actor':p.user_id,'body':body})
    with transaction(SessionLocal) as s:
        order=_order(s,v,oid,p,True);events=_events(s,v,oid);state=_state(events)
        previous=next((e for e in events if e['command_id']==body['command_id']),None)
        if previous:
            if previous['request_hash']!=request_hash:raise ValueError('TICKET_OPERATIONS_COMMAND_CONFLICT')
            if v=='ATTRACTION' and previous['action'] in {'VERIFY','FOLLOW_UP'}:
                if previous.get('order_fingerprint')!=_attraction_fingerprint(order):raise ValueError('TICKET_OPERATIONS_OUTCOME_CHANGED')
                _verify_attraction_outcome(s,order,state)
            return {'workflow':state,'idempotent_replay':True}
        if state['revision']!=body['expected_revision']:raise ValueError('TICKET_OPERATIONS_STALE_RELOAD')
        if action=='REGISTER':
            if state['stage'] not in {'NONE','CLOSED'}:raise ValueError('TICKET_OPERATIONS_ACTIVE')
        elif action=='CLAIM':
            if state['stage'] not in {'REGISTERED','ASSIGNED','APPLIED'}:raise ValueError('TICKET_OPERATIONS_STAGE_INVALID')
            if state['assignee'] not in {None,p.user_id} and p.actor_type!='GO_ADMIN':raise ValueError('TICKET_OPERATIONS_TAKEOVER_DENIED')
        elif action=='RECEIPT':
            if state['stage']!='ASSIGNED' or state['assignee']!=p.user_id:raise ValueError('TICKET_OPERATIONS_ASSIGNEE_REQUIRED')
            if not body.get('receipt'):raise ValueError('TICKET_OPERATIONS_RECEIPT_REQUIRED')
            receipt=body['receipt']
            states={'CONFIRMED','CLOSED_BY_SUPPLIER','UNKNOWN_EXTERNAL_STATE'} if v=='ATTRACTION' else {'TICKETED','FAILED','UNKNOWN_EXTERNAL_STATE'}
            if receipt.get('state') not in states or (v=='ATTRACTION' and receipt.get('ticket_numbers')) or (v!='ATTRACTION' and receipt.get('voucher_code')):
                raise ValueError('TICKET_OPERATIONS_RECEIPT_INVALID')
            if not str(receipt.get('evidence_reference') or '').strip():raise ValueError('TICKET_OPERATIONS_RECEIPT_INVALID')
            if v=='ATTRACTION' and receipt['state']=='CONFIRMED' and not all(str(receipt.get(k) or '').strip() for k in ['supplier_reference','voucher_code']):
                raise ValueError('ATTRACTION_RECONCILIATION_VOUCHER_REQUIRED')
        elif action=='VERIFY':
            if (p.actor_type!='GO_ADMIN' or state['stage']!='APPLIED'
                or p.user_id in state['contributors']):raise ValueError('TICKET_OPERATIONS_INDEPENDENT_VERIFIER_REQUIRED')
            terminal={'CONFIRMED','CLOSED_BY_SUPPLIER','FULFILLED','REFUNDED','CANCELLED'} if v=='ATTRACTION' else {'TICKETED','FAILED','REFUNDED','CANCELLED'}
            if order.status not in terminal:raise ValueError('TICKET_OPERATIONS_OUTCOME_UNRESOLVED')
            if v=='ATTRACTION':_verify_attraction_outcome(s,order,state)
        elif action=='FOLLOW_UP':
            if state['stage']!='VERIFIED' or p.actor_type!='GO_ADMIN':raise ValueError('TICKET_OPERATIONS_STAGE_INVALID')
            if v=='ATTRACTION':_verify_attraction_outcome(s,order,state)
        else:raise ValueError('TICKET_OPERATIONS_ACTION_INVALID')
        event={**body,'actor_id':p.user_id,'actor_type':p.actor_type,'supplier_id':p.supplier_id,'request_hash':request_hash}
        if v=='ATTRACTION' and action in {'VERIFY','FOLLOW_UP'}:event['order_fingerprint']=_attraction_fingerprint(order)
        append_vertical_evidence(s,v,oid,'TICKET_OPERATIONS',order.status,event)
        return {'workflow':_state(events+[event]),'idempotent_replay':False}


def apply(v,oid,p,body):
    if p.actor_type!='GO_ADMIN' or 'admin:orders' not in p.permissions:raise ValueError('TICKET_OPERATIONS_PERMISSION_DENIED')
    request_hash=digest({'actor':p.user_id,'body':body})
    with transaction(SessionLocal) as s:
        order=_order(s,v,oid,p,True);events=_events(s,v,oid);state=_state(events)
        previous=next((e for e in events if e['command_id']==body['command_id']),None)
        if previous:
            if previous['request_hash']!=request_hash:raise ValueError('TICKET_OPERATIONS_COMMAND_CONFLICT')
            return {'workflow':state,'idempotent_replay':True}
        attempt=next((e for e in events if e['action']=='APPLY_ATTEMPT' and e.get('apply_command_id')==body['command_id']),None)
        if attempt and attempt['request_hash']!=request_hash:raise ValueError('TICKET_OPERATIONS_COMMAND_CONFLICT')
        if state['stage']!='RECEIPT_RECORDED' or (not attempt and state['revision']!=body['expected_revision']):
            raise ValueError('TICKET_OPERATIONS_STALE_RELOAD')
        receipt=state['receipt']
        receipt_event=next(e['command_id'] for e in reversed(events) if e['action']=='RECEIPT')
        if v=='ATTRACTION':
            # This resolution changes only local native order/capacity facts.
            # Keep resolution and workflow completion in one transaction so
            # process death cannot leave an applied order with a pending command.
            from go_hotel.attractions.service import attraction_service
            attraction_service.admin_external_state_in(s,oid,receipt['state'],receipt['evidence_reference'],p.user_id,
                receipt.get('supplier_reference'),receipt.get('voucher_code'),receipt.get('quote_id'))
            event={**body,'action':'APPLY','actor_id':p.user_id,'actor_type':p.actor_type,'supplier_id':None,'request_hash':request_hash}
            append_vertical_evidence(s,v,oid,'TICKET_OPERATIONS',order.status,event)
            return {'workflow':_state(events+[event]),'idempotent_replay':False}
        if attempt and (attempt.get('receipt_event')!=receipt_event or attempt.get('receipt_hash')!=digest(receipt)):
            raise ValueError('TICKET_OPERATIONS_STALE_RELOAD')
        if not attempt:
            append_vertical_evidence(s,v,oid,'TICKET_OPERATIONS',order.status,
                {**body,'action':'APPLY_ATTEMPT','command_id':'attempt:'+body['command_id'],
                 'apply_command_id':body['command_id'],'receipt_event':receipt_event,'receipt_hash':digest(receipt),'actor_id':p.user_id,'actor_type':p.actor_type,
                 'supplier_id':None,'request_hash':request_hash})
    if v=='FLIGHT':
        from go_hotel.flight.service import flight_service as svc
    else:
        from go_hotel.rail.service import rail_service as svc
    svc.admin_external_state(oid,receipt['state'],receipt['evidence_reference'],p.user_id,
        receipt.get('supplier_reference'),receipt.get('ticket_numbers'),receipt.get('quote_id'),operation_id=receipt_event)
    with transaction(SessionLocal) as s:
        order=_order(s,v,oid,p,True);events=_events(s,v,oid);state=_state(events)
        prior=next((e for e in events if e['command_id']==body['command_id']),None)
        if prior:
            if prior['request_hash']!=request_hash:raise ValueError('TICKET_OPERATIONS_COMMAND_CONFLICT')
            return {'workflow':state,'idempotent_replay':True}
        if state['stage']!='RECEIPT_RECORDED' or next(e['command_id'] for e in reversed(events) if e['action']=='RECEIPT')!=receipt_event:raise ValueError('TICKET_OPERATIONS_STALE_RELOAD')
        event={**body,'action':'APPLY','actor_id':p.user_id,'actor_type':p.actor_type,'supplier_id':None,'request_hash':request_hash}
        append_vertical_evidence(s,v,oid,'TICKET_OPERATIONS',order.status,event)
        return {'workflow':_state(events+[event]),'idempotent_replay':False}
