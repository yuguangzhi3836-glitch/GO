"""Direct-hotel isolated funds use the shared immutable money graph and ledger.

All mutating helpers run inside the reservation owner's transaction. No provider
calls, fabricated callbacks, bank statements or GO operating-account transfers.
"""
from sqlalchemy import select
from go_hotel.db.models import (
    OmnichannelPaymentIntentRow as Intent, PaymentOrderRootRow as Root,
    PaymentOrderFactBindingRow as Binding, VerticalSourceDecisionRow as SourceDecision, OmnichannelMoneyMovementRow as Movement,
    HostedDirectRoomOfferRow as Offer, HostedDirectHotelRow as Hotel,
    HostedReservationStayRow as Stay, HostedDirectReservationRow as Reservation,
    AlipayAuthorizationRow as Authorization, GuestStayLifecycleRow as GuestStay,
    StayFulfillmentEvidenceRow as Fulfillment, StayDisputeRow as Dispute,
    PostStayDisputeCaseRow as Case, PostStayDecisionRow as Decision,
    RefundEligibilityRow as Refund)
from go_hotel.services.hosted_direct_booking import ident,now,out
from go_hotel.services.omnichannel_payment import digest,legal_entity
from go_hotel.services.unified_money_movement import unified_money_movement_service as money

BUSINESS='HOSTED_HOTEL_AUTHORIZATION'


def root(s,a):
    if not a:return None
    from go_hotel.db.models import HostedFareFundingRow as Funding
    current=s.scalar(select(Funding).where(Funding.hosted_reservation_id==a.hosted_reservation_id).order_by(Funding.generation.desc()))
    if current:
        payment=s.scalar(select(Root).where(Root.payment_intent_id==current.payment_intent_id))
        if not payment or (payment.business_type,payment.business_id)!=('HOSTED_HOTEL_FARE_CHANGE',current.quote_id):raise ValueError('FARE_FUNDING_ROOT_MISMATCH')
        return payment
    return s.scalar(select(Root).where(Root.business_type==BUSINESS,Root.business_id==a.authorization_id))


def require_isolated():
    from go_hotel.services.hosted_checkout import isolated
    isolated()


def movements(s,a):
    if not a:return []
    from go_hotel.db.models import HostedFareFundingRow as Funding
    original=s.scalar(select(Root).where(Root.business_type==BUSINESS,Root.business_id==a.authorization_id))
    ids=[x for x in s.scalars(select(Funding.payment_intent_id).where(Funding.hosted_reservation_id==a.hosted_reservation_id))]
    if original:ids.append(original.payment_intent_id)
    return list(s.scalars(select(Movement).where(Movement.root_payment_intent_id.in_(ids)).order_by(Movement.created_at,Movement.money_movement_id))) if ids else []


def refundable_captures(s,a):
    from go_hotel.services.hosted_fare_value import is_forfeiture
    return [m for m in movements(s,a) if m.movement_type=='CAPTURE' and m.state=='CONFIRMED' and not is_forfeiture(m)]


def active_movements(s,a):
    current=root(s,a)
    return [m for m in movements(s,a) if current and m.root_payment_intent_id==current.payment_intent_id]


def require_known(s,a):
    if a.external_invoked or a.state=='UNKNOWN_EXTERNAL_STATE' or any(m.state!='CONFIRMED' for m in movements(s,a)):
        raise ValueError('PAYMENT_RECONCILIATION_REQUIRED')
    from go_hotel.services.hosted_credit_value import allocation,checked
    allocated=allocation(s,a.hosted_reservation_id)
    if allocated:checked(s,allocated.credit_id)


