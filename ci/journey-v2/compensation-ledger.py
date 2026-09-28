"""Read-only snapshots and independent SQL audit of isolated rental compensation.

Original movements and journal entries are saved before the real UI appeal and
compared byte-for-value after compensation. No application projection imports.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

BUSINESS = 'RENTAL_DEPOSIT'


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def connect(state):
    runtime = json.loads((state / 'runtime-binding.json').read_text())
    assert runtime['mode'] == 'ISOLATED_SQLITE_HTTP' and runtime['data_class'] == 'SYNTHETIC_ONLY'
    target = (state / 'acceptance.db').resolve()
    assert target.is_file() and target.parent == state.resolve() and not (state / 'acceptance.db').is_symlink()
    db = sqlite3.connect(target.as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    return db, runtime


def observe(db, oid, obligation):
    def rows(sql, *args):
        return [dict(r) for r in db.execute(sql, args)]
    def one(sql, *args):
        result = rows(sql, *args)
        assert len(result) == 1, ('EXPECTED_ONE', len(result))
        return result[0]
    order = one('SELECT order_id,account_id,currency,deposit_minor,status FROM mobility_rental_order_runtime WHERE order_id=?', oid)
    root = one('SELECT * FROM payment_order_root WHERE business_type=? AND business_id=?', BUSINESS, obligation)
    intent = one('SELECT * FROM omnichannel_payment_intent WHERE payment_intent_id=?', root['payment_intent_id'])
    fact = one('SELECT * FROM payment_order_fact_binding WHERE payment_intent_id=?', root['payment_intent_id'])
    assert order['status'] == 'COMPLETED'
    assert (intent['business_type'], intent['business_id'], intent['payer_id'], intent['currency'], intent['amount_minor'], intent['state']) == (BUSINESS, obligation, order['account_id'], 'CNY', order['deposit_minor'], 'SUCCEEDED')
    for key in ('business_type', 'business_id', 'payer_id', 'payee_id', 'amount_minor', 'currency'):
        assert fact[key] == intent[key], ('FACT_BINDING', key)
    movements = rows('SELECT * FROM omnichannel_money_movement WHERE root_payment_intent_id=? ORDER BY money_movement_id', root['payment_intent_id'])
    ledger = rows('SELECT * FROM omnichannel_ledger_entry WHERE payment_intent_id=? ORDER BY ledger_entry_id', root['payment_intent_id'])
    return {'order': order, 'root': root, 'intent': intent, 'fact': fact, 'movements': movements, 'ledger': ledger}


def journal_pair(rows, movement, reverse=False):
    pair = [r for r in rows if r['transaction_id'] == movement['money_movement_id']]
    assert len(pair) == 2 and {r['direction'] for r in pair} == {'DEBIT', 'CREDIT'}
    assert all(r['amount_minor'] == movement['amount_minor'] and r['currency'] == movement['currency'] and r['entry_type'] == movement['movement_type'] for r in pair)
    clearing = [r for r in pair if r['account_code'] == 'PAYMENT_CLEARING:LOCAL_MARKET']
    assert len(clearing) == 1 and clearing[0]['direction'] == ('CREDIT' if reverse else 'DEBIT')
    other = next(r for r in pair if r is not clearing[0])
    assert other['direction'] == ('DEBIT' if reverse else 'CREDIT')
    return other['account_code']


def snapshot(state, evidence, oid, obligation):
    db, runtime = connect(state)
    try:
        observed = observe(db, oid, obligation)
        kinds = {m['movement_type']: m for m in observed['movements']}
        assert len(observed['movements']) == len(kinds) == 3 and set(kinds) == {'AUTHORIZATION', 'CAPTURE', 'RELEASE'}
        assert kinds['CAPTURE']['amount_minor'] == 4000
        assert kinds['AUTHORIZATION']['amount_minor'] == kinds['CAPTURE']['amount_minor'] + kinds['RELEASE']['amount_minor']
        assert len(observed['ledger']) == 2
        journal_pair(observed['ledger'], kinds['CAPTURE'])
        dump(evidence / 'compensation-before-sql.json', {'schema': 'go.compensation-before-sql.v1',
            'source_tree_sha256': runtime['source_tree_sha256'], 'order_id': oid,
            'obligation_id': obligation, 'mode': 'READ_ONLY_SYNTHETIC_SQL', 'observed': observed})
    finally:
        db.close()


def audit(state, evidence):
    browser = json.loads((evidence / 'browser-results.json').read_text())
    before_path = evidence / 'compensation-before-sql.json'
    before = json.loads(before_path.read_text())
    result = {'schema': 'go.compensation-sql-audit.v1', 'commit': browser['commit'],
              'source_tree_sha256': browser['source_tree_sha256'], 'result': 'HOLD',
              'mode': 'READ_ONLY_SYNTHETIC_SQL', 'before_sha256': hashlib.sha256(before_path.read_bytes()).hexdigest()}
    db, runtime = connect(state)
    try:
        assert before['source_tree_sha256'] == browser['source_tree_sha256'] == runtime['source_tree_sha256']
        case = browser['compensation']
        assert case['complete'] is True and case['order_id'] == before['order_id'] and case['obligation_id'] == before['obligation_id']
        old = before['observed']; new = observe(db, case['order_id'], case['obligation_id'])
        for key in ('order', 'root', 'intent', 'fact'):
            assert new[key] == old[key], ('ORIGINAL_BINDING_CHANGED', key)
        assert len(old['movements']) == 3 and len(new['movements']) == 4
        for original in old['movements']:
            assert original in new['movements'], 'ORIGINAL_MONEY_CHANGED'
        for original in old['ledger']:
            assert original in new['ledger'], 'ORIGINAL_LEDGER_CHANGED'
        assert len(old['ledger']) == 2 and len(new['ledger']) == 4
        kinds = {m['movement_type']: m for m in new['movements']}
        assert len(kinds) == 4 and set(kinds) == {'AUTHORIZATION', 'CAPTURE', 'RELEASE', 'COMPENSATION'}
        auth, capture, release, compensation = (kinds[k] for k in ('AUTHORIZATION', 'CAPTURE', 'RELEASE', 'COMPENSATION'))
        assert all((m['business_type'], m['business_id'], m['currency'], m['state']) == (BUSINESS, case['obligation_id'], 'CNY', 'CONFIRMED') for m in new['movements'])
        assert capture['parent_movement_id'] == release['parent_movement_id'] == auth['money_movement_id']
        assert compensation['parent_movement_id'] == capture['money_movement_id']
        assert (capture['amount_minor'], compensation['amount_minor']) == (4000, 3000)
        assert auth['amount_minor'] == capture['amount_minor'] + release['amount_minor']
        assert journal_pair(new['ledger'], capture) == journal_pair(new['ledger'], compensation, reverse=True)
        net = capture['amount_minor'] - compensation['amount_minor']; assert net == 1000
        api = case['after']['money']
        assert (api['captured_minor'], api['compensated_minor'], api['net_captured_minor'], api['remaining_minor']) == (4000, 3000, 1000, 0)
        assert api['payment_intent_id'] == new['root']['payment_intent_id']
        events, previous = [], 'GENESIS'
        chain = db.execute('SELECT * FROM journey_recovery_evidence_chain WHERE execution_id=? ORDER BY sequence_no', ('rc20:RENTAL:' + case['order_id'],)).fetchall()
        stable = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        for sequence, row in enumerate(chain, 1):
            body = json.loads(row['evidence_json'])
            assert row['execution_item_id'] == body['order_id'] == case['order_id']
            assert row['sequence_no'] == body['sequence_no'] == sequence
            assert row['previous_hash'] == body['previous_hash'] == previous
            assert row['evidence_hash'] == stable(body)
            assert row['entry_hash'] == stable({'evidence_hash': row['evidence_hash'], 'previous_hash': previous, 'sequence_no': sequence})
            previous = row['entry_hash']
            if row['evidence_kind'] == 'DAMAGE_CASE_EVENT': events.append(body['payload'])
        assert len(events) == 5
        first, latest = events[2]['case'], events[-1]['case']
        assert first['status'] == latest['status'] == 'ADJUDICATED'
        assert first['awarded_minor'] == 4000 and latest['awarded_minor'] == 1000
        assert latest['version'] == 5 and len(latest['appeals']) == 1
        reviewers = [d['reviewer_id'] for d in latest['decision_history']]
        assert len(reviewers) == len(set(reviewers)) == 2
        assert latest['opened_by'] not in reviewers and latest['owner_id'] not in reviewers
        authority_hashes = []
        hashed = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        for decision in (first, latest):
            binding = decision['deposit_obligation']
            fact = {'case_id': decision['case_id'], 'order_id': case['order_id'], 'obligation_id': case['obligation_id'],
                    'case_version': decision['version'], 'awarded_minor': decision['awarded_minor'], 'owner_id': new['order']['account_id'],
                    'currency': 'CNY', 'source_hash': binding['source_hash'], 'obligation_revision': binding['revision'],
                    'decision_history': decision['decision_history'], 'status': 'ADJUDICATED', 'held': False,
                    'data_mode': 'ISOLATED_CONTRACT_FIXTURE', 'external_live': False}
            authority_hashes.append(hashed(fact))
        assert capture['idempotency_key'] == 'rental-deposit:' + hashed([case['obligation_id'], first['case_id'], first['version'], authority_hashes[0]]) + ':capture'
        assert compensation['idempotency_key'] == 'rental-deposit-comp:' + hashed([case['obligation_id'], latest['case_id'], latest['version'], authority_hashes[1]])
        assert 'rental-appeal-compensation://' + latest['case_id'] + '/' + authority_hashes[1] in json.loads(compensation['evidence_json'])
        for entry in new['ledger']:
            assert entry['evidence_hash'] == hashed({'movement': entry['transaction_id']})
        result.update(result='PASS', order_id=case['order_id'], obligation_id=case['obligation_id'],
                      original_records_unchanged=True, movement_count=4, ledger_entries=4,
                      capture_minor=4000, compensated_minor=3000, net_minor=net,
                      compensation_parent=capture['money_movement_id'], decision_version=latest['version'])
    except Exception as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        db.close(); dump(evidence / 'compensation-ledger-audit.json', result)
        print(json.dumps({'compensation_sql_audit': result['result']}))


if __name__ == '__main__':
    mode, state, evidence = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    if mode == 'snapshot': snapshot(state, evidence, sys.argv[4], sys.argv[5])
    elif mode == 'audit': audit(state, evidence)
    else: raise ValueError('UNSUPPORTED_READ_ONLY_MODE')
