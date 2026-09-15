"""Signed, current-order travel facts. ENGINEERING/SANDBOX only until live acceptance.

Public keys are registered by two administrators. No private key is generated or
stored here. Provider facts are immutable; reads never invent a check-in state.
"""
from contextlib import contextmanager
from datetime import date, datetime, timezone
import re
from urllib.parse import urlsplit
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy import select, text

from go_hotel.autonomy.durable import canonical, db_now_ms, digest, transaction
from go_hotel.core.config import settings
from go_hotel.db.models import (TravelFactAuthorityRow as Authority,
    TravelOperationalFactRow as Fact, FlightOrderRow)
from go_hotel.db.session import SessionLocal

CHECKIN_STATES = {'CHECK_IN_NOT_OPEN', 'CHECK_IN_OPEN', 'CHECKED_IN', 'BOARDING_PASS_AVAILABLE'}
KINDS = {'CHECK_IN', 'FLIGHT_ARRIVAL'}
ENVELOPE_KEYS = {'authority_id', 'provider_id', 'event_id', 'kind', 'source_sequence',
                 'observed_ms', 'expires_ms', 'subject', 'data'}


def identifier(value, code='IDENTITY_INVALID', maximum=128):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,'+str(maximum)+'}', value):
        raise ValueError(code)
    return value


def integer(value, low, high, code):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(code)
    return value


def instant(value):
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.utcoffset() is None:
            raise ValueError()
        return dt.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, AttributeError):
        raise ValueError('TIME_WITH_OFFSET_REQUIRED') from None


def environment_allowed(environment):
    # No authority registration can open the real-provider release gate.
    if settings.app_env.strip().lower() not in {'local', 'test', 'demo'} or environment not in {'ENGINEERING', 'SANDBOX'}:
        raise ValueError('TRAVEL_LIVE_PROVIDER_ACCEPTANCE_REQUIRED')


@contextmanager
def travel_transaction(factory=SessionLocal):
    with transaction(factory) as s:
        # Serialize travel writers across authority/key rotations too. The local
        # acceptance does not certify PostgreSQL throughput or distributed scale.
        if s.bind.dialect.name == 'postgresql':
            s.execute(text('SELECT pg_advisory_xact_lock(126019)'))
        yield s


def authority_hash(provider, environment, source, contract, public_key, start, end):
    return digest([provider, environment, source, contract, public_key, start, end])


def flight_identity(subject):
    if not isinstance(subject, dict) or set(subject) != {'carrier_code', 'flight_no', 'departure_date', 'arrival_airport'}:
        raise ValueError('EXACT_FLIGHT_IDENTITY_REQUIRED')
    carrier = str(subject['carrier_code']).strip().upper()
    flight = str(subject['flight_no']).replace(' ', '').upper()
    airport = str(subject['arrival_airport']).strip().upper()
    try:
        day = date.fromisoformat(subject['departure_date']).isoformat()
    except (ValueError, TypeError):
        raise ValueError('FLIGHT_DATE_INVALID') from None
    if not re.fullmatch('[A-Z0-9]{2,3}', carrier) or not re.fullmatch('[A-Z]{3}', airport):
        raise ValueError('FLIGHT_IDENTITY_INVALID')
    if not re.fullmatch(re.escape(carrier)+r'[0-9]{1,5}[A-Z]?', flight):
        raise ValueError('FLIGHT_NUMBER_CARRIER_MISMATCH')
    return {'carrier_code': carrier, 'flight_no': flight, 'departure_date': day, 'arrival_airport': airport}


def flight_from_leg(leg):
    carrier = str(leg.get('carrier_code', '')).upper()
    number = str(leg.get('flight_number', '')).upper()
    return flight_identity({'carrier_code': carrier,
        'flight_no': number if number.startswith(carrier) else carrier+number,
        'departure_date': leg.get('departure_date'), 'arrival_airport': leg.get('destination')})


