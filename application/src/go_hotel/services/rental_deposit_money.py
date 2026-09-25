"""Isolated rental deposit settlement on the existing C11 money graph.

C04 owns obligation/consent/adjudication facts. This module owns no parallel
ledger and accepts no caller amount, currency or payee. No real PSP is invoked.
"""
from contextlib import contextmanager

from sqlalchemy import select

from go_hotel.db.models import (OmnichannelPaymentIntentRow as Intent,
    PaymentOrderRootRow as Root, PaymentOrderFactBindingRow as Binding,
    VerticalSourceDecisionRow as SourceDecision, OmnichannelMoneyMovementRow as Movement,
    OmnichannelLedgerEntryRow as Ledger)
from go_hotel.mobility.rental.changes import isolated, transaction
from go_hotel.services.omnichannel_payment import digest, ident, now, legal_entity
from go_hotel.services.unified_money_movement import unified_money_movement_service as money

BUSINESS = 'RENTAL_DEPOSIT'
_SCOPE = object()


def _admin(principal):
    isolated()
    if principal.actor_type != 'GO_ADMIN' or 'admin:approve' not in principal.permissions:
        raise PermissionError('RENTAL_DEPOSIT_MONEY_PERMISSION_REQUIRED')


def assert_money_action(session, intent, kind, amount, parent_id, key):
    """Generic movement ingress cannot substitute caller data for C04 authority."""
    if intent.business_type != BUSINESS:
        return
    isolated()
    scope = session.info.get(_SCOPE)
    if not scope or scope[0] != intent.payment_intent_id or scope[1].get((kind, key)) != (amount, parent_id):
        raise ValueError('RENTAL_DEPOSIT_VERIFIED_SOURCE_SCOPE_REQUIRED')


@contextmanager
def _scope(session, intent_id, allowed):
    if _SCOPE in session.info:
        raise ValueError('RENTAL_DEPOSIT_NESTED_SCOPE_FORBIDDEN')
    session.info[_SCOPE] = (intent_id, allowed)
    try:
        yield
    finally:
        session.info.pop(_SCOPE, None)


def _facts(source):
    fields = ('obligation_id', 'order_id', 'owner_id', 'payee_id', 'currency',
              'amount_minor', 'revision', 'source_hash', 'vehicle_id', 'expires_at')
    if any(source.get(field) in (None, '') for field in fields):
        raise ValueError('RENTAL_DEPOSIT_COMPLETE_SOURCE_REQUIRED')
    if (source.get('state') != 'ACTIVATED' or source.get('data_mode') != 'ISOLATED_CONTRACT_FIXTURE'
            or source.get('external_live') is not False or type(source['amount_minor']) is not int
            or source['amount_minor'] <= 0):
        raise ValueError('RENTAL_DEPOSIT_ACTIVATED_ISOLATED_SOURCE_REQUIRED')
    return {field: source[field] for field in fields}