def ensure_authorization(s,r,stay,a,credited_minor=0):
    require_isolated()
    existing=root(s,a)
    require_known(s,a)
    offer=s.get(Offer,r.hosted_offer_id)
    if type(credited_minor) is not int or credited_minor<0 or (a.amount_minor+credited_minor,a.currency)!=(r.amount_minor,r.currency):raise ValueError('AUTHORIZATION_ORDER_FACT_MISMATCH')
    if credited_minor:
        from go_hotel.services.hosted_credit_value import allocation
        allocated=allocation(s,r.hosted_reservation_id)
        if not allocated or allocated.state!='ACTIVE' or allocated.applied_minor!=credited_minor:raise ValueError('CREDIT_ALLOCATION_FACT_REQUIRED')
    if existing:
        intent=s.get(Intent,existing.payment_intent_id)
        if (intent.payer_id,intent.payee_id,intent.amount_minor,intent.currency)!=(stay.created_by,offer.hosted_hotel_id,a.amount_minor,a.currency):
            raise ValueError('PAYMENT_ORDER_FACT_MISMATCH')
    else:
        if a.external_invoked or a.state!='CONTRACT_FROZEN_NOT_ALIPAY':raise ValueError('FROZEN_CONTRACT_REQUIRED_FOR_MONEY_GRAPH')
        iid=ident('opi');timestamp=now();entity=legal_entity(a.currency)
        intent=Intent(payment_intent_id=iid,business_type=BUSINESS,business_id=a.authorization_id,
            payer_id=stay.created_by,payee_id=offer.hosted_hotel_id,operation='AUTHORIZE',
            amount_minor=a.amount_minor,currency=a.currency,channel_priority_json=['LOCAL_MARKET'],
            selected_channel='LOCAL_MARKET',state='SUCCEEDED',idempotency_key='direct-intent:'+a.authorization_id,
            automatic_fallback_allowed=False,user_channel_consent_at=timestamp,created_at=timestamp,updated_at=timestamp)
        s.add(intent);s.flush()
        s.add(Root(payment_order_root_id=ident('por'),business_type=BUSINESS,business_id=a.authorization_id,
            payment_intent_id=iid,legal_entity_id=entity,state='ACTIVE',root_hash=digest([BUSINESS,a.authorization_id,iid,entity]),created_at=timestamp))
        facts={'reservation_id':r.hosted_reservation_id,'hosted_offer_id':r.hosted_offer_id,
            'payer_id':stay.created_by,'payee_id':offer.hosted_hotel_id,'amount_minor':a.amount_minor,'currency':a.currency}
        if credited_minor:facts.update(order_total_minor=r.amount_minor,prepaid_credit_minor=credited_minor,credit_id=allocated.credit_id)
        source_id=ident('vsd')
        s.add(SourceDecision(vertical_source_decision_id=source_id,vertical='HOTEL',business_id=r.hosted_reservation_id,
            selected_source_id=offer.hosted_hotel_id,selected_source_type='HOSTED_DIRECT_SIMULATION',route='GO_HOSTED_DIRECT',
            authority_reference='isolated-offer://'+r.hosted_offer_id,evidence_reference='contract-simulator://hosted/'+r.hosted_reservation_id,
            candidate_snapshot_json=[facts],reason_codes_json=['USER_SELECTED_OFFICIAL_ROOM','ISOLATED_DATED_RATE'],
            decision_hash=digest([BUSINESS,a.authorization_id,facts]),created_at=timestamp))
        s.add(Binding(payment_order_fact_binding_id=ident('pofb'),payment_intent_id=iid,business_type=BUSINESS,
            business_id=a.authorization_id,payer_id=stay.created_by,payee_id=offer.hosted_hotel_id,
            amount_minor=a.amount_minor,currency=a.currency,legal_entity_id=entity,source_decision_id=source_id,
            request_fingerprint=digest(facts),order_fact_hash=digest(facts),
            evidence_reference='contract-simulator://hosted/'+r.hosted_reservation_id,created_at=timestamp))
        s.flush()
    if not a.amount_minor:return {'payment_intent_id':intent.payment_intent_id,'state':'PREPAID_WITHOUT_CASH_AUTHORIZATION'}
    return money.create_in_session(s,intent.payment_intent_id,{'movement_type':'AUTHORIZATION',
        'amount_minor':a.amount_minor,'mode':'CONTRACT_SIMULATOR','evidence':['direct-authorization://'+a.authorization_id]},
        'direct-auth:'+a.authorization_id,'hosted-money')


