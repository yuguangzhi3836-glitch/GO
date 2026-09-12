"""Read-only, independent SQL audit of the recorded hotel adjustment journey.

This extends evidence for one exercised hotel case, not all verticals or banks.
No application projection or money service is imported.
"""
import json
import pathlib
import sqlite3
import sys


def audit_order(db, check):
    def rows(sql, *args):
        return [dict(x) for x in db.execute(sql, args)]

    def one(sql, *args):
        found = rows(sql, *args)
        assert len(found) == 1, (sql, len(found))
        return found[0]

    assert check['complete'] and check['refund_replay'] == 'NO_DUPLICATE'
    oid = check['order_id']
    order = one('SELECT * FROM hotel_order_runtime WHERE order_id=?', oid)
    assert order['status'] == check['final']['order']['status'] == 'CANCELLED'
    operations = rows('SELECT * FROM catalog_cash_fare_operation WHERE order_id=?', oid)
    assert len(operations) == 3 and all(x['state'] == 'COMPLETED' for x in operations)
    # Completed cancellation deliberately retains its claim so the fee remainder
    # cannot be refunded again through another path.
    claim = one('SELECT * FROM catalog_cash_fare_claim WHERE order_id=?', oid)
    cancelled = [x for x in operations if json.loads(x['plan_json'])['quote']['action'] == 'CANCEL']
    assert len(cancelled) == 1 and claim['operation_id'] == cancelled[0]['operation_id']
    changes = rows('SELECT * FROM order_change_runtime WHERE order_id=? ORDER BY created_at', oid)
    assert len(changes) == 2 and all(x['status'] == 'CONFIRMED' for x in changes)
    assert len(check['change_quotes']) == 2
    for change, quote in zip(changes, check['change_quotes']):
        assert change['quote_id'] == quote['quote_id']
        assert (change['new_check_in'], change['new_check_out'], change['additional_payment_minor']) == (
            quote['new_check_in'], quote['new_check_out'], quote['amount_due_minor'])
    roots = rows('''SELECT * FROM payment_order_root WHERE
        (business_type='HOTEL_ORDER' AND business_id=?) OR
        (business_type='HOTEL_CHANGE' AND business_id IN
            (SELECT quote_id FROM change_quote WHERE order_id=?))''', oid, oid)
    assert len(roots) == 3
    assert sum(x['business_type'] == 'HOTEL_ORDER' for x in roots) == 1
    expected = {x['quote_id']: x['amount_due_minor'] for x in check['change_quotes']}
    expected[oid] = check['original_capture_minor']
    captures, refunds, proof = [], [], []
    for root in roots:
        iid = root['payment_intent_id']
        intent = one('SELECT * FROM omnichannel_payment_intent WHERE payment_intent_id=?', iid)
        fact = one('SELECT * FROM payment_order_fact_binding WHERE payment_intent_id=?', iid)
        assert (intent['business_type'], intent['business_id'], intent['state']) == (
            root['business_type'], root['business_id'], 'SUCCEEDED')
        assert (fact['business_type'], fact['business_id']) == (root['business_type'], root['business_id'])
        for item in (intent, fact):
            assert item['payer_id'] == order['account_id']
            assert item['payee_id'] == order['supplier_id']
            assert item['currency'] == order['currency']
            assert item['amount_minor'] == expected[root['business_id']]
        movements = rows('SELECT * FROM omnichannel_money_movement WHERE root_payment_intent_id=?', iid)
        groups = {kind: [x for x in movements if x['movement_type'] == kind]
                  for kind in ('AUTHORIZATION', 'CAPTURE', 'REFUND')}
        assert len(movements) == 3 and all(len(x) == 1 for x in groups.values())
        auth, cap, refund = (groups[k][0] for k in ('AUTHORIZATION', 'CAPTURE', 'REFUND'))
        assert cap['parent_movement_id'] == auth['money_movement_id']
        assert refund['parent_movement_id'] == cap['money_movement_id']
        for move in movements:
            assert (move['state'], move['currency'], move['business_type'], move['business_id']) == (
                'CONFIRMED', order['currency'], root['business_type'], root['business_id'])
            assert move['amount_minor'] == expected[root['business_id']]
        entries = rows('SELECT * FROM omnichannel_ledger_entry WHERE payment_intent_id=?', iid)
        assert len(entries) == 4
        for move in (cap, refund):
            pair = [x for x in entries if x['transaction_id'] == move['money_movement_id']]
            assert len(pair) == 2 and {x['direction'] for x in pair} == {'DEBIT', 'CREDIT'}
            assert all((x['amount_minor'], x['currency'], x['entry_type']) ==
                       (move['amount_minor'], move['currency'], move['movement_type']) for x in pair)
        assert not any(x['external_invoked'] for x in rows(
            'SELECT external_invoked FROM omnichannel_payment_attempt WHERE payment_intent_id=?', iid))
        captures.append(cap); refunds.append(refund)
        proof.append({'business_type': root['business_type'], 'business_id': root['business_id'],
                      'payment_intent_id': iid, 'capture_id': cap['money_movement_id'],
                      'refund_parent_id': refund['parent_movement_id'], 'amount_minor': cap['amount_minor'],
                      'currency': order['currency'], 'ledger_pairs': 2, 'result': 'PASS'})
    gross = sum(x['amount_minor'] for x in captures)
    returned = sum(x['amount_minor'] for x in refunds)
    assert gross == returned == check['cancel_quote']['refund_amount_minor']
    cash = check['final']['cash_after_sales']
    assert (cash['gross_paid_minor'], cash['refunded_minor'], cash['net_paid_minor']) == (gross, returned, 0)
    assert (cash['check_in'], cash['check_out']) == (changes[-1]['new_check_in'], changes[-1]['new_check_out'])
    original = one('SELECT * FROM refund_runtime WHERE order_id=?', oid)
    assert original['status'] == 'COMPLETED'
    assert original['amount_minor'] == check['original_capture_minor']
    assert original['currency'] == order['currency']
    assert original['provider_refund_id'] in {x['money_movement_id'] for x in refunds
                                            if x['business_type'] == 'HOTEL_ORDER'}
    assert check['final']['original_payment']['refunded_minor'] == original['amount_minor']
    return {'order_id': oid, 'result': 'PASS', 'payment_roots': proof,
            'capture_count': len(captures), 'refund_count': len(refunds),
            'gross_paid_minor': gross, 'refunded_minor': returned, 'net_paid_minor': 0,
            'confirmed_changes': len(changes), 'cash_operations': len(operations)}


def audit(state, evidence):
    browser = json.loads((evidence / 'browser-results.json').read_text())
    binding = json.loads((state / 'runtime-binding.json').read_text())
    result = {'schema': 'go.hotel-adjustment-ledger.v1', 'result': 'HOLD', 'orders': [],
              'commit': browser['commit'], 'source_tree_sha256': browser['source_tree_sha256'],
              'scope': 'ONE_HOTEL_ORIGINAL_PLUS_TWO_CHANGE_ROOTS',
              'mode': 'SYNTHETIC_READ_ONLY_SQL', 'bank_settlement_verified': False}
    db = None
    try:
        assert browser['source_tree_sha256'] == binding['source_tree_sha256']
        assert browser['depth44']['complete'] and len(browser['cash_journeys']) == 1
        db = sqlite3.connect((state / 'acceptance.db').resolve().as_uri() + '?mode=ro', uri=True)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        for check in browser['cash_journeys']:
            result['orders'].append(audit_order(db, check))
        result['result'] = 'PASS'
    except Exception as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        if db is not None:
            db.close()
        (evidence / 'hotel-change-ledger-audit.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({'hotel_change_ledger': result['result'], 'orders': len(result['orders'])}))


if __name__ == '__main__':
    audit(pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]))