def _root(session, source, *, create=False):
    facts = _facts(source)
    fingerprint = digest(facts)
    root = session.scalar(select(Root).where(Root.business_type == BUSINESS,
        Root.business_id == source['obligation_id']).with_for_update())
    if root:
        intent = session.scalar(select(Intent).where(Intent.payment_intent_id == root.payment_intent_id).with_for_update())
        binding = session.scalar(select(Binding).where(Binding.payment_intent_id == root.payment_intent_id))
        decision = session.get(SourceDecision, binding.source_decision_id) if binding else None
        expected = (BUSINESS, source['obligation_id'], source['owner_id'], source['payee_id'],
                    source['amount_minor'], source['currency'])
        if (not intent or not binding
                or (intent.business_type, intent.business_id, intent.payer_id, intent.payee_id, intent.amount_minor, intent.currency) != expected
                or (binding.business_type, binding.business_id, binding.payer_id, binding.payee_id, binding.amount_minor, binding.currency) != expected
                or binding.order_fact_hash != fingerprint or binding.request_fingerprint != fingerprint
                or not decision or decision.decision_hash != fingerprint or decision.candidate_snapshot_json != [facts]
                or decision.selected_source_id != source['payee_id'] or decision.business_id != source['obligation_id']
                or intent.operation != 'AUTHORIZE' or intent.selected_channel != 'LOCAL_MARKET'
                or intent.automatic_fallback_allowed
                or root.legal_entity_id != legal_entity(source['currency']) or binding.legal_entity_id != root.legal_entity_id
                or root.root_hash != digest([BUSINESS, source['obligation_id'], intent.payment_intent_id, root.legal_entity_id])
                or root.state != 'ACTIVE'):
            raise ValueError('RENTAL_DEPOSIT_ROOT_BINDING_INVALID')
        if intent.state != 'SUCCEEDED':
            raise ValueError('RENTAL_DEPOSIT_RECONCILIATION_REQUIRED')
        return intent, False
    if session.scalar(select(Intent).where(Intent.business_type == BUSINESS,
            Intent.business_id == source['obligation_id'])):
        raise ValueError('RENTAL_DEPOSIT_UNBOUND_INTENT_REQUIRES_REVIEW')
    if not create:
        raise ValueError('RENTAL_DEPOSIT_AUTHORIZATION_REQUIRED')
    from go_hotel.db.models import MobilityRentalOrderRow as Order
    order = session.get(Order, source['order_id'])
    if not order or order.status not in {'CONFIRMED', 'IN_PROGRESS'}:
        raise ValueError('RENTAL_DEPOSIT_NEW_AUTHORIZATION_NOT_ALLOWED')
    timestamp = now()
    iid, source_id = ident('opi'), ident('vsd')
    entity = legal_entity(source['currency'])
    intent = Intent(payment_intent_id=iid, business_type=BUSINESS, business_id=source['obligation_id'],
        payer_id=source['owner_id'], payee_id=source['payee_id'], operation='AUTHORIZE',
        amount_minor=source['amount_minor'], currency=source['currency'], channel_priority_json=['LOCAL_MARKET'],
        selected_channel='LOCAL_MARKET', state='SUCCEEDED', idempotency_key='rental-deposit-intent:' + source['obligation_id'],
        automatic_fallback_allowed=False, user_channel_consent_at=timestamp, created_at=timestamp, updated_at=timestamp)
    session.add(intent)
    session.flush()
    session.add(Root(payment_order_root_id=ident('por'), business_type=BUSINESS, business_id=source['obligation_id'],
        payment_intent_id=iid, legal_entity_id=entity, state='ACTIVE',
        root_hash=digest([BUSINESS, source['obligation_id'], iid, entity]), created_at=timestamp))
    session.add(SourceDecision(vertical_source_decision_id=source_id, vertical='RENTAL', business_id=source['obligation_id'],
        selected_source_id=source['payee_id'], selected_source_type='RENTAL_DEPOSIT_SIMULATION', route='ISOLATED_RENTAL_DEPOSIT',
        authority_reference=source['evidence_reference'], evidence_reference=source['evidence_reference'],
        candidate_snapshot_json=[facts], reason_codes_json=['EXPLICIT_DEPOSIT_CONSENT', 'ISOLATED_CONTRACT_FIXTURE'],
        decision_hash=fingerprint, created_at=timestamp))
    session.add(Binding(payment_order_fact_binding_id=ident('pofb'), payment_intent_id=iid, business_type=BUSINESS,
        business_id=source['obligation_id'], payer_id=source['owner_id'], payee_id=source['payee_id'],
        amount_minor=source['amount_minor'], currency=source['currency'], legal_entity_id=entity, source_decision_id=source_id,
        request_fingerprint=fingerprint, order_fact_hash=fingerprint, evidence_reference=source['evidence_reference'], created_at=timestamp))
    session.flush()
    return intent, True


def _graph(session, intent):
    rows = list(session.scalars(select(Movement).where(Movement.root_payment_intent_id == intent.payment_intent_id).with_for_update()))
    if any(row.state != 'CONFIRMED' for row in rows):
        raise ValueError('RENTAL_DEPOSIT_RECONCILIATION_REQUIRED')
    if any((row.business_type, row.business_id, row.currency) != (BUSINESS, intent.business_id, intent.currency)
           or type(row.amount_minor) is not int or row.amount_minor <= 0
           or row.movement_type not in {'AUTHORIZATION', 'CAPTURE', 'RELEASE'} for row in rows):
        raise ValueError('RENTAL_DEPOSIT_GRAPH_INVALID')
    authorizations = [row for row in rows if row.movement_type == 'AUTHORIZATION']
    if len(authorizations) != 1:
        raise ValueError('RENTAL_DEPOSIT_AUTHORIZATION_REQUIRED')
    auth = authorizations[0]
    if auth.amount_minor != intent.amount_minor or auth.parent_movement_id or any(
            row.parent_movement_id != auth.money_movement_id for row in rows if row != auth):
        raise ValueError('RENTAL_DEPOSIT_GRAPH_INVALID')
    if sum(row.amount_minor for row in rows if row != auth) > auth.amount_minor:
        raise ValueError('RENTAL_DEPOSIT_GRAPH_INVALID')
    ledger = list(session.scalars(select(Ledger).where(Ledger.payment_intent_id == intent.payment_intent_id)))
    captures = {row.money_movement_id: row for row in rows if row.movement_type == 'CAPTURE'}
    if len(ledger) != len(captures) * 2 or any(entry.transaction_id not in captures for entry in ledger):
        raise ValueError('RENTAL_DEPOSIT_LEDGER_INVALID')
    for capture_id, capture in captures.items():
        entries = [entry for entry in ledger if entry.transaction_id == capture_id]
        expected = {('PAYMENT_CLEARING:LOCAL_MARKET', 'DEBIT'), (f'BUSINESS:{BUSINESS}:{intent.business_id}', 'CREDIT')}
        if len(entries) != 2 or {(entry.account_code, entry.direction) for entry in entries} != expected or any(
                entry.amount_minor != capture.amount_minor or entry.currency != intent.currency
                or entry.entry_type != 'CAPTURE' or entry.evidence_hash != digest({'movement': capture_id}) for entry in entries):
            raise ValueError('RENTAL_DEPOSIT_LEDGER_INVALID')
    return auth, rows