def release(s,a,reason):
    payment=root(s,a)
    if not payment:return None # Historical contract-only evidence remains historical.
    require_isolated();require_known(s,a)
    from go_hotel.db.models import HostedOrderFareSnapshotRow
    stay=s.get(Stay,a.hosted_reservation_id)
    if stay and stay.operational_state=='CONFIRMED' and s.get(HostedOrderFareSnapshotRow,a.hosted_reservation_id):raise ValueError('CONFIRMED_CANCELLATION_FARE_QUOTE_REQUIRED')
    auth=next((m for m in active_movements(s,a) if m.movement_type=='AUTHORIZATION' and m.state=='CONFIRMED'),None)
    if not auth:raise ValueError('CONFIRMED_AUTHORIZATION_REQUIRED')
    return money.create_in_session(s,payment.payment_intent_id,{'movement_type':'RELEASE',
        'parent_movement_id':auth.money_movement_id,'amount_minor':a.amount_minor,'mode':'CONTRACT_SIMULATOR',
        'evidence':['direct-release://'+a.authorization_id+'/'+reason]},'direct-release:'+a.authorization_id,'hosted-money')


def fulfillment(s,r,a):
    guest=s.scalar(select(GuestStay).where(GuestStay.hosted_reservation_id==r.hosted_reservation_id).with_for_update())
    if not guest or guest.state!='CHECKED_OUT':raise ValueError('COMPLETED_GUEST_STAY_REQUIRED')
    if s.scalar(select(Dispute).where(Dispute.stay_lifecycle_id==guest.stay_lifecycle_id,Dispute.state=='OPEN_SETTLEMENT_FROZEN')):
        raise ValueError('OPEN_FULFILLMENT_DISPUTE')
    evidence=s.scalar(select(Fulfillment).where(Fulfillment.stay_lifecycle_id==guest.stay_lifecycle_id,Fulfillment.state=='DUAL_CONFIRMED'))
    from go_hotel.services.hosted_fare_value import basis
    if not evidence or type(evidence.fulfilled_amount_minor) is not int or not 0<=evidence.fulfilled_amount_minor<=basis(s,r)['current_room_value_minor']:
        raise ValueError('VALID_DUAL_FULFILLMENT_EVIDENCE_REQUIRED')
    return guest,evidence


def settle(s,r,stay,a):
    require_isolated();payment=root(s,a)
    if not payment:raise ValueError('HOSTED_MONEY_GRAPH_REQUIRED')
    require_known(s,a)
    guest,evidence=fulfillment(s,r,a)
    auth=next((m for m in active_movements(s,a) if m.movement_type=='AUTHORIZATION' and m.state=='CONFIRMED'),None)
    from go_hotel.services.hosted_credit_value import prepaid,settle_allocation
    from go_hotel.services.hosted_fare_value import basis,capture_forfeiture
    value=basis(s,r)
    amount=max(0,evidence.fulfilled_amount_minor-(prepaid(s,r.hosted_reservation_id)-value['prepaid_forfeiture_minor']))
    if amount and not auth:raise ValueError('CONFIRMED_AUTHORIZATION_REQUIRED')
    refs=[evidence.hotel_evidence_reference,evidence.guest_checkout_reference]
    if amount:money.create_in_session(s,payment.payment_intent_id,{'movement_type':'CAPTURE','amount_minor':amount,
        'parent_movement_id':auth.money_movement_id,'mode':'CONTRACT_SIMULATOR','evidence':refs},
        'direct-capture:'+a.authorization_id,'hosted-money')
    capture_forfeiture(s,r,a,refs)
    remaining=s.get(Intent,payment.payment_intent_id).amount_minor-amount-value['cash_forfeiture_minor']
    if remaining:money.create_in_session(s,payment.payment_intent_id,{'movement_type':'RELEASE','amount_minor':remaining,
        'parent_movement_id':auth.money_movement_id,'mode':'CONTRACT_SIMULATOR','evidence':refs},
        'direct-unfulfilled-release:'+a.authorization_id,'hosted-money')
    settle_allocation(s,r,evidence.fulfilled_amount_minor,'hosted-money',refs)
    return amount


