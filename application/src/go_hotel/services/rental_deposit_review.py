"""Read-only administrator review of C04 source and existing C11 money facts."""
from sqlalchemy import select
from go_hotel.db.models import MobilityRentalOrderRow as Order, PaymentOrderRootRow as Root
from go_hotel.db.models import OmnichannelPaymentIntentRow as Intent, OmnichannelMoneyMovementRow as Movement
from go_hotel.mobility.rental import damage, deposit_authority as authority
from go_hotel.mobility.rental.changes import transaction
from go_hotel.services import rental_deposit_money as money


def review(principal, order_id):
    money._admin(principal)
    with transaction() as session:
        order = session.get(Order, order_id, with_for_update=True)
        if not order:
            raise ValueError('MOBILITY_ORDER_NOT_FOUND')
        result = {'order_id': order_id, 'order_status': order.status, 'read_only': True,
            'data_mode': 'ISOLATED_CONTRACT_FIXTURE', 'external_live': False,
            'source': None, 'money': None, 'movements': [], 'decisions': [], 'release': None,
            'can_authorize': False, 'blockers': []}
        try:
            events = authority._events(session, order)
            if not events:
                result['blockers'].append('DEPOSIT_OBLIGATION_NOT_FOUND')
                return result
            obligation = events[-1]['obligation']
            result['source'] = {key: obligation[key] for key in ('obligation_id', 'revision', 'source_hash', 'state')}
            result['source'].update(currency=obligation['source']['currency'], amount_minor=obligation['source']['amount_minor'],
                expires_at=obligation['source']['expires_at'], consent=obligation.get('consent'))
            if obligation['state'] != 'ACTIVATED':
                result['blockers'].append('DEPOSIT_CONSUMER_ACCEPTANCE_REQUIRED')
                return result
            source = authority.resolve_obligation(session, order_id, obligation['obligation_id'],
                obligation['revision'], obligation['source_hash'], allow_expired=True)
        except ValueError as error:
            result['blockers'].append(str(error))
            return result
        expired = False
        try:
            authority._not_expired(source)
        except ValueError as error:
            expired = True
            result['blockers'].append(str(error))
        root = session.scalar(select(Root).where(Root.business_type == money.BUSINESS,
            Root.business_id == source['obligation_id']))
        observed = list(session.scalars(select(Movement).where(Movement.business_type == money.BUSINESS,
            Movement.business_id == source['obligation_id']).order_by(Movement.created_at, Movement.money_movement_id)))
        result['movements'] = [{'movement_id': row.money_movement_id, 'type': row.movement_type, 'state': row.state,
            'recorded_amount_minor': row.amount_minor, 'currency': row.currency,
            'operation_key': row.idempotency_key, 'parent_movement_id': row.parent_movement_id} for row in observed]
        result['money'] = {'state': 'NOT_AUTHORIZED', 'currency': source['currency'], 'authorized_minor': 0,
            'captured_minor': 0, 'released_minor': 0, 'compensated_minor': 0, 'net_captured_minor': 0, 'remaining_minor': 0, 'movement_ids': []}
        try:
            if root:
                intent, _ = money._root(session, source)
                _, rows = money._graph(session, intent, source)
                result['money'] = money._result(intent, rows)
            elif observed or session.scalar(select(Intent).where(Intent.business_type == money.BUSINESS,
                    Intent.business_id == source['obligation_id'])):
                raise ValueError('RENTAL_DEPOSIT_UNBOUND_INTENT_REQUIRES_REVIEW')
        except ValueError as error:
            result['blockers'].append(str(error))
            result['money'] = {'state': 'RECONCILIATION_REQUIRED', 'currency': source['currency'],
                'authorized_minor': None, 'captured_minor': None, 'released_minor': None, 'compensated_minor': None, 'net_captured_minor': None, 'remaining_minor': None,
                'movement_ids': []}
        state = result['money']['state']
        result['can_authorize'] = state == 'NOT_AUTHORIZED' and not expired and order.status in {'CONFIRMED', 'IN_PROGRESS'}
        # The latest C04 case, never a caller-supplied award, supplies settlement.
        cases = {}
        for event in damage._history(session, order_id):
            cases[event['case']['case_id']] = event['case']
        for case_id, case in cases.items():
            item = {'case_id': case_id, 'case_version': case['version'], 'case_status': case['status'],
                    'can_settle': False, 'decision': None, 'blocker': None}
            try:
                decision = authority._decision(session, order_id, source['obligation_id'], case_id)
                item['decision'] = decision
                item['can_settle'] = state == 'AUTHORIZED' and (not expired or decision['awarded_minor'] == 0)
                if state == 'SETTLED': item['blocker'] = 'SETTLED_MONEY_REQUIRES_SEPARATE_COMPENSATION_REVIEW'
            except ValueError as error:
                item['blocker'] = str(error)
            if state == 'SETTLED':
                try:
                    adjustment = authority.resolve_compensation(session, order_id, source['obligation_id'],
                        case_id, case['version'], item['decision']['decision_hash'] if item['decision'] else '')
                    _, _, _, plan = money._compensation_plan(session, source, adjustment)
                    item['compensation'] = plan
                    item['can_compensate'] = plan['amount_minor'] > 0
                    item['blocker'] = None
                except ValueError as error:
                    item['compensation_blocker'] = str(error)
            result['decisions'].append(item)
        event = authority._release_event(session, order)
        if event:
            fact = event['release']
            try:
                closure = authority.resolve_release(session, order_id, source['obligation_id'], fact['release_revision'], fact['release_hash'])
                result['release'] = {'fact': closure, 'can_release': state == 'AUTHORIZED'
                    and result['money']['captured_minor'] == 0 and result['money']['released_minor'] == 0}
            except ValueError as error:
                result['blockers'].append(str(error))
        return result
