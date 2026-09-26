"""Isolated damage-case adjudication; never asserts or executes a money movement.

Existing order locks serialize the append-only case history. Supplier claim access
requires the payment root, fact binding and source decision to agree. Evidence
references are submissions, not proof of authenticity or a payment authorization.
"""
import re
from sqlalchemy import select

from go_hotel.db.models import MobilityRentalOrderRow as Order, JourneyRecoveryEvidenceChainRow as EvidenceRow
from go_hotel.domain.models import new_id
from go_hotel.mobility.rental.changes import isolated, transaction
from go_hotel.services.omnichannel_payment import digest
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence, _stable_hash


def _admin(p):
    if p.actor_type != 'GO_ADMIN' or 'admin:approve' not in p.permissions:
        raise PermissionError('DAMAGE_REVIEW_PERMISSION_REQUIRED')


def _order(s, p, order_id, allow_supplier=False):
    if allow_supplier and p.actor_type == 'SUPPLIER_USER' and p.supplier_id and 'supplier:orders' in p.permissions:
        from go_hotel.services.transaction_order_view import supplier_query
        order = s.scalar(supplier_query('RENTAL', p.supplier_id).where(Order.order_id == order_id).with_for_update())
        if order is None: raise ValueError('MOBILITY_ORDER_NOT_FOUND')
        return order
    order = s.get(Order, order_id, with_for_update=True)
    if not order or not (p.actor_type == 'GO_ADMIN' and 'admin:approve' in p.permissions
                         or p.actor_type == 'CONSUMER' and order.account_id == p.user_id):
        raise ValueError('MOBILITY_ORDER_NOT_FOUND')
    return order


def _evidence(items):
    if not isinstance(items, list) or not 1 <= len(items) <= 20:
        raise ValueError('DAMAGE_EVIDENCE_INVALID')
    clean = []
    for item in items:
        if not isinstance(item, dict) or set(item) not in ({'reference', 'sha256'}, {'reference', 'sha256', 'statement'}):
            raise ValueError('DAMAGE_EVIDENCE_INVALID')
        ref, sha = item['reference'], item['sha256']
        if not isinstance(ref, str) or not ref.strip() or len(ref) > 500 or not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha):
            raise ValueError('DAMAGE_EVIDENCE_INVALID')
        if 'statement' in item:
            # Only the authenticated operations adapter supplies this internal
            # shape. Public raw-evidence schemas reject extra statement fields.
            statement = item['statement']
            if (not isinstance(statement, dict) or digest(statement) != sha
                    or ref != 'rental-statement://' + sha
                    or statement.get('kind') != 'ACTOR_STATEMENT_UNVERIFIED'):
                raise ValueError('DAMAGE_STATEMENT_INTEGRITY_INVALID')
            clean.append({'reference': ref, 'sha256': sha, 'statement': statement})
        else:
            clean.append({'reference': ref, 'sha256': sha})
    return clean


def _history(s, oid):
    rows = s.scalars(select(EvidenceRow).where(
        EvidenceRow.execution_id == f'rc20:RENTAL:{oid}').order_by(EvidenceRow.sequence_no)).all()
    previous, events = 'GENESIS', []
    owner = s.get(Order, oid).account_id
    for sequence, row in enumerate(rows, 1):
        body = row.evidence_json
        if (not isinstance(body, dict) or row.execution_item_id != oid
                or body.get('order_id') != oid or body.get('vertical') != 'RENTAL'
                or row.sequence_no != sequence or body.get('sequence_no') != sequence
                or row.previous_hash != previous or body.get('previous_hash') != previous
                or body.get('kind') != row.evidence_kind or body.get('status') != row.observed_status
                or _stable_hash(body) != row.evidence_hash
                or _stable_hash({'evidence_hash': row.evidence_hash, 'previous_hash': previous,
                                 'sequence_no': sequence}) != row.entry_hash):
            raise ValueError('DAMAGE_EVIDENCE_INTEGRITY_INVALID')
        previous = row.entry_hash
        if row.evidence_kind == 'DAMAGE_CASE_EVENT':
            payload = body.get('payload')
            case = payload.get('case') if isinstance(payload, dict) else None
            if (not isinstance(case, dict) or case.get('order_id') != oid
                    or case.get('owner_id') != owner):
                raise ValueError('DAMAGE_EVIDENCE_INTEGRITY_INVALID')
            events.append(payload)
    return events


def _current(events, case_id):
    rows = [e for e in events if e['case']['case_id'] == case_id]
    if not rows:
        raise ValueError('DAMAGE_CASE_NOT_FOUND')
    return rows[-1]['case']


def _replay(events, p, key, request):
    if not isinstance(key, str) or not key.strip() or len(key) > 128:
        raise ValueError('DAMAGE_IDEMPOTENCY_KEY_INVALID')
    fingerprint = digest(request)
    for event in events:
        if event['actor_id'] == p.user_id and event['key'] == key:
            if event['fingerprint'] != fingerprint:
                raise ValueError('DAMAGE_IDEMPOTENCY_CONFLICT')
            return event['case']
    return None