def summary(s,r):
    a=s.scalar(select(Authorization).where(Authorization.hosted_reservation_id==r.hosted_reservation_id))
    rows=movements(s,a)
    from go_hotel.services.hosted_credit_value import summary as credit_summary,reconciliation_required
    credit=credit_summary(s,r.hosted_reservation_id)
    if not rows and not credit['applied_credit']:return None
    totals={kind.lower()+'_minor':sum(m.amount_minor for m in rows if m.movement_type==kind and m.state=='CONFIRMED')
        for kind in ['AUTHORIZATION','CAPTURE','RELEASE','REFUND']}
    payment=root(s,a)
    guest=s.scalar(select(GuestStay).where(GuestStay.hosted_reservation_id==r.hosted_reservation_id))
    refund_rows=list(s.scalars(select(Refund).join(Decision,Decision.post_stay_decision_id==Refund.post_stay_decision_id)
        .join(Case,Case.dispute_case_id==Decision.dispute_case_id).where(Case.stay_lifecycle_id==guest.stay_lifecycle_id))) if guest else []
    refund_rows=[x for x in refund_rows if x.eligible_amount_minor>0]
    state='REFUND_PROCESSING' if any(x.decision in {'REFUND_PENDING_SIMULATION','REFUND_ELIGIBLE_CONTRACT_ONLY'} for x in refund_rows) else 'REFUND_COMPLETED' if refund_rows and all(x.decision=='REFUND_CONFIRMED_SIMULATION' for x in refund_rows) else 'NOT_REQUESTED'
    from go_hotel.db.models import HostedCreditRefundPlanRow
    plans=s.scalars(select(HostedCreditRefundPlanRow).where(HostedCreditRefundPlanRow.hosted_reservation_id==r.hosted_reservation_id)).all()
    credit_refunded=sum(x['amount_minor'] for p in plans if (e:=s.get(Refund,p.refund_eligibility_id)) and e.decision=='REFUND_CONFIRMED_SIMULATION' for x in p.plan_json if x['kind']=='CREDIT')
    from go_hotel.services.hosted_fare_value import basis
    return {**totals,**basis(s,r),'refundable_capture_minor':sum(m.amount_minor for m in refundable_captures(s,a)),'credit_refund_minor':credit_refunded,'total_refund_minor':totals['refund_minor']+credit_refunded,'credit':credit,'prepaid_credit_minor':credit['prepaid_minor'],'payment_intent_id':payment.payment_intent_id,'held_minor':totals['authorization_minor']-totals['capture_minor']-totals['release_minor'],
        'refund_state':state,'refund_cycle_count':len(refund_rows),'reconciliation_required':bool(a.external_invoked or a.state=='UNKNOWN_EXTERNAL_STATE' or any(m.state!='CONFIRMED' for m in rows) or reconciliation_required(s,r.hosted_reservation_id)),'movements':[{'money_movement_id':m.money_movement_id,'type':m.movement_type,
            'amount_minor':m.amount_minor,'state':m.state,'parent_movement_id':m.parent_movement_id} for m in rows],
        'data_mode':'SIMULATION','external_live':False}


