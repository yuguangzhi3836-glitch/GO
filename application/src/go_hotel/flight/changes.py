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
    if require_current and 'coupons' in plan.plan_json:
        from .coupons import ledger, snapshot
        if plan.plan_json['coupons'] != [snapshot(c) for c in ledger(s,order)]:
            raise ValueError('FLIGHT_CHANGE_COUPONS_CHANGED_REQUOTE_REQUIRED')
    if require_current and plan.plan_json['order'] != order_facts(order):
        raise ValueError('FLIGHT_CHANGE_ORDER_CHANGED_REQUOTE_REQUIRED')
    return plan


def public(quote, plan):
    data = deepcopy(plan.plan_json)
    entries = data['changes']
    return {**quote_facts(quote), 'status':quote.status, 'quote_hash':plan.plan_hash,
            'changes':entries, 'leg_index':entries[0]['leg_index'] if len(entries)==1 else None,
            'partial_party':data.get('partial_party',False),'coupon_changes':data.get('coupon_changes',[]),
            'new_itinerary':data['new_itinerary'], 'passenger_count':len(data['order']['passengers']),
            'expires_at':quote.expires_at.isoformat(), 'data_mode':'SIMULATION', 'external_live':False}


def _legacy_create_quote(account, order_id, new_date=None, leg_index=None, changes=None):
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
    if len(order.current_itinerary)==1 and confirmation is None and not plan.plan_json.get('partial_party'):
        return  # Preserve the legacy single-leg quote-ID contract.
    expected={'quote_hash':plan.plan_hash,'expected_total_due_minor':quote.total_due_minor,
              'currency':quote.currency,'confirmed':True}
    if (not isinstance(confirmation,dict) or confirmation != expected
            or type(confirmation.get('confirmed')) is not bool
            or type(confirmation.get('expected_total_due_minor')) is not int):
        raise ValueError('FLIGHT_CHANGE_CONSENT_INVALID')


