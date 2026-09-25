"""C04 isolated deposit obligation authority, never a money balance or receipt.

Only a server-owned synthetic contract is supported. ACTIVATED means explicit
consumer agreement, not financial authorization. C11 resolves this evidence in
its transaction (order lock before payment-intent lock).
"""
from copy import deepcopy
from datetime import datetime, timedelta

from sqlalchemy import select

from go_hotel.db.models import MobilityRentalOrderRow as Order, JourneyRecoveryEvidenceChainRow as EvidenceRow
from go_hotel.mobility.rental.changes import isolated, transaction, now
from go_hotel.mobility.rental import damage
from go_hotel.services.omnichannel_payment import digest
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence

KIND = 'RENTAL_DEPOSIT_OBLIGATION'
MODE = 'ISOLATED_CONTRACT_FIXTURE'
FIXTURE_VERSION = 'rental-deposit-isolated-v1'
# Immutable engineering fixture, not an approved real-world contract or policy.
_FIXTURES = {
    'COMPACT': {'currency': 'CNY', 'deposit_minor': 200000,
                'insurance': {'type': 'BASIC', 'excess_minor': 500000}},
    'SUV': {'currency': 'CNY', 'deposit_minor': 300000,
            'insurance': {'type': 'FULL', 'excess_minor': 0}},
}


def _identity(order_id):
    return 'rent_dep_' + digest(['C04', FIXTURE_VERSION, order_id])[:40]


def _locked_order(session, order_id):
    order = session.get(Order, order_id, with_for_update=True)
    if not order: raise ValueError('MOBILITY_ORDER_NOT_FOUND')
    return order


def _owner(session, p, order_id):
    o = _locked_order(session, order_id)
    if p.actor_type != 'CONSUMER' or p.user_id != o.account_id:
        raise ValueError('MOBILITY_ORDER_NOT_FOUND')
    return o


def _source(order):
    fixture = _FIXTURES.get(order.vehicle_class)
    if (not fixture or type(order.deposit_minor) is not int
            or order.deposit_minor != fixture['deposit_minor']
            or order.currency != fixture['currency'] or order.insurance != fixture['insurance']):
        raise ValueError('DEPOSIT_APPROVED_SOURCE_UNAVAILABLE')
    t = now()
    terms = {'fixture_version': FIXTURE_VERSION, 'vehicle_class': order.vehicle_class,
        'maximum_authorization_minor': fixture['deposit_minor'],
        'maximum_damage_award_minor': min(fixture['deposit_minor'], fixture['insurance']['excess_minor']),
        'currency': fixture['currency'], 'insurance': deepcopy(fixture['insurance']),
        'consent_scope': 'DEPOSIT_OBLIGATION_ONLY_NOT_DAMAGE_ACCEPTANCE',
        'damage_requires_independent_decision': True, 'silence_is_not_acceptance': True,
        'fixture_validity_seconds': 86400, 'real_contract_approved': False}
    return {'order_id': order.order_id, 'owner_id': order.account_id,
        'vehicle_id': 'fixture-vehicle-' + digest(order.order_id)[:24],
        'payee_id': 'fixture-rental-merchant-v1',
        'payee_verification': {'status': 'VERIFIED_SYNTHETIC_FIXTURE', 'version': FIXTURE_VERSION,
                               'real_payee_verified': False},
        'currency': fixture['currency'], 'amount_minor': fixture['deposit_minor'],
        'contract_snapshot': terms, 'terms_hash': digest(terms),
        'issued_at': t.isoformat(), 'expires_at': (t + timedelta(days=1)).isoformat(),
        'data_mode': MODE, 'external_live': False}


