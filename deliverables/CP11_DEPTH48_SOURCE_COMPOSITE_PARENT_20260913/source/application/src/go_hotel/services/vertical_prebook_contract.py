"""Immutable quoted terms and single-order consumption. No provider inventory hold is implied."""
import json
from sqlalchemy import select
from go_hotel.autonomy.durable import canonical, db_now_ms, digest
from go_hotel.db.models import VerticalPrebookContractRow as Row


def party_count(value, maximum=9):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError('BOOKING_PARTY_COUNT_INVALID')
    return value


def named_party(people, quantity, *, adults_only=False, maximum=9):
    party_count(quantity,maximum)
    if not isinstance(people,list) or len(people)!=quantity:
        raise ValueError('BOOKING_QUOTED_PARTY_COUNT_MISMATCH')
    result=[]
    for person in people:
        if not isinstance(person,dict):raise ValueError('BOOKING_TRAVELER_INVALID')
        name=person.get('full_name') or person.get('name')
        if not isinstance(name,str) or not name.strip() or len(name.strip())>128 or name.strip().casefold() in {'go traveler','traveler'}:
            raise ValueError('BOOKING_CONFIRMED_TRAVELER_NAME_REQUIRED')
        if adults_only and person.get('type','ADT')!='ADT':
            raise ValueError('BOOKING_CHILD_FARE_NOT_IN_ADULT_QUOTE')
        result.append({**person,'full_name':name.strip()})
    # Real people can share a name. Distinct vault IDs are checked by release_booking_data.
    return result

def party_refs(refs, quantity):
    if refs is None or refs==[]:return []
    if not isinstance(refs,list) or len(refs)!=quantity or any(not isinstance(x,str) or not x.strip() for x in refs) or len(set(refs))!=quantity:
        raise ValueError('BOOKING_TRAVELER_REFERENCE_COUNT_INVALID')
    return list(refs)

def rail_tickets(tickets, quantity):
    if not isinstance(tickets,list) or len(tickets)!=quantity or any(not isinstance(x,str) or not x.strip() or len(x)>128 or x!=x.strip() for x in tickets) or len(set(tickets))!=quantity:
        raise ValueError('RAIL_TICKET_PARTY_COUNT_OR_IDENTITY_INVALID')
    return list(tickets)


def _identity(row):
    return {'prebook_id':row.prebook_id,'vertical':row.vertical,'issued_account_id':row.issued_account_id,
        'terms':row.terms_json,'expires_ms':row.expires_ms}


def issue_in(s, vertical, prebook_id, terms, *, lifetime_ms=600000, account=None):
    if vertical not in {'RAIL','ATTRACTION'} or not isinstance(terms,dict):
        raise ValueError('PREBOOK_CONTRACT_INVALID')
    quantity=party_count(terms.get('quantity'),9 if vertical=='RAIL' else 100)
    unit=terms.get('unit_amount_minor');total=terms.get('total_amount_minor')
    if type(unit) is not int or unit<=0 or type(total) is not int or total!=unit*quantity or terms.get('currency')!='CNY':
        raise ValueError('PREBOOK_PRICE_CONTRACT_INVALID')
    if type(lifetime_ms) is not int or not 1000<=lifetime_ms<=900000:
        raise ValueError('PREBOOK_VALIDITY_INVALID')
    now=db_now_ms(s)
    row=Row(prebook_id=prebook_id,vertical=vertical,issued_account_id=account,owner_id=None,order_id=None,
        state='QUOTED',terms_json=json.loads(canonical(terms)),terms_hash='',consumed_hash=None,
        expires_ms=now+lifetime_ms,created_ms=now,consumed_ms=None)
    row.terms_hash=digest(_identity(row));s.add(row);s.flush()
    return row


def current_in(s, vertical, prebook_id, account, request):
    """Caller uses a writer transaction; returns existing claimed result only for exact owner/body."""
    row=s.scalar(select(Row).where(Row.prebook_id==prebook_id).with_for_update())
    if not row or row.vertical!=vertical or row.issued_account_id not in {None,account}:
        raise ValueError('PREBOOK_CONTRACT_NOT_FOUND')
    if digest(_identity(row))!=row.terms_hash:
        raise ValueError('PREBOOK_CONTRACT_INTEGRITY_FAILED')
    bound=digest({'account':account,'prebook_id':prebook_id,'request':request})
    if row.state=='CONSUMED':
        if row.owner_id!=account or row.consumed_hash!=bound or not row.order_id:
            raise ValueError('PREBOOK_CONSUMPTION_CONFLICT')
        return row,True
    if row.expires_ms<=db_now_ms(s):raise ValueError('PREBOOK_CONTRACT_EXPIRED')
    if row.owner_id or row.order_id or row.consumed_hash:
        raise ValueError('PREBOOK_CONTRACT_STATE_INVALID')
    return row,False


def consume_in(s, row, account, order_id, request):
    if row.state!='QUOTED' or row.expires_ms<=db_now_ms(s):
        raise ValueError('PREBOOK_CONTRACT_NOT_CONSUMABLE')
    row.owner_id=account;row.order_id=order_id;row.state='CONSUMED'
    row.consumed_hash=digest({'account':account,'prebook_id':row.prebook_id,'request':request})
    row.consumed_ms=db_now_ms(s);s.flush()


def projection(row):
    return {**row.terms_json,'prebook_id':row.prebook_id,'terms_hash':row.terms_hash,
        'expires_ms':row.expires_ms,'data_mode':'SIMULATION','external_live':False,
        'provider_inventory_reserved':False}