def _append(s, order, p, key, request, case):
    append_vertical_evidence(s, 'RENTAL', order.order_id, 'DAMAGE_CASE_EVENT', order.status,
        {'actor_id': p.user_id, 'actor_type': p.actor_type, 'key': key,
         'fingerprint': digest(request), 'case': case}, source='C04_DAMAGE_CASE')
    return case


def open_case(p, order_id, key, amount_minor, currency, pickup_evidence, return_evidence):
    isolated()
    if p.actor_type != 'SUPPLIER_USER' or 'supplier:orders' not in p.permissions: _admin(p)
    pickup, returned = _evidence(pickup_evidence), _evidence(return_evidence)
    if {x['sha256'] for x in pickup} & {x['sha256'] for x in returned}:
        raise ValueError('DAMAGE_DISTINCT_INSPECTIONS_REQUIRED')
    if type(amount_minor) is not int or amount_minor <= 0:
        raise ValueError('DAMAGE_AMOUNT_INVALID')
    request = ['OPEN', order_id, amount_minor, currency, pickup, returned]
    with transaction() as s:
        o = _order(s, p, order_id, allow_supplier=True); events = _history(s, order_id)
        old = _replay(events, p, key, request)
        if old is not None: return old
        if o.status != 'COMPLETED': raise ValueError('DAMAGE_RETURN_REQUIRED')
        # One frozen case per rental: supplemental claims require a future,
        # reviewed amendment workflow, never another independently chargeable case.
        if events: raise ValueError('DAMAGE_CASE_ALREADY_EXISTS')
        excess = (o.insurance or {}).get('excess_minor')
        if type(excess) is not int or excess < 0 or type(o.deposit_minor) is not int or o.deposit_minor < 0:
            raise ValueError('DAMAGE_CONTRACT_REVIEW_REQUIRED')
        cap = min(o.deposit_minor, excess)
        if currency != o.currency or amount_minor > cap:
            raise ValueError('DAMAGE_CONTRACT_AMOUNT_INVALID')
        from go_hotel.mobility.rental.deposit_authority import binding_for_case, assert_case_open_allowed
        assert_case_open_allowed(s, o)
        deposit_obligation = binding_for_case(s, o)
        case = {'case_id': new_id('rent_damage'), 'order_id': order_id,
            'deposit_obligation': deposit_obligation,
            'owner_id': o.account_id, 'opened_by': p.user_id, 'status': 'AWAITING_CUSTOMER',
            'version': 1, 'claimed_minor': amount_minor, 'currency': currency,
            'contract_snapshot': {'deposit_minor': o.deposit_minor, 'insurance': o.insurance,
                                  'maximum_award_minor': cap},
            'pickup_evidence': pickup, 'return_evidence': returned,
            'supplier_evidence_status': 'SUPPLIER_STATEMENT_UNVERIFIED' if p.actor_type == 'SUPPLIER_USER' else 'ADMIN_RECORDED_UNVERIFIED',
            'customer_evidence': [], 'customer_response': None, 'awarded_minor': None,
            'actionable_award_minor': None, 'decision_history': [], 'appeals': [],
            'money_instruction_state': 'BLOCKED_PENDING_DECISION',
            'money_status': 'NOT_REQUESTED', 'money_movement_ids': [],
            'data_mode': 'ISOLATED_CONTRACT_FIXTURE', 'external_live': False}
        return _append(s, o, p, key, request, case)


def respond(p, order_id, case_id, key, expected_version, response, evidence):
    isolated()
    if p.actor_type != 'CONSUMER': raise PermissionError('CONSUMER_IDENTITY_REQUIRED')
    submitted = _evidence(evidence)
    if response not in {'ACCEPT', 'DISPUTE'}: raise ValueError('DAMAGE_RESPONSE_INVALID')
    request = ['RESPOND', case_id, expected_version, response, submitted]
    with transaction() as s:
        o = _order(s, p, order_id); events = _history(s, order_id)
        old = _replay(events, p, key, request)
        if old is not None: return old
        case = _current(events, case_id)
        if type(expected_version) is not int or case['version'] != expected_version:
            raise ValueError('DAMAGE_VERSION_CONFLICT')
        if case['status'] != 'AWAITING_CUSTOMER': raise ValueError('DAMAGE_STATE_CONFLICT')
        case = {**case, 'status': 'REVIEW_REQUIRED', 'version': case['version'] + 1,
                'customer_response': response, 'customer_evidence': submitted,
                'responded_by': p.user_id}
        return _append(s, o, p, key, request, case)


