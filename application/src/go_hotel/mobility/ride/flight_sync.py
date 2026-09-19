"""Versioned flight tracking and durable fleet intents; confirmed times stay distinct.

Only the explicit isolated adapter is supplied in this build. UNKNOWN/DISPATCHED
intents can be queried, never resent. Real fleet credentials are not accepted here.
"""
from datetime import datetime, timezone
import uuid
from sqlalchemy import select

from go_hotel.autonomy.durable import db_now_ms, digest
from go_hotel.db.models import (MobilityRideOrderRow as Ride, RideServicePolicyRow as Policy,
    RideFlightBindingV2Row as Binding, RideFlightAdjustmentRow as Adjustment,
    TravelOperationalFactRow as Fact, TravelFactAuthorityRow as Authority)
from go_hotel.db.session import SessionLocal
from go_hotel.services.travel_operational_facts import (TravelFacts, travel_transaction,
    flight_identity, instant, environment_allowed)


# These are versioned server-side engineering offer terms, not real fleet terms.
def engineering_policy(offer_id):
    included = {'ride_standard': 60, 'ride_premium': 90}.get(offer_id)
    if included is None:
        raise ValueError('RIDE_OFFER_NOT_FOUND')
    return {'version': 'engineering-ride-19.1', 'offer_id': offer_id, 'data_mode': 'SIMULATION',
        'fleet_adapter': 'isolated-fleet-v1', 'included_wait_minutes': included,
        'delay_protection_free_wait_minutes': 30, 'max_free_wait_minutes': included+30,
        'arrival_to_pickup_minutes': 0, 'extra_fees_authorized': False, 'delay_protection_triggers': ['DELAYED']}


def reject_client_rules(body):
    if any(body.get(k) not in (None, 0, {}) for k in ('included_wait_minutes',
            'delay_protection_free_wait_minutes', 'max_free_wait_minutes', 'supplier_rule_snapshot')):
        raise ValueError('CLIENT_SUPPLIER_RULE_OVERRIDE_FORBIDDEN')


def snapshot_policy(s, ride, offer_id):
    policy = engineering_policy(offer_id)
    s.add(Policy(ride_order_id=ride.order_id, policy_json=policy, policy_hash=digest(policy), accepted_ms=db_now_ms(s)))
    s.flush()


def adjustment_out(a):
    return {k:getattr(a,k) for k in ('adjustment_id', 'ride_order_id', 'fact_id', 'binding_revision',
        'expected_pickup_at', 'proposed_pickup_at', 'free_wait_minutes', 'status', 'created_ms', 'updated_ms')}