def _events(session, order):
    damage._history(session, order.order_id)  # validates the entire order chain
    rows = list(session.scalars(select(EvidenceRow).where(
        EvidenceRow.execution_id == f'rc20:RENTAL:{order.order_id}',
        EvidenceRow.evidence_kind == KIND).order_by(EvidenceRow.sequence_no)))
    result, previous = [], None
    for revision, row in enumerate(rows, 1):
        event = row.evidence_json['payload']
        obligation = event.get('obligation', {})
        source = obligation.get('source', {})
        valid = (obligation.get('obligation_id') == _identity(order.order_id)
                 and obligation.get('revision') == revision
                 and source.get('order_id') == order.order_id and source.get('owner_id') == order.account_id
                 and digest(source) == obligation.get('source_hash')
                 and source.get('data_mode') == MODE and source.get('external_live') is False
                 and digest(source.get('contract_snapshot')) == source.get('terms_hash'))
        if revision == 1:
            valid = valid and row.evidence_chain_id == _identity(order.order_id) and obligation.get('state') == 'PROPOSED'
        elif obligation.get('state') == 'ACTIVATED':
            consent = obligation.get('consent', {})
            valid = (valid and previous['state'] == 'PROPOSED'
                     and previous['source_hash'] == obligation['source_hash']
                     and consent.get('actor_id') == order.account_id and consent.get('accepted') is True
                     and consent.get('source_hash') == obligation.get('source_hash')
                     and consent.get('terms_hash') == source.get('terms_hash'))
        elif obligation.get('state') == 'PROPOSED':
            valid = (valid and previous['state'] == 'PROPOSED' and obligation.get('consent') is None
                     and obligation.get('renewed_from_source_hash') == previous['source_hash']
                     and datetime.fromisoformat(source['issued_at']) >= datetime.fromisoformat(previous['source']['expires_at'])
                     and source['issued_at'] != previous['source']['issued_at'])
        else:
            valid = False
        if not valid: raise ValueError('DEPOSIT_OBLIGATION_INTEGRITY_INVALID')
        previous = obligation; result.append(event)
    return result


def _replay(events, p, key, request):
    if not isinstance(key, str) or not key.strip() or len(key) > 128:
        raise ValueError('DEPOSIT_IDEMPOTENCY_KEY_INVALID')
    for event in events:
        if event['actor_id'] == p.user_id and event['key'] == key:
            if event['request_hash'] != digest(request): raise ValueError('DEPOSIT_IDEMPOTENCY_CONFLICT')
            return deepcopy(event['obligation'])
    return None


def _append(session, order, p, key, request, obligation):
    row = append_vertical_evidence(session, 'RENTAL', order.order_id, KIND, order.status,
        {'actor_id': p.user_id, 'key': key, 'request_hash': digest(request), 'obligation': obligation},
        source='C04_DEPOSIT_AUTHORITY')
    if obligation['revision'] == 1:
        # DB primary-key uniqueness is a second fence in addition to order lock.
        row.evidence_chain_id = obligation['obligation_id']; session.flush()
    return obligation


def propose(p, order_id, key):
    isolated()
    with transaction() as s:
        o = _owner(s, p, order_id); events = _events(s, o)
        request = ['PROPOSE', order_id]
        prior = _replay(events, p, key, request)
        if prior is not None: return prior
        if events: raise ValueError('DEPOSIT_OBLIGATION_ALREADY_EXISTS')
        if o.status not in {'CONFIRMED', 'IN_PROGRESS'}: raise ValueError('DEPOSIT_ORDER_NOT_ELIGIBLE')
        source = _source(o)
        obligation = {'obligation_id': _identity(order_id), 'revision': 1, 'state': 'PROPOSED',
                      'source': source, 'source_hash': digest(source), 'consent': None,
                      'financial_state': 'NO_FINANCIAL_FACT_ASSERTED'}
        return _append(s, o, p, key, request, obligation)