def project(s,r,event):
    """Direct reservations join GO Trips without inventing another booking."""
    from go_hotel.services.consumer_unified_lifecycle import consumer_unified_lifecycle_service as lifecycle
    s.flush();stay=s.get(Stay,r.hosted_reservation_id)
    if not stay:return
    offer=s.get(Offer,r.hosted_offer_id);hotel=s.get(Hotel,offer.hosted_hotel_id)
    guest=s.scalar(select(GuestStay).where(GuestStay.hosted_reservation_id==r.hosted_reservation_id))
    native=stay.operational_state
    state='CONVERTED_TO_CREDIT' if native=='CONVERTED_TO_CREDIT' else 'CANCELLED' if native in {'CANCELLED','REJECTED','EXPIRED'} else 'CONFIRMED' if native=='CONFIRMED' else 'PENDING'
    if guest and guest.state=='IN_HOUSE':state='IN_PROGRESS'
    if guest and guest.state in {'CHECKED_OUT','NO_SHOW'}:state='COMPLETED'
    funds=summary(s,r)
    payment_state='UNKNOWN_EXTERNAL_STATE' if funds and funds['reconciliation_required'] else 'PAID' if funds and funds['capture_minor'] else 'PREPAID' if funds and funds.get('prepaid_credit_minor') and not funds['held_minor'] else 'AUTHORIZED' if funds and funds['held_minor'] else 'RELEASED' if funds and funds['release_minor'] else 'PENDING'
    return lifecycle.project_in_session(s,{'account_id':stay.created_by,'vertical':'HOTEL','order_id':r.hosted_reservation_id,
        'supplier_id':hotel.hosted_hotel_id,'title':hotel.supplier_name+' · '+offer.room_name,
        'lifecycle_state':state,'payment_state':payment_state,'refund_state':funds['refund_state'] if funds else 'NOT_REQUESTED',
        'change_allowed':state in {'PENDING','CONFIRMED'} and not (funds and (funds['held_minor'] or funds['capture_minor'])),
        'cancel_allowed':native=='PENDING_HOTEL_CONFIRMATION','evidence_reference':'hosted://'+r.hosted_reservation_id+'/'+event,
        'source_updated_at':now(),'event_type':event,'facts':{'native_status':r.reservation_state,
            'check_in':r.check_in,'check_out':r.check_out,'total_amount_minor':r.amount_minor,'currency':r.currency,
            'detail_url':'/go-app/direct.html?reservation='+r.hosted_reservation_id,'funds':funds,'refund_cycle_count':funds['refund_cycle_count'] if funds else 0,
            'seller_id':hotel.hosted_hotel_id,'payee_id':hotel.hosted_hotel_id,'fulfiller_id':hotel.hosted_hotel_id}},allow_new_refund_cycle=True)


