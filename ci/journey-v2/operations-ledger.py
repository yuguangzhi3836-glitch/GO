"""Independent read-only SQL audit of isolated operations browser transactions.

No product projection helpers, credentials, full DB export or real PSP claims.
The original six-domain and hotel audits remain separate and unchanged.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    default=str, separators=(',', ':')).encode()).hexdigest()


def audit(state, evidence):
    browser = json.loads((evidence / 'browser-results.json').read_text())
    runtime = json.loads((state / 'runtime-binding.json').read_text())
    report = browser['operations']
    result = {'schema': 'go.operations-sql-audit.v1', 'commit': browser['commit'],
              'source_tree_sha256': browser['source_tree_sha256'],
              'mode': 'SYNTHETIC_READ_ONLY_SQL', 'real_psp': False,
              'result': 'HOLD', 'orders': []}
    db = sqlite3.connect((state / 'acceptance.db').resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    def rows(sql, *args):
        return [dict(r) for r in db.execute(sql, args)]
    def one(sql, *args):
        found = rows(sql, *args)
        assert len(found) == 1, ('EXPECTED_ONE_ROW', len(found))
        return found[0]
    try:
        assert browser['source_tree_sha256'] == runtime['source_tree_sha256']
        assert report['complete'] is True
        checks = report['rentals']
        assert len(checks) == 2 and {c['flow'] for c in checks} == {'DISPUTE_APPEAL_SETTLE', 'NO_DAMAGE_RELEASE'}
        assert len({c['order_id'] for c in checks}) == 2
        assert not {c['order_id'] for c in checks} & {c['order_id'] for c in browser['order_checks']}
        for check in checks:
            oid, obligation_id = check['order_id'], check['obligation_id']
            order = one('SELECT * FROM mobility_rental_order_runtime WHERE order_id=?', oid)
            assert order['status'] == 'COMPLETED'
            root = one('SELECT * FROM payment_order_root WHERE business_type=? AND business_id=?', 'RENTAL_DEPOSIT', obligation_id)
            iid = root['payment_intent_id']
            intent = one('SELECT * FROM omnichannel_payment_intent WHERE payment_intent_id=?', iid)
            fact = one('SELECT * FROM payment_order_fact_binding WHERE payment_intent_id=?', iid)
            assert (intent['business_type'], intent['business_id'], intent['payer_id'], intent['currency'], intent['state']) == ('RENTAL_DEPOSIT', obligation_id, order['account_id'], 'CNY', 'SUCCEEDED')
            assert intent['amount_minor'] == order['deposit_minor']
            for field in ['business_type', 'business_id', 'payer_id', 'payee_id', 'currency', 'amount_minor']:
                assert fact[field] == intent[field], ('FACT_MISMATCH', field)
            movements = rows('SELECT * FROM omnichannel_money_movement WHERE root_payment_intent_id=?', iid)
            assert len({m['money_movement_id'] for m in movements}) == len(movements)
            assert all((m['business_type'], m['business_id'], m['currency'], m['state']) == ('RENTAL_DEPOSIT', obligation_id, 'CNY', 'CONFIRMED') for m in movements)
            groups = {kind: [m for m in movements if m['movement_type'] == kind] for kind in ['AUTHORIZATION', 'CAPTURE', 'RELEASE']}
            expected_capture = 5000 if check['flow'] == 'DISPUTE_APPEAL_SETTLE' else 0
            assert len(groups['AUTHORIZATION']) == len(groups['RELEASE']) == 1
            assert len(groups['CAPTURE']) == (1 if expected_capture else 0)
            assert len(movements) == (3 if expected_capture else 2), 'NO_DUPLICATE_OR_UNKNOWN_MOVEMENTS'
            auth = groups['AUTHORIZATION'][0]
            assert auth['amount_minor'] == intent['amount_minor'] and auth['parent_movement_id'] is None
            assert all(m['parent_movement_id'] == auth['money_movement_id'] for m in groups['CAPTURE'] + groups['RELEASE'])
            captured = sum(m['amount_minor'] for m in groups['CAPTURE'])
            released = groups['RELEASE'][0]['amount_minor']
            assert captured == expected_capture and released > 0 and captured + released == auth['amount_minor']
            ledger = rows('SELECT * FROM omnichannel_ledger_entry WHERE payment_intent_id=?', iid)
            assert len(ledger) == (2 if expected_capture else 0)
            for cap in groups['CAPTURE']:
                assert {l['direction'] for l in ledger} == {'DEBIT', 'CREDIT'}
                assert all(l['transaction_id'] == cap['money_movement_id'] and l['amount_minor'] == captured and l['currency'] == 'CNY' and l['entry_type'] == 'CAPTURE' for l in ledger)
            observed = check['financial']['money']
            assert (observed['payment_intent_id'], observed['authorized_minor'], observed['captured_minor'], observed['released_minor'], observed['remaining_minor'], observed['state']) == (iid, auth['amount_minor'], captured, released, 0, 'SETTLED')
            chain = rows('SELECT * FROM journey_recovery_evidence_chain WHERE execution_id=? ORDER BY sequence_no', 'rc20:RENTAL:' + oid)
            previous, cases, obligations = 'GENESIS', [], []
            for seq, row in enumerate(chain, 1):
                body = json.loads(row['evidence_json'])
                assert row['sequence_no'] == body['sequence_no'] == seq
                assert row['previous_hash'] == body['previous_hash'] == previous
                assert row['execution_item_id'] == body['order_id'] == oid
                assert body['vertical'] == 'RENTAL' and body['kind'] == row['evidence_kind']
                assert digest(body) == row['evidence_hash']
                assert digest({'evidence_hash': row['evidence_hash'], 'previous_hash': previous, 'sequence_no': seq}) == row['entry_hash']
                previous = row['entry_hash']
                if row['evidence_kind'] == 'DAMAGE_CASE_EVENT': cases.append(body['payload'])
                if row['evidence_kind'] == 'RENTAL_DEPOSIT_OBLIGATION': obligations.append(body['payload']['obligation'])
            assert obligations and obligations[-1]['obligation_id'] == obligation_id and obligations[-1]['state'] == 'ACTIVATED'
            if expected_capture:
                assert len(cases) == 5, 'OPEN_RESPONSE_DECISION_APPEAL_REVIEW_REQUIRED'
                final = cases[-1]['case']
                assert final == check['workspace']['cases'][0]['case']
                assert final['status'] == 'ADJUDICATED' and final['awarded_minor'] == captured
                reviewers = [d['reviewer_id'] for d in final['decision_history']]
                assert len(reviewers) == len(set(reviewers)) == 2
                assert final['opened_by'] not in reviewers and final['owner_id'] not in reviewers
                assert len(final['appeals']) == 1
            else:
                assert not cases
                release_rows = [json.loads(r['evidence_json'])['payload'] for r in chain if r['evidence_kind'] == 'RENTAL_DEPOSIT_RELEASE']
                assert len(release_rows) == 1
            result['orders'].append({'order_id': oid, 'obligation_id': obligation_id, 'payment_intent_id': iid,
                'captured_minor': captured, 'released_minor': released, 'currency': 'CNY',
                'movement_count': len(movements), 'ledger_entries': len(ledger),
                'evidence_chain_entries': len(chain), 'result': 'PASS'})
        result['result'] = 'PASS'
    except Exception as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        db.close()
        (evidence / 'operations-ledger-audit.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({'operations_sql_audit': result['result'], 'orders': len(result['orders'])}))


if __name__ == '__main__':
    audit(Path(sys.argv[1]), Path(sys.argv[2]))