def accept(p, order_id, obligation_id, key, expected_revision, expected_source_hash, accepted):
    isolated()
    if accepted is not True: raise ValueError('DEPOSIT_EXPLICIT_ACCEPTANCE_REQUIRED')
    request = ['ACCEPT', obligation_id, expected_revision, expected_source_hash, accepted]
    with transaction() as s:
        o = _owner(s, p, order_id); events = _events(s, o)
        prior = _replay(events, p, key, request)
        if prior is not None: return prior
        if not events: raise ValueError('DEPOSIT_OBLIGATION_NOT_FOUND')
        current = events[-1]['obligation']
        if obligation_id != current['obligation_id']: raise ValueError('DEPOSIT_OBLIGATION_NOT_FOUND')
        if type(expected_revision) is not int or expected_revision != current['revision'] or expected_source_hash != current['source_hash']:
            raise ValueError('DEPOSIT_SOURCE_VERSION_CONFLICT')
        if current['state'] != 'PROPOSED': raise ValueError('DEPOSIT_STATE_CONFLICT')
        if o.status not in {'CONFIRMED', 'IN_PROGRESS'}: raise ValueError('DEPOSIT_ORDER_NOT_ELIGIBLE')
        _check_source_current(o, current['source'])
        _not_expired(current['source'])
        result = {**current, 'revision': current['revision'] + 1, 'state': 'ACTIVATED',
                  'consent': {'actor_id': p.user_id, 'accepted': True, 'source_hash': current['source_hash'],
                              'terms_hash': current['source']['terms_hash'], 'accepted_at': now().isoformat()}}
        return _append(s, o, p, key, request, result)


def _not_expired(source):
    if datetime.fromisoformat(source['expires_at']) <= now(): raise ValueError('DEPOSIT_SOURCE_EXPIRED')


def renew(p, order_id, obligation_id, key, expected_revision, expected_source_hash):
    """Replace only an expired, never-accepted proposal; require fresh consent."""
    isolated()
    request = ['RENEW', obligation_id, expected_revision, expected_source_hash]
    with transaction() as s:
        o = _owner(s, p, order_id); events = _events(s, o)
        prior = _replay(events, p, key, request)
        if prior is not None: return prior
        if not events: raise ValueError('DEPOSIT_OBLIGATION_NOT_FOUND')
        current = events[-1]['obligation']
        if obligation_id != current['obligation_id']: raise ValueError('DEPOSIT_OBLIGATION_NOT_FOUND')
        if type(expected_revision) is not int or expected_revision != current['revision'] or expected_source_hash != current['source_hash']:
            raise ValueError('DEPOSIT_SOURCE_VERSION_CONFLICT')
        if current['state'] != 'PROPOSED': raise ValueError('DEPOSIT_ACCEPTED_SOURCE_IMMUTABLE')
        if datetime.fromisoformat(current['source']['expires_at']) > now():
            raise ValueError('DEPOSIT_RENEWAL_NOT_DUE')
        if o.status not in {'CONFIRMED', 'IN_PROGRESS'}: raise ValueError('DEPOSIT_ORDER_NOT_ELIGIBLE')
        _check_source_current(o, current['source'])
        source = _source(o)
        result = {'obligation_id': obligation_id, 'revision': current['revision'] + 1,
                  'state': 'PROPOSED', 'source': source, 'source_hash': digest(source),
                  'consent': None, 'renewed_from_source_hash': current['source_hash'],
                  'financial_state': 'NO_FINANCIAL_FACT_ASSERTED'}
        return _append(s, o, p, key, request, result)


def _check_source_current(order, source):
    contract = source['contract_snapshot']
    if (order.account_id != source['owner_id'] or order.currency != source['currency']
            or order.vehicle_class != contract['vehicle_class']
            or order.deposit_minor != source['amount_minor'] or order.insurance != contract['insurance']):
        raise ValueError('DEPOSIT_ORDER_SOURCE_DRIFT')


def get_obligation(p, order_id):
    with transaction() as s:
        o = damage._order(s, p, order_id); events = _events(s, o)
        if not events: raise ValueError('DEPOSIT_OBLIGATION_NOT_FOUND')
        return events[-1]['obligation']


