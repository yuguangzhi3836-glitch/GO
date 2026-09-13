"""Explicit, amount-bound direct-hotel authorization in isolated environments.

The reservation keeps its canonical offer and dated inventory. Authorization is
not payment, capture or hotel confirmation; no second hotel order is created.
"""
from sqlalchemy import select
from go_hotel.core.config import settings
from go_hotel.db.models import (HostedDirectReservationRow as Reservation, HostedReservationStayRow as Stay,
    HostedDirectRoomOfferRow as Offer, HostedDirectRateVariantRow as Variant,
    HostedDirectHotelRow as Hotel, AlipayAuthorizationRow as Authorization)
from go_hotel.services.hosted_reservation_operations import managed_session, aware
from go_hotel.services.hosted_direct_booking import ident, now, out
from go_hotel.services.alipay_safeguarded_settlement import alipay_safeguarded_settlement_service as payment


def isolated():
    if settings.app_env.lower() not in {'local','test','demo'}:
        raise ValueError('SIMULATED_CHECKOUT_FORBIDDEN_IN_THIS_ENVIRONMENT')


def _simulation_offer(s,r):
    offer=s.get(Offer,r.hosted_offer_id)
    hotel=s.get(Hotel,offer.hosted_hotel_id) if offer else None
    variant=s.scalar(select(Variant).where(Variant.hosted_offer_id==r.hosted_offer_id))
    return bool(hotel and hotel.page_slug=='aoluguya-harbin' and
        hotel.contact_json.get('inventory_data_mode')=='SIMULATION' and
        variant and variant.payment_mode=='CONTRACT_SIMULATOR')


def authorize(account,reservation_id,expected_amount_minor,currency):
    isolated()
    with managed_session() as s:
        stay=s.get(Stay,reservation_id,with_for_update=True)
        r=s.get(Reservation,reservation_id,with_for_update=True)
        if not stay or not r or stay.created_by!=account:raise ValueError('RESERVATION_NOT_FOUND')
        if type(expected_amount_minor) is not int or (r.amount_minor,r.currency)!=(expected_amount_minor,currency):
            raise ValueError('ORDER_AMOUNT_CHANGED_RECONFIRM_REQUIRED')
        if not _simulation_offer(s,r):raise ValueError('ISOLATED_HOTEL_RATE_REQUIRED')
        if stay.operational_state not in {'PENDING_HOTEL_CONFIRMATION','CONFIRMED'}:
            raise ValueError('RESERVATION_NOT_AUTHORIZABLE')
        if stay.operational_state=='PENDING_HOTEL_CONFIRMATION' and aware(stay.confirmation_expires_at)<=now():
            raise ValueError('RESERVATION_CONFIRMATION_EXPIRED')
        rows=s.scalars(select(Authorization).where(Authorization.hosted_reservation_id==reservation_id).with_for_update()).all()
        active=[a for a in rows if a.state!='CONTRACT_RELEASED_NOT_ALIPAY']
        if len(active)>1:raise ValueError('PAYMENT_RECONCILIATION_REQUIRED')
        if active:
            a=active[0]
            if a.state!='CONTRACT_FROZEN_NOT_ALIPAY' or a.external_invoked or (a.amount_minor,a.currency)!=(r.amount_minor,r.currency):
                raise ValueError('PAYMENT_RECONCILIATION_REQUIRED')
        else:
            if rows:raise ValueError('RELEASED_AUTHORIZATION_REBOOK_REQUIRED')
            if r.payment_state not in {'ALIPAY_APPLICATION_PENDING_NO_CHARGE','NO_PAYMENT_NO_REFUND_REQUIRED'}:
                raise ValueError('PAYMENT_RECONCILIATION_REQUIRED')
            a=Authorization(authorization_id=ident('aauth'),hosted_reservation_id=reservation_id,
                amount_minor=r.amount_minor,currency=r.currency,state='CONTRACT_FROZEN_NOT_ALIPAY',
                external_invoked=False,external_authorization_reference=None,settlement_eligible=False,
                idempotency_key='direct-authorization:'+reservation_id+':'+str(len(rows)),updated_at=now())
            s.add(a);s.flush()
            payment._event(s,a.authorization_id,'AUTHORIZATION_CONTRACT_FROZEN',
                {'amount_minor':r.amount_minor,'actor':account,'explicit_amount_confirmed':True},False,False)
        from go_hotel.services import hosted_money
        hosted_money.ensure_authorization(s,r,stay,a)
        r.payment_state='CONTRACT_AUTHORIZED_NOT_ALIPAY';r.updated_at=now()
        hosted_money.project(s,r,'FUNDS_AUTHORIZED')
        s.commit()
        return {'reservation_id':reservation_id,'authorization':out(a),
            'payment_state':r.payment_state,'payment_captured':False,'data_mode':'SIMULATION','external_live':False}


def release_contract_in_session(s,r,reason):
    """Release only known local freezes, atomically with reservation inventory."""
    isolated()
    if not _simulation_offer(s,r):raise ValueError('ISOLATED_HOTEL_RATE_REQUIRED')
    rows=s.scalars(select(Authorization).where(Authorization.hosted_reservation_id==r.hosted_reservation_id,
        Authorization.state!='CONTRACT_RELEASED_NOT_ALIPAY').with_for_update()).all()
    if not rows or any(a.external_invoked or a.state!='CONTRACT_FROZEN_NOT_ALIPAY' for a in rows):
        raise ValueError('PAYMENT_RELEASE_OR_REFUND_REQUIRED')
    for a in rows:
        from go_hotel.services import hosted_money
        hosted_money.release(s,a,reason)
        a.state='CONTRACT_RELEASED_NOT_ALIPAY';a.updated_at=now()
        payment._event(s,a.authorization_id,'AUTHORIZATION_RELEASED',{'reason':reason},False,False)
    r.payment_state='NO_PAYMENT_NO_REFUND_REQUIRED';r.updated_at=now();s.flush()


def authorization_summary(s,r):
    rows=s.scalars(select(Authorization).where(Authorization.hosted_reservation_id==r.hosted_reservation_id)
        .order_by(Authorization.updated_at,Authorization.authorization_id)).all()
    return [{'authorization_id':a.authorization_id,'amount_minor':a.amount_minor,'currency':a.currency,
        'state':a.state,'external_invoked':a.external_invoked} for a in rows]