def adjudicate(p, order_id, case_id, key, expected_version, award_minor, reason, evidence):
    isolated(); _admin(p)
    submitted = _evidence(evidence)
    if type(award_minor) is not int or award_minor < 0 or not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        raise ValueError('DAMAGE_DECISION_INVALID')
    request = ['ADJUDICATE', case_id, expected_version, award_minor, reason, submitted]
    with transaction() as s:
        o = _order(s, p, order_id); events = _history(s, order_id)
        old = _replay(events, p, key, request)
        if old is not None: return old
        case = _current(events, case_id)
        if p.user_id in {case['owner_id'], case['opened_by'], case.get('responded_by')}:
            raise PermissionError('DAMAGE_INDEPENDENT_REVIEWER_REQUIRED')
        if type(expected_version) is not int or case['version'] != expected_version:
            raise ValueError('DAMAGE_VERSION_CONFLICT')
        if case['status'] != 'REVIEW_REQUIRED': raise ValueError('DAMAGE_STATE_CONFLICT')
        if award_minor > min(case['claimed_minor'], case['contract_snapshot']['maximum_award_minor']):
            raise ValueError('DAMAGE_AWARD_EXCEEDS_CLAIM')
        case = {**case, 'status': 'ADJUDICATED', 'version': case['version'] + 1,
                'awarded_minor': award_minor, 'reviewer_id': p.user_id,
                'decision_reason': reason, 'decision_evidence': submitted,
                'actionable_award_minor': award_minor,
                'money_instruction_state': 'AWAITING_C11_REVIEW',
                'decision_history': [{'version': case['version'] + 1, 'reviewer_id': p.user_id,
                    'award_minor': award_minor, 'reason': reason, 'evidence': submitted}],
                'money_status': 'C11_MONEY_REVIEW_REQUIRED'}
        return _append(s, o, p, key, request, case)


def appeal(p, order_id, case_id, key, expected_version, reason, evidence):
    isolated()
    if p.actor_type != 'CONSUMER': raise PermissionError('CONSUMER_IDENTITY_REQUIRED')
    submitted = _evidence(evidence)
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        raise ValueError('DAMAGE_APPEAL_INVALID')
    request = ['APPEAL', case_id, expected_version, reason, submitted]
    with transaction() as s:
        o = _order(s, p, order_id); events = _history(s, order_id)
        old = _replay(events, p, key, request)
        if old is not None: return old
        case = _current(events, case_id)
        if type(expected_version) is not int or case['version'] != expected_version:
            raise ValueError('DAMAGE_VERSION_CONFLICT')
        if case['status'] != 'ADJUDICATED': raise ValueError('DAMAGE_STATE_CONFLICT')
        case = {**case, 'status': 'APPEAL_REVIEW_REQUIRED', 'version': case['version'] + 1,
                'actionable_award_minor': None, 'money_instruction_state': 'DISPUTE_HOLD',
                'money_status': 'C11_MONEY_REVIEW_REQUIRED',
                'appeals': case['appeals'] + [{'actor_id': p.user_id, 'reason': reason,
                    'evidence': submitted, 'decision_version': case['version']} ]}
        return _append(s, o, p, key, request, case)


def review_appeal(p, order_id, case_id, key, expected_version, award_minor, reason, evidence):
    isolated(); _admin(p)
    submitted = _evidence(evidence)
    if type(award_minor) is not int or award_minor < 0 or not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        raise ValueError('DAMAGE_DECISION_INVALID')
    request = ['REVIEW_APPEAL', case_id, expected_version, award_minor, reason, submitted]
    with transaction() as s:
        o = _order(s, p, order_id); events = _history(s, order_id)
        old = _replay(events, p, key, request)
        if old is not None: return old
        case = _current(events, case_id)
        prior_reviewers = {d['reviewer_id'] for d in case['decision_history']}
        if p.user_id in prior_reviewers | {case['owner_id'], case['opened_by']}:
            raise PermissionError('DAMAGE_INDEPENDENT_REVIEWER_REQUIRED')
        if type(expected_version) is not int or case['version'] != expected_version:
            raise ValueError('DAMAGE_VERSION_CONFLICT')
        if case['status'] != 'APPEAL_REVIEW_REQUIRED': raise ValueError('DAMAGE_STATE_CONFLICT')
        if award_minor > min(case['claimed_minor'], case['contract_snapshot']['maximum_award_minor']):
            raise ValueError('DAMAGE_AWARD_EXCEEDS_CLAIM')
        decision = {'version': case['version'] + 1, 'reviewer_id': p.user_id,
                    'award_minor': award_minor, 'reason': reason, 'evidence': submitted,
                    'supersedes_decision_version': case['decision_history'][-1]['version']}
        case = {**case, 'status': 'ADJUDICATED', 'version': case['version'] + 1,
                'awarded_minor': award_minor, 'reviewer_id': p.user_id,
                'decision_reason': reason, 'decision_evidence': submitted,
                'actionable_award_minor': award_minor,
                'money_instruction_state': 'AWAITING_C11_REVIEW',
                'decision_history': case['decision_history'] + [decision],
                # No booked-money mutation. C11 must compare prior receipts and
                # create compensation if a future integration has executed them.
                'money_status': 'C11_MONEY_REVIEW_REQUIRED'}
        return _append(s, o, p, key, request, case)


def get_case(p, order_id, case_id):
    with transaction() as s:
        _order(s, p, order_id)
        return _current(_history(s, order_id), case_id)