def resolve_obligation(session, order_id, obligation_id, expected_revision, expected_source_hash, *, allow_expired=False):
    isolated()
    o = _locked_order(session, order_id); events = _events(session, o)
    if not events: raise ValueError('DEPOSIT_OBLIGATION_NOT_FOUND')
    current = events[-1]['obligation']
    if obligation_id != current['obligation_id']: raise ValueError('DEPOSIT_OBLIGATION_NOT_FOUND')
    if type(expected_revision) is not int or expected_revision != current['revision'] or expected_source_hash != current['source_hash']:
        raise ValueError('DEPOSIT_SOURCE_VERSION_CONFLICT')
    if current['state'] != 'ACTIVATED': raise ValueError('DEPOSIT_CONSUMER_ACCEPTANCE_REQUIRED')
    source = current['source']; _check_source_current(o, source)
    if not allow_expired:
        if o.status not in {'CONFIRMED', 'IN_PROGRESS', 'COMPLETED'}:
            raise ValueError('DEPOSIT_ORDER_NOT_ELIGIBLE')
        _not_expired(source)
    # allow_expired is internal-only; C11 may use it solely to release an already
    # proven authorization. It cannot create/extend financial authorization.
    return {**deepcopy(source), 'obligation_id': obligation_id, 'revision': current['revision'],
            'source_hash': current['source_hash'], 'consent': deepcopy(current['consent']),
            'state': 'ACTIVATED', 'evidence_reference': 'c04-deposit-obligation://' + obligation_id}


def binding_for_case(session, order):
    events = _events(session, order)
    if not events: return None
    current = events[-1]['obligation']
    if current['state'] != 'ACTIVATED': return None
    # Opening a dispute is allowed after expiry; it does not move money.
    resolved = resolve_obligation(session, order.order_id, current['obligation_id'],
                                  current['revision'], current['source_hash'], allow_expired=True)
    return {key: resolved[key] for key in ('obligation_id', 'revision', 'source_hash', 'vehicle_id', 'owner_id', 'payee_id', 'currency')}


def _decision(session, order_id, obligation_id, case_id):
    o = _locked_order(session, order_id)
    case = damage._current(damage._history(session, order_id), case_id)
    binding = case.get('deposit_obligation')
    if not binding or binding['obligation_id'] != obligation_id: raise ValueError('DEPOSIT_CASE_UNBOUND')
    obligation = resolve_obligation(session, order_id, obligation_id, binding['revision'], binding['source_hash'], allow_expired=True)
    return _case_decision_fact(o, obligation, case)


def _case_decision_fact(o, obligation, case):
    """Preserve the v1 decision hash for current or immutable historical snapshots."""
    binding = case.get('deposit_obligation')
    if not binding or binding.get('obligation_id') != obligation['obligation_id']:
        raise ValueError('DEPOSIT_CASE_UNBOUND')
    if binding != {key: obligation[key] for key in binding}: raise ValueError('DEPOSIT_CASE_SOURCE_MISMATCH')
    if (case['status'] != 'ADJUDICATED' or case['money_instruction_state'] != 'AWAITING_C11_REVIEW'
            or case['actionable_award_minor'] is None): raise ValueError('DEPOSIT_DECISION_HELD')
    if (case['owner_id'] != o.account_id or case['currency'] != obligation['currency']
            or case['contract_snapshot']['deposit_minor'] != obligation['amount_minor']
            or case['contract_snapshot']['insurance'] != obligation['contract_snapshot']['insurance']):
        raise ValueError('DEPOSIT_CASE_SOURCE_MISMATCH')
    award = case['awarded_minor']
    if (type(award) is not int or not 0 <= award <= min(case['claimed_minor'], obligation['contract_snapshot']['maximum_damage_award_minor'])
            or case['actionable_award_minor'] != award): raise ValueError('DEPOSIT_DECISION_AMOUNT_INVALID')
    fact = {'case_id': case['case_id'], 'order_id': o.order_id, 'obligation_id': obligation['obligation_id'],
            'case_version': case['version'], 'awarded_minor': award, 'owner_id': o.account_id,
            'currency': obligation['currency'], 'source_hash': obligation['source_hash'],
            'obligation_revision': obligation['revision'], 'decision_history': case['decision_history'],
            'status': 'ADJUDICATED', 'held': False, 'data_mode': MODE, 'external_live': False}
    return {**fact, 'decision_hash': digest(fact)}


