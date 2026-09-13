"""Explicit leg selection and immutable simulated reissue plans."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from sqlalchemy import select
from go_hotel.autonomy.durable import transaction, digest
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (FlightChangePlanRow as Plan, FlightChangeQuoteRow as Quote,
    FlightOrderRow as Order, FlightPrebookRow as Prebook, FlightOfferRow as Offer)
from go_hotel.domain.models import new_id
from go_hotel.core.production_truth_gate import production_truth_required


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def order_facts(order):
    return {'order_id':order.order_id, 'account_id':order.account_id,
            'itinerary':deepcopy(order.current_itinerary), 'passengers':deepcopy(order.passengers),
            'ticket_numbers':list(order.ticket_numbers), 'pnr':order.pnr,
            'amount_minor':order.total_amount_minor, 'currency':order.currency}


def quote_facts(quote):
    return {key:getattr(quote,key) for key in ('quote_id','order_id','new_departure_date',
        'new_flight_number','fare_difference_minor','change_fee_minor','total_due_minor','currency')}


def checked(s, order, quote, require_current=True):
    plan = s.get(Plan, quote.quote_id)
    if not plan or plan.order_id != order.order_id or plan.account_id != order.account_id:
        raise ValueError('FLIGHT_CHANGE_PLAN_INVALID_REQUOTE_REQUIRED')
    if digest(plan.plan_json) != plan.plan_hash or plan.plan_json['quote'] != quote_facts(quote):
        raise ValueError('FLIGHT_CHANGE_PLAN_INTEGRITY_INVALID')
    if require_current and plan.plan_json['order'] != order_facts(order):
        raise ValueError('FLIGHT_CHANGE_ORDER_CHANGED_REQUOTE_REQUIRED')
    return plan


def public(quote, plan):
    data = deepcopy(plan.plan_json)
    entries = data['changes']
    return {**quote_facts(quote), 'status':quote.status, 'quote_hash':plan.plan_hash,
            'changes':entries, 'leg_index':entries[0]['leg_index'] if len(entries)==1 else None,
            'new_itinerary':data['new_itinerary'], 'passenger_count':len(data['order']['passengers']),
            'expires_at':quote.expires_at.isoformat(), 'data_mode':'SIMULATION', 'external_live':False}


def create_quote(account, order_id, new_date=None, leg_index=None, changes=None):
    production_truth_required('FLIGHT','CHANGE_QUOTE')
    with transaction(SessionLocal) as s:
        order = s.get(Order, order_id, with_for_update=True)
        if not order or order.account_id != account or order.status != 'TICKETED':
            raise ValueError('FLIGHT_ORDER_NOT_CHANGEABLE')
        legs = order.current_itinerary
        if changes is not None:
            if new_date is not None or leg_index is not None:
                raise ValueError('FLIGHT_CHANGE_INPUT_INVALID')
            entries = deepcopy(changes)
        else:
            if leg_index is None:
                if len(legs) != 1:
                    raise ValueError('FLIGHT_CHANGE_SEGMENT_SELECTION_REQUIRED')
                leg_index = 0
            entries = [{'leg_index':leg_index,'new_departure_date':new_date}]
        if not isinstance(entries,list) or not 1 <= len(entries) <= len(legs):
            raise ValueError('FLIGHT_CHANGE_INPUT_INVALID')
        selected=set(); new=deepcopy(legs); lines=[]; difference=fee=0
        offer = s.get(Offer, s.get(Prebook, order.prebook_id).offer_id)
        for entry in entries:
            if not isinstance(entry,dict) or set(entry) != {'leg_index','new_departure_date'}:
                raise ValueError('FLIGHT_CHANGE_INPUT_INVALID')
            index=entry['leg_index']; value=entry['new_departure_date']
            if type(index) is not int or not 0<=index<len(legs) or index in selected:
                raise ValueError('FLIGHT_CHANGE_SEGMENT_INVALID')
            try: parsed=date.fromisoformat(value)
            except (ValueError,TypeError):raise ValueError('FLIGHT_CHANGE_DATE_INVALID')
            if parsed.isoformat()!=value or parsed<date.today() or value==legs[index]['departure_date']:
                raise ValueError('FLIGHT_CHANGE_DATE_INVALID')
            rules=legs[index].get('change_policy',offer.change_policy if len(legs)==1 else {})
            if rules.get('allowed') is not True:
                raise ValueError('FLIGHT_ORDER_NOT_CHANGEABLE:FARE_POLICY')
            leg_fee=rules.get('fee_minor',0)
            if type(leg_fee) is not int or leg_fee<0:raise ValueError('FLIGHT_CHANGE_FARE_INVALID')
            delta=30000*len(order.passengers)  # Explicit existing contract-simulator tariff.
            new[index].update(departure_date=value,flight_number='GO720')
            if 'total_amount_minor' in new[index]:new[index]['total_amount_minor']+=delta
            if 'unit_total_amount_minor' in new[index]:new[index]['unit_total_amount_minor']+=30000
            lines.append({**entry,'origin':legs[index]['origin'],'destination':legs[index]['destination'],
                'old_departure_date':legs[index]['departure_date'],'new_flight_number':'GO720',
                'fare_difference_minor':delta,'change_fee_minor':leg_fee})
            selected.add(index);difference+=delta;fee+=leg_fee
        if any(b['departure_date']<=a['departure_date'] for a,b in zip(new,new[1:])):
            raise ValueError('FLIGHT_CHANGE_ITINERARY_DATE_ORDER_INVALID')
        quote=Quote(quote_id=new_id('flt_chq'),order_id=order_id,new_departure_date=lines[0]['new_departure_date'],
            new_flight_number='GO720',fare_difference_minor=difference,change_fee_minor=fee,total_due_minor=difference+fee,
            currency=order.currency,status='QUOTED',expires_at=now()+timedelta(minutes=15),created_at=now())
        data={'order':order_facts(order),'quote':quote_facts(quote),'changes':lines,'new_itinerary':new}
        plan=Plan(quote_id=quote.quote_id,order_id=order_id,account_id=account,plan_json=data,plan_hash=digest(data),created_at=now())
        s.add_all([quote,plan]);s.flush()
        return public(quote,plan)


def consent(order, quote, plan, confirmation):
    if len(order.current_itinerary)==1 and confirmation is None:
        return  # Preserve the legacy single-leg quote-ID contract.
    expected={'quote_hash':plan.plan_hash,'expected_total_due_minor':quote.total_due_minor,
              'currency':quote.currency,'confirmed':True}
    if (not isinstance(confirmation,dict) or confirmation != expected
            or type(confirmation.get('confirmed')) is not bool
            or type(confirmation.get('expected_total_due_minor')) is not int):
        raise ValueError('FLIGHT_CHANGE_CONSENT_INVALID')