def execute_refund(eligibility_id):
    from go_hotel.db.models import HostedCreditRefundPlanRow
    from go_hotel.db.session import SessionLocal
    with SessionLocal() as probe:credit_plan=probe.get(HostedCreditRefundPlanRow,eligibility_id) is not None
    if credit_plan:
        from go_hotel.services.hosted_credit_refunds import execute
        return execute(eligibility_id)
    from go_hotel.services.alipay_safeguarded_settlement import transaction
    from go_hotel.services.post_stay_dispute import locked_case
    require_isolated()
    def context(s):
        eligibility=s.get(Refund,eligibility_id)
        decision=s.get(Decision,eligibility.post_stay_decision_id) if eligibility else None
        if not decision:raise ValueError('REFUND_ELIGIBILITY_NOT_FOUND')
        case=locked_case(s,decision.dispute_case_id)
        eligibility=s.get(Refund,eligibility_id,with_for_update=True,populate_existing=True)
        decision=s.get(Decision,eligibility.post_stay_decision_id,populate_existing=True)
        guest=s.get(GuestStay,case.stay_lifecycle_id)
        r=s.get(Reservation,guest.hosted_reservation_id)
        a=s.scalar(select(Authorization).where(Authorization.hosted_reservation_id==r.hosted_reservation_id))
        payment=root(s,a)
        if not payment:raise ValueError('REAL_ALIPAY_REFUND_EXECUTOR_NOT_CONFIGURED')
        require_known(s,a)
        capture=s.get(Movement,eligibility.original_payment_reference) if eligibility.original_payment_reference else None
        if not capture or capture.root_payment_intent_id!=payment.payment_intent_id or capture not in refundable_captures(s,a):
            raise ValueError('ORIGINAL_CONFIRMED_CAPTURE_REQUIRED')
        if decision.state!='APPROVED_CONTRACT_ONLY' or not decision.checker_id or decision.checker_id==decision.requester_id:
            raise ValueError('APPROVED_INDEPENDENT_REFUND_DECISION_REQUIRED')
        if eligibility.eligible_amount_minor!=decision.refund_amount_minor or not 0<eligibility.eligible_amount_minor<=capture.amount_minor:
            raise ValueError('REFUND_APPROVED_AMOUNT_MISMATCH')
        return eligibility,r,payment,capture
    with transaction() as s:
        eligibility,r,payment,capture=context(s)
        if eligibility.decision not in {'REFUND_ELIGIBLE_CONTRACT_ONLY','REFUND_PENDING_SIMULATION','REFUND_CONFIRMED_SIMULATION'}:
            raise ValueError('REFUND_NOT_EXECUTABLE')
        if eligibility.decision=='REFUND_ELIGIBLE_CONTRACT_ONLY':
            eligibility.decision='REFUND_PENDING_SIMULATION'
            project(s,r,'REFUND_REQUESTED')
    with transaction() as s:
        eligibility,r,payment,capture=context(s)
        movement=money.create_in_session(s,payment.payment_intent_id,{'movement_type':'REFUND',
            'parent_movement_id':capture.money_movement_id,'amount_minor':eligibility.eligible_amount_minor,
            'mode':'CONTRACT_SIMULATOR','evidence':['approved-refund://'+eligibility.post_stay_decision_id]},
            'direct-poststay-refund:'+eligibility_id,'hosted-money')
        if eligibility.decision!='REFUND_CONFIRMED_SIMULATION':
            eligibility.decision='REFUND_CONFIRMED_SIMULATION';eligibility.external_refund_invoked=False
            eligibility.blockers_json=[];project(s,r,'REFUND_COMPLETED')
        return {'refund_eligibility_id':eligibility_id,'state':'REFUND_COMPLETED',
            'amount_minor':eligibility.eligible_amount_minor,'currency':r.currency,
            'money_movement_id':movement['money_movement_id'],'original_capture_id':capture.money_movement_id,
            'data_mode':'SIMULATION','external_live':False}

def _unknown_episode_public(row, replay=False):
    return {
        'episode_id': row.episode_id,
        'authorization_id': row.authorization_id,
        'hosted_reservation_id': row.hosted_reservation_id,
        'money_movement_id': row.money_movement_id,
        'funding_leg': row.funding_leg,
        'episode_generation': row.episode_generation,
        'status': row.status,
        'open_evidence_reference': row.open_evidence_reference,
        'open_evidence_digest': row.open_evidence_digest,
        'resolution_decision': row.resolution_decision,
        'resolution_evidence_reference': row.resolution_evidence_reference,
        'resolution_evidence_digest': row.resolution_evidence_digest,
        'opened_by': row.opened_by,
        'resolved_by': row.resolved_by,
        'created_at': row.created_at.isoformat(),
        'resolved_at': row.resolved_at.isoformat() if row.resolved_at else None,
        'replay': replay,
    }


def _unknown_funding_leg(s, authorization, movement):
    from go_hotel.db.models import HostedCreditAllocationRow, HostedStayCreditRow
    if movement.money_movement_id in {m.money_movement_id for m in active_movements(s, authorization)}:
        if movement.movement_type != 'AUTHORIZATION':
            raise ValueError('UNKNOWN_EPISODE_FUNDING_MOVEMENT_REQUIRED')
        return 'CASH_AUTHORIZATION'
    allocated = s.get(HostedCreditAllocationRow, authorization.hosted_reservation_id)
    credit = s.get(HostedStayCreditRow, allocated.credit_id) if allocated else None
    if credit and credit.source_capture_id == movement.money_movement_id and movement.movement_type == 'CAPTURE':
        return 'STAY_CREDIT_SOURCE_CAPTURE'
    raise ValueError('UNKNOWN_EPISODE_FUNDING_MOVEMENT_REQUIRED')