def decision_preview(p, order_id, obligation_id, case_id):
    isolated(); damage._admin(p)
    with transaction() as s:
        return _decision(s, order_id, obligation_id, case_id)


def resolve_decision(session, order_id, obligation_id, case_id, expected_case_version, expected_decision_hash):
    isolated()
    fact = _decision(session, order_id, obligation_id, case_id)
    if type(expected_case_version) is not int or fact['case_version'] != expected_case_version or fact['decision_hash'] != expected_decision_hash:
        raise ValueError('DEPOSIT_DECISION_VERSION_CONFLICT')
    return fact


def resolve_compensation(session, order_id, obligation_id, case_id, expected_case_version, expected_decision_hash):
    """Current independent reduction authority, never a computed money refund.

    C11 must prove which historical decision produced its actual capture and
    subtract all prior confirmed compensation before determining any difference.
    This resolver does not assert that a capture exists or that money was returned.
    """
    fact = resolve_decision(session, order_id, obligation_id, case_id,
                            expected_case_version, expected_decision_hash)
    events = [e for e in damage._history(session, order_id) if e['case']['case_id'] == case_id]
    return _compensation_fact(fact, events)


def _compensation_fact(fact, events, *, require_reduction=True):
    current = events[-1]['case']
    adjudications = [e for e in events if e['case']['status'] == 'ADJUDICATED']
    history = current['decision_history']
    if len(history) < 2: raise ValueError('DEPOSIT_COMPENSATION_APPEAL_REQUIRED')
    if len(adjudications) != len(history): raise ValueError('DEPOSIT_COMPENSATION_LINEAGE_INVALID')
    prior_facts, prior_reviewers, previous_version = [], set(), None
    for index, event in enumerate(adjudications):
        case = event['case']; decision = history[index]
        reviewer = decision.get('reviewer_id')
        if (case.get('deposit_obligation') != current['deposit_obligation']
                or case.get('owner_id') != current['owner_id'] or case.get('currency') != current['currency']
                or case.get('opened_by') != current['opened_by']
                or case.get('contract_snapshot') != current['contract_snapshot']
                or case.get('claimed_minor') != current['claimed_minor']
                or case.get('decision_history') != history[:index + 1]
                or case.get('version') != decision.get('version')
                or case.get('awarded_minor') != decision.get('award_minor')
                or case.get('actionable_award_minor') != decision.get('award_minor')
                or case.get('reviewer_id') != reviewer or event.get('actor_id') != reviewer
                or event.get('actor_type') != 'GO_ADMIN'
                or reviewer in prior_reviewers | {current['owner_id'], current['opened_by']}):
            raise ValueError('DEPOSIT_COMPENSATION_LINEAGE_INVALID')
        if index:
            appeals = case.get('appeals') or []
            if (decision.get('supersedes_decision_version') != previous_version or not appeals
                    or appeals[-1].get('decision_version') != previous_version
                    or appeals[-1].get('actor_id') != current['owner_id']):
                raise ValueError('DEPOSIT_COMPENSATION_LINEAGE_INVALID')
        historical = {k: deepcopy(v) for k, v in fact.items() if k != 'decision_hash'}
        historical.update(case_version=case['version'], awarded_minor=case['awarded_minor'],
                          decision_history=deepcopy(case['decision_history']))
        historical_hash = digest(historical)
        if index == len(history) - 1:
            if historical_hash != fact['decision_hash']: raise ValueError('DEPOSIT_COMPENSATION_LINEAGE_INVALID')
        else:
            prior_facts.append({'case_version': case['version'], 'decision_hash': historical_hash,
                                'awarded_minor': case['awarded_minor'], 'reviewer_id': reviewer})
        prior_reviewers.add(reviewer); previous_version = case['version']
    if fact['awarded_minor'] >= history[-2]['award_minor']:
        if not require_reduction: return None
        raise ValueError('DEPOSIT_COMPENSATION_REDUCTION_REQUIRED')
    return {**fact, 'prior_decisions': prior_facts, 'reviewer_id': history[-1]['reviewer_id'],
            'payee_id': current['deposit_obligation']['payee_id'],
            'vehicle_id': current['deposit_obligation']['vehicle_id'],
            'approval_evidence': deepcopy(history[-1]['evidence']),
            'authority_scope': 'REDUCE_ONLY', 'financial_effect_asserted': False}