def checkin_subject(order, leg_index, passenger_index):
    legs, people, tickets = order.current_itinerary or [], order.passengers or [], order.ticket_numbers or []
    if order.status != 'TICKETED' or not legs or not people or len(tickets) != len(legs)*len(people):
        raise ValueError('CURRENT_TICKET_ASSIGNMENT_REQUIRED')
    integer(leg_index, 0, len(legs)-1, 'FLIGHT_LEG_INVALID')
    integer(passenger_index, 0, len(people)-1, 'FLIGHT_PASSENGER_INVALID')
    leg = legs[leg_index]
    identity = flight_from_leg(leg)
    origin = leg.get('origin')
    if not isinstance(origin, str) or not re.fullmatch('[A-Z]{3}', origin):
        raise ValueError('FLIGHT_ORIGIN_INVALID')
    # Full current itinerary and current traveler record bind later amendments.
    return {'order_id': order.order_id, 'leg_index': leg_index, 'passenger_index': passenger_index,
        'ticket_number': tickets[leg_index*len(people)+passenger_index],
        'itinerary_hash': digest(legs), 'traveler_hash': digest(people[passenger_index])}, identity


class TravelFacts:
    def __init__(self, factory=SessionLocal):
        self.factory = factory

    def register(self, body, actor):
        identifier(actor, maximum=64)
        required = {'provider_id', 'environment', 'source_type', 'contract', 'public_key_hex', 'valid_from_ms', 'valid_until_ms'}
        if set(body) != required:
            raise ValueError('AUTHORITY_FIELDS_INVALID')
        provider = identifier(body['provider_id'], maximum=64)
        env, source, contract, key = body['environment'], body['source_type'], body['contract'], body['public_key_hex']
        environment_allowed(env)
        if source not in {'AIRLINE_OFFICIAL', 'AUTHORIZED_AIRLINE_PROVIDER'}:
            raise ValueError('AIRLINE_SOURCE_REQUIRED')
        if not isinstance(contract, dict) or set(contract) != {'reference', 'kinds', 'carriers', 'link_hosts', 'max_age_ms'}:
            raise ValueError('AUTHORITY_CONTRACT_INVALID')
        if not isinstance(contract['reference'], str) or not contract['reference'].strip() or len(contract['reference']) > 512:
            raise ValueError('AUTHORITY_REFERENCE_REQUIRED')
        if not isinstance(contract['kinds'], list) or not contract['kinds'] or any(not isinstance(k,str) for k in contract['kinds']) or not set(contract['kinds']) <= KINDS:
            raise ValueError('AUTHORITY_SCOPE_INVALID')
        if not isinstance(contract['carriers'], list) or not contract['carriers'] or any(not re.fullmatch('[A-Z0-9]{2,3}', str(x)) for x in contract['carriers']):
            raise ValueError('AUTHORITY_CARRIER_SCOPE_INVALID')
        hosts = contract['link_hosts']
        if not isinstance(hosts, list) or any(not isinstance(h, str) or not re.fullmatch(r'[a-z0-9]+(?:[.-][a-z0-9]+)*\.[a-z]{2,63}', h) for h in hosts):
            raise ValueError('AUTHORITY_LINK_HOST_INVALID')
        integer(contract['max_age_ms'], 1000, 86400000, 'FACT_MAX_AGE_INVALID')
        try:
            if not isinstance(key, str) or len(key) != 64:
                raise ValueError()
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(key))
        except (TypeError, ValueError):
            raise ValueError('ED25519_PUBLIC_KEY_INVALID') from None
        start = integer(body['valid_from_ms'], 0, 2**63-1, 'AUTHORITY_WINDOW_INVALID')
        end = integer(body['valid_until_ms'], start+1, 2**63-1, 'AUTHORITY_WINDOW_INVALID')
        with travel_transaction(self.factory) as s:
            now = db_now_ms(s)
            if end <= now:
                raise ValueError('AUTHORITY_EXPIRED')
            row = Authority(authority_id='tfa_'+uuid.uuid4().hex, provider_id=provider, environment=env,
                source_type=source, contract_json=contract,
                contract_hash=authority_hash(provider, env, source, contract, key, start, end),
                public_key_hex=key, status='DRAFT', created_by=actor, approved_by=None,
                valid_from_ms=start, valid_until_ms=end, created_ms=now, updated_ms=now, revision=1)
            s.add(row); s.flush()
            return self.authority_out(row)

    @staticmethod
    def authority_out(row):
        return {k:getattr(row, k) for k in ('authority_id', 'provider_id', 'environment', 'source_type',
            'status', 'revision', 'created_by', 'approved_by', 'valid_from_ms', 'valid_until_ms', 'contract_hash')}

    def review(self, authority_id, actor, revision, action):
        identifier(actor, maximum=64)
        with travel_transaction(self.factory) as s:
            row = s.get(Authority, authority_id)
            if not row or row.revision != revision:
                raise ValueError('AUTHORITY_REVISION_CONFLICT')
            self._integrity(row)
            if action == 'APPROVE':
                if row.status != 'DRAFT' or row.created_by == actor:
                    raise ValueError('INDEPENDENT_AUTHORITY_REVIEW_REQUIRED')
                if not row.valid_from_ms <= db_now_ms(s) < row.valid_until_ms:
                    raise ValueError('AUTHORITY_NOT_CURRENT')
                row.status, row.approved_by = 'ACTIVE', actor
            elif action == 'REVOKE':
                if row.status != 'ACTIVE':
                    raise ValueError('AUTHORITY_NOT_ACTIVE')
                row.status = 'REVOKED'
            else:
                raise ValueError('AUTHORITY_ACTION_INVALID')
            row.revision += 1; row.updated_ms = db_now_ms(s)
            return self.authority_out(row)

    @staticmethod
    def _integrity(a):
        environment_allowed(a.environment)
        if a.contract_hash != authority_hash(a.provider_id, a.environment, a.source_type,
                a.contract_json, a.public_key_hex, a.valid_from_ms, a.valid_until_ms):
            raise ValueError('AUTHORITY_INTEGRITY_FAILED')

    def authority(self, s, authority_id, kind, carrier):
        a = s.get(Authority, authority_id)
        if not a:
            raise ValueError('FACT_AUTHORITY_NOT_FOUND')
        self._integrity(a)
        now = db_now_ms(s)
        if a.status != 'ACTIVE' or not a.approved_by or a.approved_by == a.created_by or not a.valid_from_ms <= now < a.valid_until_ms:
            raise ValueError('FACT_AUTHORITY_NOT_CURRENT')
        if kind not in a.contract_json['kinds'] or carrier not in a.contract_json['carriers']:
            raise ValueError('FACT_AUTHORITY_SCOPE_MISMATCH')
        return a

    @staticmethod
    def _link(value, a):
        if value is None:
            return None
        try:
            u = urlsplit(value)
            if not isinstance(value, str) or len(value) > 2048 or any(ord(x) < 33 for x in value) or '\\' in value or u.scheme != 'https' or u.username or u.password or u.port not in {None, 443} or u.hostname not in a.contract_json['link_hosts']:
                raise ValueError()
        except (TypeError, ValueError, AttributeError):
            raise ValueError('OFFICIAL_LINK_NOT_AUTHORIZED') from None
        return value

    def validate(self, s, body, signature):
        if not isinstance(body, dict) or set(body) != ENVELOPE_KEYS or not isinstance(body['kind'],str) or body['kind'] not in KINDS:
            raise ValueError('SIGNED_FACT_ENVELOPE_REQUIRED')
        identifier(body['authority_id'], maximum=64); identifier(body['provider_id'], maximum=64)
        identifier(body['event_id'])
        integer(body['source_sequence'], 1, 2**63-1, 'FACT_SEQUENCE_INVALID')
        if not isinstance(body['subject'], dict) or not isinstance(body['data'], dict):
            raise ValueError('FACT_CONTENT_INVALID')
        if body['kind'] == 'CHECK_IN':
            subject = body['subject']
            identifier(subject.get('order_id'), 'FLIGHT_ORDER_ID_INVALID', maximum=64)
            order = s.get(FlightOrderRow, subject['order_id'])
            if not order:
                raise ValueError('FLIGHT_ORDER_NOT_FOUND')
            expected, identity = checkin_subject(order, subject.get('leg_index'), subject.get('passenger_index'))
            if subject != expected:
                raise ValueError('FACT_CURRENT_TICKET_MISMATCH')
        else:
            identity = flight_identity(body['subject'])
            if identity != body['subject']:
                raise ValueError('FACT_IDENTITY_NOT_CANONICAL')
        a = self.authority(s, body['authority_id'], body['kind'], identity['carrier_code'])
        if a.provider_id != body['provider_id']:
            raise ValueError('FACT_PROVIDER_MISMATCH')
        try:
            if not isinstance(signature, str) or len(signature) != 128:
                raise ValueError()
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(a.public_key_hex)).verify(bytes.fromhex(signature), canonical(body).encode())
        except (ValueError, TypeError, InvalidSignature):
            raise ValueError('FACT_SIGNATURE_INVALID') from None
        now = db_now_ms(s)
        observed = integer(body['observed_ms'], 0, 2**63-1, 'FACT_TIME_INVALID')
        expires = integer(body['expires_ms'], observed+1, 2**63-1, 'FACT_TIME_INVALID')
        if not a.valid_from_ms <= observed <= now or now-observed > a.contract_json['max_age_ms'] or expires <= now or expires > min(a.valid_until_ms, observed+a.contract_json['max_age_ms']):
            raise ValueError('FACT_NOT_CURRENT')
        data = body['data']
        if body['kind'] == 'CHECK_IN':
            if set(data) - {'state', 'check_in_opens_at', 'official_check_in_url', 'boarding_pass_reference'} or not isinstance(data.get('state'),str) or data.get('state') not in CHECKIN_STATES:
                raise ValueError('CHECK_IN_STATE_INVALID')
            self._link(data.get('official_check_in_url'), a)
            self._link(data.get('boarding_pass_reference'), a)
            if data.get('check_in_opens_at'):
                instant(data['check_in_opens_at'])
            if data['state'] == 'BOARDING_PASS_AVAILABLE' and not data.get('boarding_pass_reference'):
                raise ValueError('BOARDING_PASS_REFERENCE_REQUIRED')
            if data['state'] != 'BOARDING_PASS_AVAILABLE' and data.get('boarding_pass_reference'):
                raise ValueError('BOARDING_PASS_STATE_MISMATCH')
        else:
            if set(data) != {'event_type', 'verified_arrival_at'} or not isinstance(data['event_type'],str) or data['event_type'] not in {'DELAYED', 'EARLY', 'LANDED', 'CORRECTED'}:
                raise ValueError('FLIGHT_ARRIVAL_DATA_INVALID')
            arrival = instant(data['verified_arrival_at'])
            # Prevent identity-date accidents; international date-line crossings fit.
            if abs((date.fromisoformat(arrival[:10])-date.fromisoformat(identity['departure_date'])).days) > 3:
                raise ValueError('FLIGHT_ARRIVAL_DATE_MISMATCH')
        return a

    def ingest_in(self, s, envelope):
        if not isinstance(envelope, dict) or set(envelope) != {'fact', 'signature_hex'}:
            raise ValueError('SIGNED_FACT_ENVELOPE_REQUIRED')
        body, signature = envelope['fact'], envelope['signature_hex']
        a = self.validate(s, body, signature)
        hashed, stream = digest(body), digest([body['kind'], body['subject']])
        existing = s.scalar(select(Fact).where(Fact.provider_id == a.provider_id, Fact.event_id == body['event_id']))
        if existing:
            if existing.payload_hash != hashed or existing.signature_hex != signature:
                raise ValueError('FACT_EVENT_CONTENT_CONFLICT')
            return existing, False
        last = s.scalar(select(Fact).where(Fact.stream_key == stream).order_by(Fact.source_sequence.desc()).limit(1))
        if last and last.provider_id != a.provider_id:
            raise ValueError('FACT_PROVIDER_SWITCH_REVIEW_REQUIRED')
        if last and (body['source_sequence'] <= last.source_sequence or body['observed_ms'] < last.observed_ms):
            raise ValueError('FACT_OUT_OF_ORDER')
        row = Fact(fact_id='tf_'+uuid.uuid4().hex, authority_id=a.authority_id, provider_id=a.provider_id,
            event_id=body['event_id'], kind=body['kind'], stream_key=stream, order_id=body['subject'].get('order_id'),
            source_sequence=body['source_sequence'], payload_json=body, payload_hash=hashed, signature_hex=signature,
            observed_ms=body['observed_ms'], expires_ms=body['expires_ms'], created_ms=db_now_ms(s))
        s.add(row); s.flush()
        return row, True

    def current(self, s, row):
        if row.payload_hash != digest(row.payload_json):
            raise ValueError('FACT_INTEGRITY_FAILED')
        body = row.payload_json
        if (row.authority_id, row.provider_id, row.event_id, row.kind, row.stream_key, row.source_sequence, row.observed_ms, row.expires_ms) != (body['authority_id'], body['provider_id'], body['event_id'], body['kind'], digest([body['kind'], body['subject']]), body['source_sequence'], body['observed_ms'], body['expires_ms']):
            raise ValueError('FACT_INDEX_INTEGRITY_FAILED')
        self.validate(s, body, row.signature_hex)
        latest = s.scalar(select(Fact).where(Fact.stream_key == row.stream_key).order_by(Fact.source_sequence.desc()).limit(1))
        if not latest or latest.fact_id != row.fact_id:
            raise ValueError('FACT_SUPERSEDED')
        return body

    def ingest_checkin(self, order_id, envelope, actor):
        body = envelope.get('fact', {}) if isinstance(envelope,dict) else {}
        if not isinstance(body,dict) or body.get('kind') != 'CHECK_IN' or not isinstance(body.get('subject'),dict) or body['subject'].get('order_id') != order_id:
            raise ValueError('SIGNED_CHECK_IN_ORDER_REQUIRED')
        with travel_transaction(self.factory) as s:
            row, created = self.ingest_in(s, envelope)
            return {'fact_id': row.fact_id, 'created': created, 'state': row.payload_json['data']['state'], 'external_live': False}

    def checkin(self, account, order_id):
        with self.factory() as s:
            order = s.get(FlightOrderRow, order_id)
            if not order or order.account_id != account:
                raise ValueError('FLIGHT_ORDER_NOT_FOUND')
            cells = []
            for leg_i, leg in enumerate(order.current_itinerary or []):
                for person_i, person in enumerate(order.passengers or []):
                    cell = {'leg_index': leg_i, 'passenger_index': person_i, 'state': 'CHECK_IN_UNVERIFIED',
                        'official_check_in_url': None, 'boarding_pass_reference': None}
                    try:
                        subject, _ = checkin_subject(order, leg_i, person_i)
                        stream = digest(['CHECK_IN', subject])
                        row = s.scalar(select(Fact).where(Fact.stream_key == stream).order_by(Fact.source_sequence.desc()).limit(1))
                        if row:
                            body = self.current(s, row)
                            cell.update(body['data']); cell.update(fact_id=row.fact_id, observed_ms=row.observed_ms, expires_ms=row.expires_ms)
                    except ValueError:
                        pass  # No stale URL, pass, or inferred state is exposed.
                    cells.append(cell)
            states = {c['state'] for c in cells}
            return {'flight_order_id': order_id, 'state': next(iter(states)) if len(states) == 1 else 'MIXED' if states else 'CHECK_IN_UNVERIFIED',
                'items': cells, 'external_check_in_only': True, 'external_live': False,
                'data_mode': 'SIMULATION', 'go_does_not_fabricate_success': True}


travel_facts = TravelFacts()
