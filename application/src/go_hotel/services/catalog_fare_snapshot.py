"""Supplier-published catalog rules, immutable quoted terms and order acceptance."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from go_hotel.core.config import settings
from go_hotel.db.models import (
    CatalogFareFamilyRow as Family, CatalogFareRuleVersionRow as Version,
    CatalogOfferFareSnapshotRow as OfferSnapshot, CatalogOrderFareSnapshotRow as OrderSnapshot,
    OfferRow, OrderRow, PrebookRow,
)
from go_hotel.db.session import SessionLocal
from go_hotel.services.alipay_safeguarded_settlement import transaction
from go_hotel.services.hosted_direct_booking import ident, now
from go_hotel.services.hosted_fare_rules import validated as validate_structure
from go_hotel.services.hosted_reservation_operations import aware
from go_hotel.services.omnichannel_payment import digest
from go_hotel.services import hotel_change_policy
from go_hotel.services import hotel_cancellation_clock as cancellation_clock


def identity(offer):
    return {'property_id': offer.hotel_id, 'supplier_id': offer.supplier_id,
        'connector_id': offer.connector_id, 'fare_rule_id': offer.fare_rule_id, 'currency': offer.currency}


def family_id(offer):
    return digest(identity(offer))


def offer_facts(offer):
    return {**identity(offer), 'offer_id': offer.offer_id, 'room_type_id': offer.room_type_id,
        'rate_plan_id': offer.rate_plan_id, 'check_in': offer.check_in, 'check_out': offer.check_out,
        'amount_minor': offer.total_amount_minor, 'currency': offer.currency,
        'offer_expires_at': aware(offer.expires_at).isoformat()}


def validate_rules(body):
    if not isinstance(body, dict):
        raise ValueError('COMPLETE_STRUCTURED_FARE_RULE_REQUIRED')
    body = deepcopy(body)
    retained = body.pop('credit_retained_value_basis', None)
    cash_basis = body.pop('cash_cancellation_value_basis', None)
    if cash_basis is not None and cash_basis != 'NET_CASH_LESS_FORFEITED_CHANGE_VALUE_INCLUDING_PAID_CHANGE_FEES':
        raise ValueError('VALID_CASH_CANCELLATION_VALUE_POLICY_REQUIRED')
    if retained != 'NET_CONFIRMED_CASH_INCLUDING_PAID_CHANGE_FEES':
        raise ValueError('EXPLICIT_CREDIT_RETAINED_VALUE_POLICY_REQUIRED')
    result = {**validate_structure(body), 'credit_retained_value_basis': retained}
    if cash_basis is not None: result['cash_cancellation_value_basis'] = cash_basis
    return result


def version_checked(s, version_id):
    v = s.get(Version, version_id)
    if not v or digest(v.contract_json) != v.contract_hash:
        raise ValueError('CATALOG_FARE_VERSION_INTEGRITY_REQUIRED')
    f = s.get(Family, v.family_id)
    b = v.contract_json
    if not f or v.version != b['version'] or any(getattr(f, key) != b[key] for key in ['property_id', 'supplier_id', 'connector_id', 'fare_rule_id', 'currency']):
        raise ValueError('CATALOG_FARE_SOURCE_IDENTITY_MISMATCH')
    return v


def publish(offer_id, rules, authority_reference, actor, supplier_id, expected_version_id=None):
    rules = validate_rules(rules)
    hotel_change_policy.require_zero_fee(rules)
    if not isinstance(authority_reference, str) or not 1 <= len(authority_reference.strip()) <= 512:
        raise ValueError('HOTEL_RULE_AUTHORITY_REFERENCE_REQUIRED')
    with transaction() as s:
        offer = s.get(OfferRow, offer_id, with_for_update=True)
        if not offer or offer.supplier_id != supplier_id:
            raise ValueError('OWN_SUPPLIER_OFFER_REQUIRED')
        fid = family_id(offer)
        family = s.get(Family, fid, with_for_update=True)
        if not family:
            family = Family(family_id=fid, **identity(offer), version=0)
            s.add(family)
            s.flush()
        old = version_checked(s, family.current_version_id) if family.current_version_id else None
        if old and old.contract_json['rules'] == rules and old.contract_json['authority_reference'] == authority_reference.strip():
            return public_version(old)
        if family.current_version_id != expected_version_id:
            raise ValueError('CATALOG_FARE_PUBLISH_VERSION_CONFLICT')
        body = {**identity(offer), 'version': family.version + 1, 'rules': rules,
            'authority_reference': authority_reference.strip(),
            'data_mode': 'SIMULATION' if authority_reference.startswith('simulation://') else 'SUPPLIER_DECLARED'}
        v = Version(version_id=ident('cfrv'), family_id=fid, version=family.version + 1,
            contract_json=body, contract_hash=digest(body), published_by=actor, created_at=now())
        s.add(v)
        family.current_version_id = v.version_id
        family.version = v.version
        s.flush()
        from go_hotel.services.catalog_supplier_remedy import event
        event(s, fid, 'CATALOG_FARE_RULE_PUBLISHED', actor, {'version_id': v.version_id, 'contract_hash': v.contract_hash,
            'supplier_id': supplier_id, 'authority_reference': authority_reference.strip()})
        return public_version(v)


def public_version(v):
    return {'version_id': v.version_id, 'rule_hash': v.contract_hash, **deepcopy(v.contract_json)}


def configured(offer_id, supplier_id):
    with SessionLocal() as s:
        offer = s.get(OfferRow, offer_id)
        if not offer or offer.supplier_id != supplier_id:
            raise ValueError('OWN_SUPPLIER_OFFER_REQUIRED')
        family = s.get(Family, family_id(offer))
        return public_version(version_checked(s, family.current_version_id)) if family and family.current_version_id else None


def demo_rules():
    # Explicit isolated fixture, never attributed to a real hotel authorization.
    return {'fare_family': 'GO_STANDARD', 'timezone': 'UTC', 'check_in_hour': 0, 'cooling_off_minutes': 0,
        'cancellation_tiers': [{'min_hours': h, 'fee_basis_points': b} for h, b in [(168, 0), (72, 2000), (24, 5000), (0, 8000)]],
        'change_allowed': True, 'change_fee_minor': 0, 'stay_credit_enabled': True,
        'stay_credit_days': 365, 'stay_credit_scope': 'PROPERTY_ONLY', 'no_show_grace_hours': 0,
        'no_show_fee_basis_points': 10000, 'credit_retained_value_basis': 'NET_CONFIRMED_CASH_INCLUDING_PAID_CHANGE_FEES',
        'cash_cancellation_value_basis': 'NET_CASH_LESS_FORFEITED_CHANGE_VALUE_INCLUDING_PAID_CHANGE_FEES'}


def seed_mock_offer(offer):
    """Only the exact local mock identity has a built-in, clearly simulated supplier policy."""
    if settings.app_env.lower() not in {'local', 'test', 'demo'} or identity(offer) != {
        'property_id': 'htl_conrad_tokyo', 'supplier_id': 'sup_mock',
        'connector_id': 'conn_mock_hotel', 'fare_rule_id': 'fr_standard_v1', 'currency': offer.currency}:
        return
    if configured(offer.offer_id, offer.supplier_id) is None:
        publish(offer.offer_id, demo_rules(), 'simulation://catalog-standard-v1', 'ISOLATED_FIXTURE_SETUP', offer.supplier_id)


def bind_offer_in_session(s, offer):
    old = s.get(OfferSnapshot, offer.offer_id)
    if old:
        return offer_snapshot_checked(s, offer, old)
    family = s.get(Family, family_id(offer))
    if not family or not family.current_version_id:
        raise ValueError('SUPPLIER_PUBLISHED_FARE_RULE_REQUIRED')
    version = version_checked(s, family.current_version_id)
    body = {'offer': offer_facts(offer), 'version': public_version(version)}
    snap = OfferSnapshot(offer_id=offer.offer_id, version_id=version.version_id,
        snapshot_json=body, snapshot_hash=digest(body), created_at=now())
    s.add(snap)
    s.flush()
    return snap


def offer_snapshot_checked(s, offer, snap):
    if digest(snap.snapshot_json) != snap.snapshot_hash or snap.snapshot_json['offer'] != offer_facts(offer):
        raise ValueError('CATALOG_OFFER_RULE_SNAPSHOT_MISMATCH')
    version = version_checked(s, snap.version_id)
    if snap.snapshot_json['version'] != public_version(version):
        raise ValueError('CATALOG_OFFER_RULE_SOURCE_MISMATCH')
    return snap


def offer_rule(offer_id):
    with transaction() as s:
        offer = s.get(OfferRow, offer_id, with_for_update=True)
        if not offer:
            raise ValueError('OFFER_NOT_FOUND')
        snap = bind_offer_in_session(s, offer)
        return {**deepcopy(snap.snapshot_json['version']), 'offer_rule_hash': snap.snapshot_hash}


def snapshot_order_in_session(s, order, expected_hash, confirmed, simulation_fixture=False):
    pb = s.get(PrebookRow, order.prebook_id, with_for_update=True)
    offer = s.get(OfferRow, pb.offer_id) if pb else None
    if not pb or not offer or (order.hotel_id, order.supplier_id, order.total_amount_minor, order.currency) != (offer.hotel_id, offer.supplier_id, pb.total_amount_minor, pb.currency):
        raise ValueError('ORDER_FARE_IDENTITY_MISMATCH')
    snap = s.get(OfferSnapshot, offer.offer_id)
    if not snap:
        raise ValueError('PREBOOK_FARE_SNAPSHOT_REQUIRED')
    offer_snapshot_checked(s, offer, snap)
    fixture = simulation_fixture and settings.app_env.lower() in {'local', 'test', 'demo'}
    if not fixture and (confirmed is not True or expected_hash != snap.snapshot_hash):
        raise ValueError('CURRENT_ORDER_FARE_CONSENT_REQUIRED')
    if expected_hash is not None and expected_hash != snap.snapshot_hash:
        raise ValueError('CURRENT_ORDER_FARE_CONSENT_REQUIRED')
    body = {**deepcopy(snap.snapshot_json), 'order_id': order.order_id, 'account_id': order.account_id,
        'prebook_id': order.prebook_id, 'order_created_at': aware(order.created_at).isoformat()}
    row = OrderSnapshot(order_id=order.order_id, version_id=snap.version_id, snapshot_json=body,
        snapshot_hash=digest(body), accepted_by=order.account_id,
        acceptance_kind='ISOLATED_FIXTURE' if fixture else 'CUSTOMER_EXPLICIT', created_at=now())
    s.add(row)
    return row


def consent_preflight(prebook_id, expected_hash, confirmed):
    with SessionLocal() as s:
        pb=s.get(PrebookRow,prebook_id)
        offer=s.get(OfferRow,pb.offer_id) if pb else None
        snap=s.get(OfferSnapshot,offer.offer_id) if offer else None
        if not snap:
            raise ValueError('PREBOOK_FARE_SNAPSHOT_REQUIRED')
        offer_snapshot_checked(s,offer,snap)
        if confirmed is not True or expected_hash!=snap.snapshot_hash:
            raise ValueError('CURRENT_ORDER_FARE_CONSENT_REQUIRED')


def order_snapshot(s, order):
    row = s.get(OrderSnapshot, order.order_id)
    if not row:
        raise ValueError('HISTORICAL_ORDER_FARE_RECONCILIATION_REQUIRED')
    body = row.snapshot_json
    if digest(body) != row.snapshot_hash or body['order_id'] != order.order_id or body['account_id'] != order.account_id or body['prebook_id'] != order.prebook_id or body['order_created_at'] != aware(order.created_at).isoformat():
        raise ValueError('ORDER_FARE_SNAPSHOT_INTEGRITY_REQUIRED')
    offer=s.get(OfferRow,body['offer']['offer_id'])
    original=s.get(OfferSnapshot,body['offer']['offer_id'])
    if not offer or not original or original.snapshot_json != {'offer':body['offer'],'version':body['version']}:
        raise ValueError('ORDER_FARE_OFFER_SOURCE_MISMATCH')
    offer_snapshot_checked(s,offer,original)
    version = version_checked(s, row.version_id)
    if body['version'] != public_version(version) or (version.contract_json['property_id'], version.contract_json['supplier_id'], version.contract_json['currency']) != (order.hotel_id, order.supplier_id, order.currency):
        raise ValueError('ORDER_FARE_SOURCE_IDENTITY_MISMATCH')
    return row


def order_rule(order_id):
    with SessionLocal() as s:
        order = s.get(OrderRow, order_id)
        if not order:
            raise ValueError('ORDER_NOT_FOUND')
        snap = order_snapshot(s, order)
        version = snap.snapshot_json['version']
        rules = version['rules']
        return {'fare_rule_id': version['fare_rule_id'], 'fare_family': rules['fare_family'],
            'change_allowed': rules['change_allowed'], **hotel_change_policy.terms(order.created_at),
            'stay_credit_allowed': rules['stay_credit_enabled'], 'stay_credit_validity_days': rules['stay_credit_days'],
            'stay_credit_scope': rules['stay_credit_scope'],
            'tiers': [{**t, 'fee_percent': t['fee_basis_points'] // 100 if t['fee_basis_points'] % 100 == 0 else t['fee_basis_points'] / 100} for t in rules['cancellation_tiers']],
            'rules': deepcopy(rules), 'version_id': version['version_id'], 'rule_hash': version['rule_hash'],
            'order_snapshot_hash': snap.snapshot_hash, 'order_created_at': snap.snapshot_json['order_created_at']}


def cancellation_terms(order, check_in, rule, at):
    rules = rule['rules']
    boundary = datetime.fromisoformat(check_in).replace(hour=rules['check_in_hour'], tzinfo=ZoneInfo(rules['timezone'])).astimezone(timezone.utc)
    if at >= boundary + timedelta(hours=rules['no_show_grace_hours']):
        raise ValueError('CANCELLATION_WINDOW_CLOSED')
    confirmed_at = None
    if rules.get('cooling_off_anchor') == 'HOTEL_CONFIRMED':
        from go_hotel.db.models import OrderSupplierFulfillmentRow as Fulfillment, OrderSupplierFulfillmentEventRow as Event
        with SessionLocal() as s:
            event = s.scalar(select(Event).join(Fulfillment,
                Fulfillment.order_supplier_fulfillment_id == Event.order_supplier_fulfillment_id).where(
                Fulfillment.business_type == 'HOTEL_ORDER', Fulfillment.business_id == order.order_id,
                Fulfillment.supplier_id == order.supplier_id,
                Event.event_type == 'SUPPLIER_FACT_RECORDED', Event.state == 'SUPPLIER_CONFIRMED'
            ).order_by(Event.occurred_at, Event.order_supplier_fulfillment_event_id))
            confirmed_at = aware(event.occurred_at) if event else None
    clock = cancellation_clock.terms(rules, check_in, boundary,
        datetime.fromisoformat(rule['order_created_at']), at, confirmed_at)
    cooling_end = clock['cooling_end']
    cooling = clock['cooling_off_applied']
    hours = max(0, (boundary - at).total_seconds() / 3600)
    bps = clock['fee_basis_points']
    expiry = min(at + timedelta(minutes=10), boundary + timedelta(hours=rules['no_show_grace_hours']))
    if cooling:
        expiry = min(expiry, cooling_end, boundary)
    for edge in clock['edges']:
        if edge > at:
            expiry = min(expiry, edge)
    return {'fee_basis_points': bps, 'cooling_off_applied': cooling, 'hours_before_checkin': hours,
        'check_in_at': boundary.isoformat(), 'hotel_timezone': rules['timezone'], 'expires_at': expiry}