def resolve_compensation_history(session, order_id, obligation_id):
    """Read historical reduction authority for receipts, never authorize new money.

    A later pending appeal or upward decision does not erase the authority that
    justified an earlier booked compensation. New executions MUST use the latest
    resolve_compensation gate instead of this immutable-history view.
    """
    isolated()
    order = _locked_order(session, order_id)
    events = damage._history(session, order_id)
    per_case, reductions = {}, []
    for event in events:
        case = event['case']; cid = case['case_id']
        per_case.setdefault(cid, []).append(event)
        if case['status'] != 'ADJUDICATED': continue
        binding = case.get('deposit_obligation')
        if not binding or binding.get('obligation_id') != obligation_id: continue
        source = resolve_obligation(session, order_id, obligation_id,
                                    binding['revision'], binding['source_hash'], allow_expired=True)
        fact = _case_decision_fact(order, source, case)
        if len(case['decision_history']) < 2: continue
        reduction = _compensation_fact(fact, per_case[cid], require_reduction=False)
        if reduction is not None: reductions.append(reduction)
    return reductions


def compensation_preview(p, order_id, obligation_id, case_id):
    isolated(); damage._admin(p)
    with transaction() as s:
        fact = _decision(s, order_id, obligation_id, case_id)
        return resolve_compensation(s, order_id, obligation_id, case_id,
                                    fact['case_version'], fact['decision_hash'])


RELEASE_KIND = 'RENTAL_DEPOSIT_RELEASE'


def _release_id(order_id):
    return 'rdep_release_' + digest(order_id)[:40]


def _release_event(session, order):
    damage._history(session, order.order_id)
    rows = list(session.scalars(select(EvidenceRow).where(
        EvidenceRow.execution_id == f'rc20:RENTAL:{order.order_id}',
        EvidenceRow.evidence_kind == RELEASE_KIND)))
    if not rows: return None
    if len(rows) != 1 or rows[0].evidence_chain_id != _release_id(order.order_id):
        raise ValueError('DEPOSIT_RELEASE_INTEGRITY_INVALID')
    event = rows[0].evidence_json['payload']; fact = event.get('release', {})
    claimed_hash = fact.get('release_hash')
    if (fact.get('order_id') != order.order_id or fact.get('owner_id') != order.account_id
            or fact.get('release_revision') != 1
            or digest({k: v for k, v in fact.items() if k != 'release_hash'}) != claimed_hash):
        raise ValueError('DEPOSIT_RELEASE_INTEGRITY_INVALID')
    return event


def assert_case_open_allowed(session, order):
    if _release_event(session, order): raise ValueError('DEPOSIT_RETURN_FINALIZED')


def _release_reason(session, order):
    if damage._history(session, order.order_id): raise ValueError('DEPOSIT_DAMAGE_CASE_REQUIRES_SETTLEMENT')
    if order.status == 'COMPLETED': return 'NO_DAMAGE_RETURN'
    if order.status == 'REFUNDED':
        from go_hotel.db.models import MobilityRefundRow
        from go_hotel.mobility.rental.reconciliation import inspect_refund
        refund = session.scalar(select(MobilityRefundRow).where(
            MobilityRefundRow.vertical == 'RENTAL', MobilityRefundRow.order_id == order.order_id))
        if refund and inspect_refund(order.account_id, order.order_id, refund.refund_id)['status'] == 'MATCHED_COMPLETED':
            return 'CANCELLED_REFUNDED'
    raise ValueError('DEPOSIT_RETURN_OR_PROVEN_CANCELLATION_REQUIRED')