def _append_unknown_audit(s, episode, event_type, actor_id, evidence_digest, payload):
    from go_hotel.db.models import HostedMoneyUnknownEpisodeAuditRow as Audit
    previous = s.scalar(
        select(Audit).where(Audit.episode_id == episode.episode_id)
        .order_by(Audit.sequence.desc()).with_for_update()
    )
    sequence = previous.sequence + 1 if previous else 1
    previous_hash = previous.event_hash if previous else None
    event_hash = digest([
        episode.episode_id, sequence, event_type, actor_id, evidence_digest,
        payload, previous_hash,
    ])
    row = Audit(
        audit_id=ident('hmua'), episode_id=episode.episode_id, sequence=sequence,
        event_type=event_type, actor_id=actor_id, evidence_digest=evidence_digest,
        payload_json=payload, previous_hash=previous_hash, event_hash=event_hash,
        created_at=now(),
    )
    s.add(row)
    s.flush()
    return row


def open_unknown_episode(authorization_id, money_movement_id, evidence_reference, evidence_payload, actor_id):
    """Atomically fence one exact cash/credit funding fact behind a durable episode."""
    from go_hotel.db.models import HostedMoneyUnknownEpisodeRow as Episode
    from go_hotel.db.session import SessionLocal
    if not actor_id or not evidence_reference or not isinstance(evidence_payload, dict):
        raise ValueError('UNKNOWN_EPISODE_EVIDENCE_REQUIRED')
    with SessionLocal.begin() as s:
        authorization = s.get(Authorization, authorization_id, with_for_update=True)
        if not authorization:
            raise ValueError('AUTHORIZATION_NOT_FOUND')
        movement = s.get(Movement, money_movement_id, with_for_update=True)
        if not movement:
            raise ValueError('MONEY_MOVEMENT_NOT_FOUND')
        funding_leg = _unknown_funding_leg(s, authorization, movement)
        evidence_digest = digest([
            authorization_id, authorization.hosted_reservation_id,
            money_movement_id, funding_leg, evidence_reference, evidence_payload,
        ])
        current = s.scalar(
            select(Episode).where(
                Episode.money_movement_id == money_movement_id,
                Episode.status == 'OPEN',
            ).order_by(Episode.episode_generation.desc()).with_for_update()
        )
        if current:
            if (current.authorization_id, current.open_evidence_digest) == (authorization_id, evidence_digest):
                return _unknown_episode_public(current, replay=True)
            raise ValueError('UNKNOWN_EPISODE_EVIDENCE_CONFLICT')
        if movement.state not in {'CONFIRMED', 'UNKNOWN_EXTERNAL_STATE'}:
            raise ValueError('UNKNOWN_EPISODE_CONFIRMED_FUNDING_REQUIRED')
        prior = s.scalars(
            select(Episode).where(Episode.money_movement_id == money_movement_id)
            .order_by(Episode.episode_generation.desc()).with_for_update()
        ).first()
        generation = prior.episode_generation + 1 if prior else 1
        timestamp = now()
        episode = Episode(
            episode_id=ident('hmue'), authorization_id=authorization_id,
            hosted_reservation_id=authorization.hosted_reservation_id,
            money_movement_id=money_movement_id, funding_leg=funding_leg,
            episode_generation=generation, status='OPEN',
            open_evidence_reference=evidence_reference,
            open_evidence_digest=evidence_digest, resolution_decision=None,
            resolution_evidence_reference=None, resolution_evidence_digest=None,
            opened_by=actor_id, resolved_by=None, created_at=timestamp,
            resolved_at=None, updated_at=timestamp,
        )
        movement.state = 'UNKNOWN_EXTERNAL_STATE'
        movement.updated_at = timestamp
        s.add(episode)
        s.flush()
        _append_unknown_audit(
            s, episode, 'UNKNOWN_OPENED', actor_id, evidence_digest,
            {'funding_leg': funding_leg, 'movement_state_from': 'CONFIRMED',
             'movement_state_to': 'UNKNOWN_EXTERNAL_STATE'},
        )
        return _unknown_episode_public(episode)