def _result(intent, rows):
    captured = sum(row.amount_minor for row in rows if row.movement_type == 'CAPTURE')
    released = sum(row.amount_minor for row in rows if row.movement_type == 'RELEASE')
    return {'payment_intent_id': intent.payment_intent_id, 'obligation_id': intent.business_id,
        'currency': intent.currency, 'authorized_minor': intent.amount_minor, 'captured_minor': captured,
        'released_minor': released, 'remaining_minor': intent.amount_minor - captured - released,
        'movement_ids': [row.money_movement_id for row in rows],
        'state': 'SETTLED' if captured + released == intent.amount_minor else 'AUTHORIZED',
        'data_mode': 'ISOLATED_CONTRACT_FIXTURE', 'external_live': False}


def authorize(principal, order_id, obligation_id, expected_revision, expected_source_hash):
    _admin(principal)
    from go_hotel.mobility.rental.deposit_authority import resolve_obligation
    with transaction() as session:
        source = resolve_obligation(session, order_id, obligation_id, expected_revision, expected_source_hash)
        intent, created = _root(session, source, create=True)
        rows = list(session.scalars(select(Movement).where(Movement.root_payment_intent_id == intent.payment_intent_id)))
        if not rows:
            if not created:
                raise ValueError('RENTAL_DEPOSIT_RECONCILIATION_REQUIRED')
            key = 'rental-deposit-auth:' + obligation_id
            with _scope(session, intent.payment_intent_id, {('AUTHORIZATION', key): (intent.amount_minor, None)}):
                money.create_in_session(session, intent.payment_intent_id, {'movement_type': 'AUTHORIZATION',
                    'amount_minor': intent.amount_minor, 'mode': 'CONTRACT_SIMULATOR',
                    'evidence': [source['evidence_reference']]}, key, principal.user_id)
        _, rows = _graph(session, intent)
        return _result(intent, rows)


def settle(principal, order_id, obligation_id, expected_revision, expected_source_hash,
           case_id, expected_case_version, expected_decision_hash):
    _admin(principal)
    from go_hotel.mobility.rental.deposit_authority import resolve_obligation, resolve_decision
    with transaction() as session:
        source = resolve_obligation(session, order_id, obligation_id, expected_revision, expected_source_hash, allow_expired=True)
        decision = resolve_decision(session, order_id, obligation_id, case_id, expected_case_version, expected_decision_hash)
        if (decision.get('order_id'), decision.get('obligation_id'), decision.get('owner_id'), decision.get('currency'),
                decision.get('source_hash'), decision.get('obligation_revision'), decision.get('case_id'),
                decision.get('case_version'), decision.get('decision_hash')) != (
                order_id, obligation_id, source['owner_id'], source['currency'], source['source_hash'], source['revision'],
                case_id, expected_case_version, expected_decision_hash) or decision.get('status') != 'ADJUDICATED' or decision.get('held') is not False:
            raise ValueError('RENTAL_DEPOSIT_DECISION_BINDING_INVALID')
        award = decision['awarded_minor']
        if type(award) is not int or not 0 <= award <= source['amount_minor']:
            raise ValueError('RENTAL_DEPOSIT_AWARD_INVALID')
        if award:
            resolve_obligation(session, order_id, obligation_id, expected_revision, expected_source_hash)
        intent, _ = _root(session, source)
        auth, rows = _graph(session, intent)
        prefix = 'rental-deposit:' + digest([obligation_id, case_id, expected_case_version, expected_decision_hash])
        operations = [('CAPTURE', award, prefix + ':capture'), ('RELEASE', intent.amount_minor - award, prefix + ':release')]
        expected = {(kind, key): (amount, auth.money_movement_id) for kind, amount, key in operations if amount}
        if any(row.movement_type != 'AUTHORIZATION' and (row.movement_type, row.idempotency_key) not in expected for row in rows):
            raise ValueError('RENTAL_DEPOSIT_SETTLEMENT_ALREADY_BOUND')
        with _scope(session, intent.payment_intent_id, expected):
            for kind, amount, key in operations:
                if amount:
                    money.create_in_session(session, intent.payment_intent_id, {'movement_type': kind,
                        'amount_minor': amount, 'parent_movement_id': auth.money_movement_id,
                        'mode': 'CONTRACT_SIMULATOR', 'evidence': [source['evidence_reference'],
                            'rental-damage-decision://' + case_id + '/' + expected_decision_hash]}, key, principal.user_id)
        _, rows = _graph(session, intent)
        return _result(intent, rows)