def close_return(p, order_id, obligation_id, key, expected_revision, expected_source_hash, evidence):
    """Explicit isolated admin final inspection; no money release is asserted."""
    isolated(); damage._admin(p)
    submitted = damage._evidence(evidence)
    if not isinstance(key, str) or not key.strip() or len(key) > 128:
        raise ValueError('DEPOSIT_IDEMPOTENCY_KEY_INVALID')
    request = ['CLOSE_RETURN', obligation_id, expected_revision, expected_source_hash, submitted]
    with transaction() as s:
        order = _locked_order(s, order_id)
        if p.user_id == order.account_id: raise PermissionError('DEPOSIT_INDEPENDENT_RETURN_REVIEW_REQUIRED')
        event = _release_event(s, order)
        if event:
            if event['actor_id'] == p.user_id and event['key'] == key:
                if event['request_hash'] != digest(request): raise ValueError('DEPOSIT_IDEMPOTENCY_CONFLICT')
                return deepcopy(event['release'])
            raise ValueError('DEPOSIT_RETURN_ALREADY_FINALIZED')
        obligation = resolve_obligation(s, order_id, obligation_id, expected_revision, expected_source_hash, allow_expired=True)
        reason = _release_reason(s, order)
        fact = {'release_revision': 1, 'order_id': order_id, 'obligation_id': obligation_id,
                'owner_id': order.account_id, 'payee_id': obligation['payee_id'],
                'source_hash': expected_source_hash, 'obligation_revision': expected_revision,
                'currency': obligation['currency'], 'reason': reason, 'reviewer_id': p.user_id,
                'evidence': submitted, 'evidence_status': 'ADMIN_CONFIRMED_ISOLATED_FIXTURE',
                'state': 'RELEASE_APPROVED', 'held': False, 'data_mode': MODE, 'external_live': False,
                'financial_state': 'NO_FINANCIAL_FACT_ASSERTED'}
        fact['release_hash'] = digest(fact)
        row = append_vertical_evidence(s, 'RENTAL', order_id, RELEASE_KIND, order.status,
            {'actor_id': p.user_id, 'key': key, 'request_hash': digest(request), 'release': fact},
            source='C04_DEPOSIT_AUTHORITY')
        row.evidence_chain_id = _release_id(order_id); s.flush()
        return fact


def resolve_release(session, order_id, obligation_id, expected_release_revision, expected_release_hash):
    isolated()
    order = _locked_order(session, order_id); event = _release_event(session, order)
    if not event: raise ValueError('DEPOSIT_RELEASE_FACT_REQUIRED')
    fact = event['release']
    if (obligation_id != fact['obligation_id'] or type(expected_release_revision) is not int
            or expected_release_revision != fact['release_revision'] or expected_release_hash != fact['release_hash']):
        raise ValueError('DEPOSIT_RELEASE_VERSION_CONFLICT')
    obligation = resolve_obligation(session, order_id, obligation_id, fact['obligation_revision'], fact['source_hash'], allow_expired=True)
    if (_release_reason(session, order) != fact['reason'] or fact['payee_id'] != obligation['payee_id']
            or fact['currency'] != obligation['currency']):
        raise ValueError('DEPOSIT_RELEASE_SOURCE_MISMATCH')
    return deepcopy(fact)


def release_preview(p, order_id, obligation_id):
    isolated(); damage._admin(p)
    with transaction() as s:
        order = _locked_order(s, order_id); event = _release_event(s, order)
        if not event: raise ValueError('DEPOSIT_RELEASE_FACT_REQUIRED')
        fact = event['release']
        return resolve_release(s, order_id, obligation_id, fact['release_revision'], fact['release_hash'])