def resolve_unknown_episode(episode_id, decision, expected_open_evidence_digest,
                            evidence_reference, evidence_payload, actor_id):
    """Resolve only the current episode; movement transition and audit commit together."""
    from go_hotel.db.models import HostedMoneyUnknownEpisodeRow as Episode
    from go_hotel.db.session import SessionLocal
    if decision != 'CONFIRMED':
        raise ValueError('UNKNOWN_EPISODE_RESOLUTION_DECISION_INVALID')
    if not actor_id or not evidence_reference or not isinstance(evidence_payload, dict):
        raise ValueError('UNKNOWN_EPISODE_RESOLUTION_EVIDENCE_REQUIRED')
    resolution_digest = digest([
        episode_id, decision, evidence_reference, evidence_payload,
    ])
    with SessionLocal.begin() as s:
        episode = s.get(Episode, episode_id, with_for_update=True)
        if not episode:
            raise ValueError('UNKNOWN_EPISODE_NOT_FOUND')
        if episode.open_evidence_digest != expected_open_evidence_digest:
            raise ValueError('UNKNOWN_EPISODE_OPEN_DIGEST_MISMATCH')
        if episode.status != 'OPEN':
            if (episode.status, episode.resolution_decision, episode.resolution_evidence_digest) == (
                    'RESOLVED_CONFIRMED', decision, resolution_digest):
                return _unknown_episode_public(episode, replay=True)
            raise ValueError('UNKNOWN_EPISODE_ALREADY_RESOLVED')
        current = s.scalar(
            select(Episode).where(
                Episode.money_movement_id == episode.money_movement_id,
                Episode.status == 'OPEN',
            ).order_by(Episode.episode_generation.desc()).with_for_update()
        )
        if not current or current.episode_id != episode_id:
            raise ValueError('UNKNOWN_EPISODE_STALE')
        movement = s.get(Movement, episode.money_movement_id, with_for_update=True)
        authorization = s.get(Authorization, episode.authorization_id, with_for_update=True)
        if not movement or not authorization:
            raise ValueError('UNKNOWN_EPISODE_FUNDING_FACT_MISSING')
        if _unknown_funding_leg(s, authorization, movement) != episode.funding_leg:
            raise ValueError('UNKNOWN_EPISODE_FUNDING_BINDING_MISMATCH')
        if movement.state != 'UNKNOWN_EXTERNAL_STATE':
            raise ValueError('UNKNOWN_EPISODE_MOVEMENT_STATE_MISMATCH')
        timestamp = now()
        movement.state = 'CONFIRMED'
        movement.updated_at = timestamp
        episode.status = 'RESOLVED_CONFIRMED'
        episode.resolution_decision = decision
        episode.resolution_evidence_reference = evidence_reference
        episode.resolution_evidence_digest = resolution_digest
        episode.resolved_by = actor_id
        episode.resolved_at = timestamp
        episode.updated_at = timestamp
        _append_unknown_audit(
            s, episode, 'UNKNOWN_RESOLVED_CONFIRMED', actor_id, resolution_digest,
            {'funding_leg': episode.funding_leg,
             'movement_state_from': 'UNKNOWN_EXTERNAL_STATE',
             'movement_state_to': 'CONFIRMED',
             'open_evidence_digest': episode.open_evidence_digest},
        )
        return _unknown_episode_public(episode)