def status(principal, order_id, obligation_id, expected_revision, expected_source_hash):
    isolated()
    from go_hotel.db.models import MobilityRentalOrderRow as Order
    from go_hotel.mobility.rental.deposit_authority import resolve_obligation
    with transaction() as session:
        order = session.get(Order, order_id, with_for_update=True)
        if not order or not (principal.actor_type == 'CONSUMER' and principal.user_id == order.account_id
                or principal.actor_type == 'GO_ADMIN' and 'admin:approve' in principal.permissions):
            raise ValueError('MOBILITY_ORDER_NOT_FOUND')
        source = resolve_obligation(session, order_id, obligation_id, expected_revision, expected_source_hash, allow_expired=True)
        base = {'payment_intent_id': None, 'obligation_id': obligation_id, 'currency': source['currency'],
                'authorized_minor': 0, 'captured_minor': 0, 'released_minor': 0, 'remaining_minor': 0,
                'movement_ids': [], 'state': 'NOT_AUTHORIZED', 'data_mode': 'ISOLATED_CONTRACT_FIXTURE', 'external_live': False}
        root = session.scalar(select(Root).where(Root.business_type == BUSINESS, Root.business_id == obligation_id))
        if not root:
            orphan = session.scalar(select(Intent).where(Intent.business_type == BUSINESS, Intent.business_id == obligation_id))
            if orphan or session.scalar(select(Movement).where(Movement.business_type == BUSINESS, Movement.business_id == obligation_id)):
                return {**base, 'state': 'RECONCILIATION_REQUIRED', 'authorized_minor': None,
                        'captured_minor': None, 'released_minor': None, 'remaining_minor': None}
            return base
        try:
            intent, _ = _root(session, source)
            _, rows = _graph(session, intent)
            return _result(intent, rows)
        except ValueError:
            return {**base, 'state': 'RECONCILIATION_REQUIRED', 'authorized_minor': None,
                    'captured_minor': None, 'released_minor': None, 'remaining_minor': None}


def release(principal, order_id, obligation_id, expected_revision, expected_source_hash,
            expected_release_revision, expected_release_hash):
    """No-damage/cancel release requires its own C04 closure fact, never a fake claim."""
    _admin(principal)
    from go_hotel.mobility.rental.deposit_authority import resolve_obligation, resolve_release
    with transaction() as session:
        source = resolve_obligation(session, order_id, obligation_id, expected_revision, expected_source_hash, allow_expired=True)
        closure = resolve_release(session, order_id, obligation_id, expected_release_revision, expected_release_hash)
        if (closure.get('order_id'), closure.get('obligation_id'), closure.get('source_hash'),
                closure.get('obligation_revision'), closure.get('release_revision'), closure.get('release_hash')) != (
                order_id, obligation_id, source['source_hash'], source['revision'], expected_release_revision, expected_release_hash
                ) or closure.get('state') != 'RELEASE_APPROVED' or closure.get('held') is not False:
            raise ValueError('RENTAL_DEPOSIT_RELEASE_BINDING_INVALID')
        intent, _ = _root(session, source)
        auth, rows = _graph(session, intent)
        key = 'rental-deposit-release:' + digest([obligation_id, expected_release_revision, expected_release_hash])
        if any(row.movement_type != 'AUTHORIZATION' and (row.movement_type, row.idempotency_key) != ('RELEASE', key) for row in rows):
            raise ValueError('RENTAL_DEPOSIT_SETTLEMENT_ALREADY_BOUND')
        with _scope(session, intent.payment_intent_id, {('RELEASE', key): (auth.amount_minor, auth.money_movement_id)}):
            money.create_in_session(session, intent.payment_intent_id, {'movement_type': 'RELEASE',
                'amount_minor': auth.amount_minor, 'parent_movement_id': auth.money_movement_id,
                'mode': 'CONTRACT_SIMULATOR', 'evidence': [source['evidence_reference'],
                    'c04-return-release://' + obligation_id + '/' + expected_release_hash]}, key, principal.user_id)
        _, rows = _graph(session, intent)
        return _result(intent, rows)