def create_quote(account, order_id, new_date=None, leg_index=None, changes=None):
    from . import coupons
    production_truth_required('FLIGHT','CHANGE_QUOTE')
    with SessionLocal() as s:
        order=s.get(Order,order_id)
        if not order or order.account_id!=account:raise ValueError('FLIGHT_ORDER_NOT_CHANGEABLE')
        legacy=not coupons.rows(s,order)
    if legacy:
        return _legacy_create_quote(account,order_id,new_date,leg_index,changes)
    with transaction(SessionLocal) as s:
        order=s.get(Order,order_id,with_for_update=True)
        if not order or order.account_id!=account or order.status!='TICKETED':raise ValueError('FLIGHT_ORDER_NOT_CHANGEABLE')
        items=coupons.ledger(s,order);legs=order.current_itinerary;party=len(order.passengers)
        if changes is not None:
            if new_date is not None or leg_index is not None:raise ValueError('FLIGHT_CHANGE_INPUT_INVALID')
            entries=deepcopy(changes)
        else:
            if leg_index is None:
                if len(legs)!=1:raise ValueError('FLIGHT_CHANGE_SEGMENT_SELECTION_REQUIRED')
                leg_index=0
            entries=[{'leg_index':leg_index,'new_departure_date':new_date}]
        if not isinstance(entries,list) or not 1<=len(entries)<=len(items):raise ValueError('FLIGHT_CHANGE_INPUT_INVALID')
        seen=set();lines=[];updates=[]
        for entry in entries:
            if (not isinstance(entry,dict) or not {'leg_index','new_departure_date'}<=set(entry)
                    or set(entry)-{'leg_index','new_departure_date','coupon_ids'}):raise ValueError('FLIGHT_CHANGE_INPUT_INVALID')
            li,value=entry['leg_index'],entry['new_departure_date']
            if type(li) is not int or not 0<=li<len(legs):raise ValueError('FLIGHT_CHANGE_SEGMENT_INVALID')
            try:parsed=date.fromisoformat(value)
            except (ValueError,TypeError):raise ValueError('FLIGHT_CHANGE_DATE_INVALID') from None
            if parsed.isoformat()!=value or parsed<date.today():raise ValueError('FLIGHT_CHANGE_DATE_INVALID')
            ids=entry.get('coupon_ids')
            if ids is None:ids=[c.coupon_id for c in items if c.leg_index==li and c.state=='ISSUED']
            selected=coupons.selected(items,ids,leg_index=li)
            if seen.intersection(ids):raise ValueError('FLIGHT_CHANGE_SEGMENT_INVALID')
            fee=0
            for c in selected:
                if value==c.leg_json['departure_date']:raise ValueError('FLIGHT_CHANGE_DATE_INVALID')
                if c.change_policy.get('allowed') is not True:raise ValueError('FLIGHT_ORDER_NOT_CHANGEABLE:FARE_POLICY')
                unit_fee=c.change_policy.get('fee_minor')
                if type(unit_fee) is not int or unit_fee<0:raise ValueError('FLIGHT_CHANGE_FARE_INVALID')
                new_leg=deepcopy(c.leg_json);new_leg.update(departure_date=value,flight_number='GO720')
                if 'unit_total_amount_minor' in new_leg:new_leg['unit_total_amount_minor']+=30000
                updates.append({'coupon_id':c.coupon_id,'leg_index':li,'passenger_index':c.passenger_index,
                    'old_ticket_number':c.ticket_number,'new_leg':new_leg,'fare_difference_minor':30000,
                    'change_fee_minor':unit_fee,'new_paid_amount_minor':c.paid_amount_minor+30000+unit_fee})
                fee+=unit_fee
            lines.append({'leg_index':li,'coupon_ids':[c.coupon_id for c in selected],
                'passenger_indices':[c.passenger_index for c in selected],
                'origin':legs[li]['origin'],'destination':legs[li]['destination'],
                'old_departure_date':selected[0].leg_json['departure_date'],'new_departure_date':value,
                'new_flight_number':'GO720','fare_difference_minor':30000*len(selected),'change_fee_minor':fee})
            seen.update(ids)
        updates.sort(key=lambda c:(c['leg_index'],c['passenger_index']))
        by_id={u['coupon_id']:u for u in updates}
        for pi in range(party):
            dates=[by_id[c.coupon_id]['new_leg']['departure_date'] if c.coupon_id in by_id else c.leg_json['departure_date']
                for c in items if c.passenger_index==pi and c.state=='ISSUED']
            if any(b<=a for a,b in zip(dates,dates[1:])):raise ValueError('FLIGHT_CHANGE_ITINERARY_DATE_ORDER_INVALID')
        new=deepcopy(legs)
        for li in {u['leg_index'] for u in updates}:
            active=[c for c in items if c.leg_index==li and c.state=='ISSUED']
            facts=[by_id[c.coupon_id]['new_leg'] if c.coupon_id in by_id else c.leg_json for c in active]
            same=len({(v['departure_date'],v['flight_number']) for v in facts})==1
            if same:new[li].update(departure_date=facts[0]['departure_date'],flight_number=facts[0]['flight_number'])
            new[li]['split_party']=not same
            delta=sum(u['fare_difference_minor'] for u in updates if u['leg_index']==li)
            if 'total_amount_minor' in new[li]:new[li]['total_amount_minor']+=delta
            if same and len(active)==party and all(c.coupon_id in by_id for c in active) and 'unit_total_amount_minor' in new[li]:
                new[li]['unit_total_amount_minor']+=30000
        difference=sum(u['fare_difference_minor'] for u in updates);fee=sum(u['change_fee_minor'] for u in updates)
        quote=Quote(quote_id=new_id('flt_chq'),order_id=order_id,new_departure_date=lines[0]['new_departure_date'],
            new_flight_number='GO720',fare_difference_minor=difference,change_fee_minor=fee,total_due_minor=difference+fee,
            currency=order.currency,status='QUOTED',expires_at=now()+timedelta(minutes=15),created_at=now())
        data={'order':order_facts(order),'coupons':[coupons.snapshot(c) for c in items],
            'quote':quote_facts(quote),'changes':lines,'coupon_changes':updates,'new_itinerary':new,
            'partial_party':any(len(line['coupon_ids'])<party for line in lines)}
        plan=Plan(quote_id=quote.quote_id,order_id=order_id,account_id=account,plan_json=data,plan_hash=digest(data),created_at=now())
        s.add_all([quote,plan]);s.flush();return public(quote,plan)