class FlightRideSync:
    def __init__(self, factory=SessionLocal):
        self.factory, self.facts = factory, TravelFacts(factory)

    @staticmethod
    def policy(s, ride_id):
        p = s.get(Policy, ride_id)
        if not p or p.policy_hash != digest(p.policy_json):
            raise ValueError('SERVER_RIDE_POLICY_REQUIRED')
        if p.policy_json != engineering_policy(p.policy_json.get('offer_id')):
            raise ValueError('RIDE_POLICY_VERSION_NOT_SUPPORTED')
        return p

    @staticmethod
    def owned(s, account, ride_id):
        ride = s.scalar(select(Ride).where(Ride.order_id == ride_id).with_for_update())
        if not ride or ride.account_id != account:
            raise ValueError('MOBILITY_ORDER_NOT_FOUND')
        return ride

    def bind_in(self, s, account, ride_id, body, *, creating=False):
        reject_client_rules(body)
        ride = self.owned(s, account, ride_id)
        if ride.status not in ({'PAYMENT_PENDING'} if creating else {'CONFIRMED'}):
            raise ValueError('RIDE_TRACKING_ORDER_NOT_ACTIVE')
        p = self.policy(s, ride_id)
        old = s.get(Binding, ride_id)
        expected = body.get('expected_revision', 0)
        if type(expected) is not int or expected != (old.revision if old else 0):
            raise ValueError('RIDE_TRACKING_REVISION_CONFLICT')
        enabled = body.get('tracking_enabled', True)
        protection = body.get('delay_protection_enabled', False)
        if type(enabled) is not bool or type(protection) is not bool:
            raise ValueError('RIDE_TRACKING_OPTION_INVALID')
        if not enabled:
            if not old:
                raise ValueError('RIDE_TRACKING_NOT_BOUND')
            old.tracking_enabled = False; old.revision += 1; old.updated_ms = db_now_ms(s)
            return self.binding_out(old, p)
        identity = flight_identity(body.get('flight_identity'))
        # Linking is explicit consumer consent; the date/airport cannot be inferred
        # from a free-text pickup label. Flight identity remains visible for review.
        authority_id = body.get('authority_id')
        self.facts.authority(s, authority_id, 'FLIGHT_ARRIVAL', identity['carrier_code'])
        # Legacy local pickup values remain opaque comparison tokens. Do not
        # guess their timezone or rewrite them while merely enabling tracking.
        try:
            if len(ride.pickup_at)<16:raise ValueError()
            pickup_day=datetime.fromisoformat(ride.pickup_at.replace('Z','+00:00')).date()
        except (TypeError,ValueError,AttributeError):
            raise ValueError('RIDE_PICKUP_TIME_INVALID') from None
        if abs((pickup_day-datetime.fromisoformat(identity['departure_date']).date()).days) > 3:
            raise ValueError('RIDE_FLIGHT_DATE_MISMATCH')
        values = dict(account_id=account, flight_key=digest(['FLIGHT_ARRIVAL', identity]), identity_json=identity,
            authority_id=authority_id, policy_hash=p.policy_hash, tracking_enabled=enabled,
            delay_protection_enabled=protection, current_pickup_at=ride.pickup_at,
            revision=expected+1, last_fact_id=None, updated_ms=db_now_ms(s))
        if old:
            for key, value in values.items(): setattr(old, key, value)
        else:
            old = Binding(ride_order_id=ride_id, original_pickup_at=ride.pickup_at, **values); s.add(old)
        ride.flight_no = identity['flight_no']
        s.flush()
        return self.binding_out(old, p)

    def bind(self, account, ride_id, body):
        with travel_transaction(self.factory) as s:
            return self.bind_in(s, account, ride_id, body)

    @staticmethod
    def binding_out(b, p):
        policy = p.policy_json
        free = min(policy['max_free_wait_minutes'], policy['included_wait_minutes']+
            (policy['delay_protection_free_wait_minutes'] if b.delay_protection_enabled else 0))
        return {'ride_order_id': b.ride_order_id, 'flight_identity': b.identity_json,
            'authority_id': b.authority_id, 'tracking_enabled': b.tracking_enabled,
            'delay_protection_enabled': b.delay_protection_enabled, 'revision': b.revision,
            'original_pickup_at': b.original_pickup_at, 'confirmed_pickup_at': b.current_pickup_at,
            'included_wait_minutes': policy['included_wait_minutes'], 'delay_protection_max_wait_minutes': free, 'policy': policy}

    @staticmethod
    def free_for_fact(binding, policy, fact):
        rules=policy.policy_json
        eligible=binding.delay_protection_enabled and fact.payload_json['data']['event_type'] in rules['delay_protection_triggers']
        return min(rules['max_free_wait_minutes'], rules['included_wait_minutes']+(rules['delay_protection_free_wait_minutes'] if eligible else 0))

    @staticmethod
    def request(ride, a, policy):
        return {'adjustment_id': a.adjustment_id, 'ride_order_id': ride.order_id,
            'supplier_reference': ride.supplier_reference, 'fact_id': a.fact_id,
            'binding_revision': a.binding_revision, 'policy_hash': a.policy_hash,
            'expected_pickup_at': a.expected_pickup_at, 'proposed_pickup_at': a.proposed_pickup_at,
            'free_wait_minutes': a.free_wait_minutes, 'fleet_adapter': policy['fleet_adapter']}

    def ingest(self, envelope, actor):
        body=envelope.get('fact') if isinstance(envelope,dict) else None
        if not isinstance(body,dict) or body.get('kind') != 'FLIGHT_ARRIVAL':
            raise ValueError('SIGNED_FLIGHT_ARRIVAL_REQUIRED')
        with travel_transaction(self.factory) as s:
            fact, created = self.facts.ingest_in(s, envelope)
            if not created:
                existing = s.scalars(select(Adjustment).where(Adjustment.fact_id == fact.fact_id)).all()
                return {'fact_id': fact.fact_id, 'events': [adjustment_out(x) for x in existing], 'matched_rides': len(existing), 'external_live': False, 'duplicate': True}
            bindings = s.scalars(select(Binding).where(Binding.flight_key == fact.stream_key,
                Binding.authority_id == fact.authority_id, Binding.tracking_enabled.is_(True))).all()
            events = []
            for b in bindings:
                ride = s.scalar(select(Ride).where(Ride.order_id == b.ride_order_id).with_for_update())
                if not ride or ride.status != 'CONFIRMED' or ride.account_id != b.account_id:
                    continue
                try:
                    p = self.policy(s, ride.order_id)
                    if b.policy_hash != p.policy_hash: continue
                except ValueError:
                    continue
                proposed = instant(fact.payload_json['data']['verified_arrival_at'])
                free = self.free_for_fact(b,p,fact)
                # Current engineering policy has a zero pickup offset. Do not
                # silently apply a future policy until that version is supported.
                a = Adjustment(adjustment_id='rfa_'+uuid.uuid4().hex, ride_order_id=ride.order_id,
                    fact_id=fact.fact_id, binding_revision=b.revision, policy_hash=p.policy_hash,
                    expected_pickup_at=ride.pickup_at, proposed_pickup_at=proposed,
                    free_wait_minutes=free, status='PENDING', request_hash='',
                    provider_reference=None, result_json=None, created_ms=db_now_ms(s), updated_ms=db_now_ms(s))
                a.request_hash = digest(self.request(ride, a, p.policy_json))
                s.add(a); b.last_fact_id = fact.fact_id; b.updated_ms = db_now_ms(s)
                events.append(adjustment_out(a))
            s.flush()
            return {'fact_id': fact.fact_id, 'events': events, 'matched_rides': len(events), 'external_live': False, 'duplicate': False}

    def _current(self, s, ride, a):
        if not ride or ride.status != 'CONFIRMED' or not ride.supplier_reference:
            raise ValueError('RIDE_NOT_CONFIRMED')
        b = s.get(Binding, ride.order_id)
        if not b or b.account_id != ride.account_id or not b.tracking_enabled or b.revision != a.binding_revision:
            raise ValueError('RIDE_BINDING_CHANGED')
        p = self.policy(s, ride.order_id)
        fact = s.get(Fact, a.fact_id)
        if not fact or b.authority_id != fact.authority_id or b.flight_key != fact.stream_key or b.last_fact_id != fact.fact_id:
            raise ValueError('RIDE_FLIGHT_FACT_CHANGED')
        self.facts.current(s, fact)
        if p.policy_hash != a.policy_hash or b.policy_hash != p.policy_hash or ride.pickup_at != a.expected_pickup_at:
            raise ValueError('RIDE_CURRENT_TERMS_CHANGED')
        request = self.request(ride, a, p.policy_json)
        if digest(request) != a.request_hash or instant(fact.payload_json['data']['verified_arrival_at']) != a.proposed_pickup_at or self.free_for_fact(b,p,fact) != a.free_wait_minutes:
            raise ValueError('RIDE_INTENT_INTEGRITY_FAILED')
        return b, request

    def process(self, adjustment_id, adapter):
        environment_allowed('ENGINEERING')
        if getattr(adapter, 'adapter_id', None) != 'isolated-fleet-v1' or getattr(adapter, 'external_live', True) is not False:
            raise ValueError('ACCEPTED_FLEET_ADAPTER_REQUIRED')
        with travel_transaction(self.factory) as s:
            a = s.get(Adjustment, adjustment_id)
            if not a:
                raise ValueError('RIDE_ADJUSTMENT_NOT_FOUND')
            ride = s.scalar(select(Ride).where(Ride.order_id == a.ride_order_id).with_for_update())
            # Another worker may have dispatched while this transaction waited
            # for the ride lock. Refresh the earlier ORM snapshot under lock
            # before deciding whether execute or query is permitted. Keep the
            # same ride -> adjustment lock order in the receipt transaction.
            s.refresh(a, with_for_update=True)
            if a.status not in {'PENDING', 'DISPATCHED', 'UNKNOWN'}:
                return adjustment_out(a)
            sending = a.status == 'PENDING'
            if sending:
                try:
                    _, request = self._current(s, ride, a)
                except ValueError as e:
                    a.status, a.result_json, a.updated_ms = 'SUPERSEDED', {'code': str(e), 'external_dispatch': False}, db_now_ms(s)
                    return adjustment_out(a)
                other = s.scalar(select(Adjustment).where(Adjustment.ride_order_id == a.ride_order_id,
                    Adjustment.adjustment_id != a.adjustment_id, Adjustment.status.in_(['DISPATCHED', 'UNKNOWN', 'HOLD'])).limit(1))
                if other:
                    return adjustment_out(a) | {'blocked_by': other.adjustment_id}
                a.status = 'DISPATCHED'; a.updated_ms = db_now_ms(s)
            else:
                request = None  # Queries need the stable intent identity/hash only.
            request_hash = a.request_hash
        # This boundary intentionally persists dispatch before any external call.
        # A crash immediately here also resumes as query-only, never blind resend.
        try:
            result = adapter.execute(request, request_hash) if sending else adapter.query(adjustment_id, request_hash)
        except Exception:
            result = {'status': 'UNKNOWN', 'request_hash': request_hash}
        with travel_transaction(self.factory) as s:
            a = s.get(Adjustment, adjustment_id)
            ride = s.scalar(select(Ride).where(Ride.order_id == a.ride_order_id).with_for_update())
            s.refresh(a, with_for_update=True)
            if a.status not in {'DISPATCHED', 'UNKNOWN'}:
                return adjustment_out(a)
            if not isinstance(result, dict) or result.get('request_hash') != a.request_hash:
                a.status = 'UNKNOWN'; a.result_json = {'code': 'FLEET_RECEIPT_MISMATCH'}
            elif result.get('status') in {'CONFIRMED', 'REJECTED'} and isinstance(result.get('provider_reference'), str) and result['provider_reference']:
                a.provider_reference = result['provider_reference'][:256]
                a.result_json = {k:result.get(k) for k in ('status', 'request_hash', 'provider_reference', 'pickup_at')}
                if result['status'] == 'REJECTED':
                    a.status = 'REJECTED'
                else:
                    try:
                        b, _ = self._current(s, ride, a)
                        if instant(result.get('pickup_at')) != a.proposed_pickup_at:
                            raise ValueError('FLEET_CONFIRMED_TIME_MISMATCH')
                        ride.pickup_at = a.proposed_pickup_at; ride.updated_at = datetime.now(timezone.utc)
                        b.current_pickup_at = a.proposed_pickup_at; b.updated_ms = db_now_ms(s)
                        a.status = 'CONFIRMED'
                    except ValueError as e:
                        a.status = 'HOLD'; a.result_json = {**a.result_json, 'code': str(e), 'manual_reconciliation_required': True}
            else:
                a.status = 'UNKNOWN'; a.result_json = {'code': 'FLEET_OUTCOME_UNKNOWN'}
            a.updated_ms = db_now_ms(s)
            return adjustment_out(a)

    def pending(self, limit=100):
        with self.factory() as s:
            return list(s.scalars(select(Adjustment.adjustment_id).where(Adjustment.status.in_(['PENDING', 'DISPATCHED', 'UNKNOWN']))
                .order_by(Adjustment.created_ms, Adjustment.adjustment_id).limit(max(1, min(int(limit), 1000)))))

    def options(self, account, ride_id):
        with self.factory() as s:
            ride=s.get(Ride,ride_id)
            if not ride or ride.account_id!=account:raise ValueError('MOBILITY_ORDER_NOT_FOUND')
            try:p=self.policy(s,ride_id)
            except ValueError:return {'sources':[], 'policy':None, 'available':False}
            sources=[]
            for a in s.scalars(select(Authority).where(Authority.status=='ACTIVE').order_by(Authority.provider_id,Authority.authority_id)):
                try:
                    carriers=[c for c in a.contract_json['carriers'] if self.facts.authority(s,a.authority_id,'FLIGHT_ARRIVAL',c)]
                    sources.append({'authority_id':a.authority_id,'provider_id':a.provider_id,'carriers':carriers,
                        'label':'航空公司官方来源' if a.source_type=='AIRLINE_OFFICIAL' else '已授权航班服务'})
                except ValueError:continue
            return {'sources':sources,'policy':p.policy_json,'available':ride.status=='CONFIRMED' and bool(sources),'data_mode':'SIMULATION'}

    def operations(self):
        with self.factory() as s:
            rows=s.scalars(select(Adjustment).where(Adjustment.status.in_(['PENDING','DISPATCHED','UNKNOWN','HOLD']))
                .order_by(Adjustment.created_ms).limit(1000)).all()
            return {'items':[adjustment_out(a)|{'result':a.result_json} for a in rows],
                'manual_reconciliation_required':sum(a.status=='HOLD' for a in rows),'external_live':False}

    def tracking(self, account, ride_id):
        with self.factory() as s:
            ride = s.get(Ride, ride_id)
            if not ride or ride.account_id != account:
                raise ValueError('MOBILITY_ORDER_NOT_FOUND')
            b, p = s.get(Binding, ride_id), s.get(Policy, ride_id)
            binding = None
            if b and p:
                try:
                    p = self.policy(s, ride_id)
                    binding = self.binding_out(b, p)
                    binding['confirmed_pickup_at'] = ride.pickup_at
                    try:
                        self.facts.authority(s,b.authority_id,'FLIGHT_ARRIVAL',b.identity_json['carrier_code'])
                        binding['source_current']=True
                    except ValueError:
                        binding['source_current']=False
                except ValueError:
                    pass
            events = s.scalars(select(Adjustment).where(Adjustment.ride_order_id == ride_id).order_by(Adjustment.created_ms, Adjustment.adjustment_id)).all()
            return {'order_id': ride_id, 'binding': binding, 'confirmed_pickup_at': ride.pickup_at, 'events': [adjustment_out(x) for x in events],
                'legacy_binding_verified': False, 'data_mode': 'SIMULATION', 'external_live': False}


flight_ride_sync = FlightRideSync()
