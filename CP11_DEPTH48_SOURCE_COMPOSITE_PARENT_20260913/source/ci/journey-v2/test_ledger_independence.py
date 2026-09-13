"""Synthetic auditor mutation tests, NOT application or browser acceptance."""
import contextlib
import importlib.util
import io
import json
import pathlib
import sqlite3
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('audit_ledger', pathlib.Path(__file__).with_name('ledger.py'))
ledger = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ledger)


class LedgerIndependence(unittest.TestCase):
    def fixture(self, root):
        db = sqlite3.connect(root / 'acceptance.db')
        def add(table, row):
            db.execute('CREATE TABLE IF NOT EXISTS '+table+' ('+', '.join(row)+')')
            db.execute('INSERT INTO '+table+' VALUES ('+','.join('?' for _ in row)+')', tuple(row.values()))
        checks = []
        for v, (ot, rt, amount) in ledger.TABLES.items():
            oid, iid, sid = v+'_order', v+'_intent', v+'_source'
            order=dict(order_id=oid, status='REFUND_COMPLETED', account_id='owner', currency='CNY', total_amount_minor=100)
            if v=='HOTEL': order['supplier_id']='supplier'
            add(ot, order)
            add('payment_order_root', dict(business_type=v+'_ORDER', business_id=oid, payment_intent_id=iid))
            payment=dict(payment_intent_id=iid, business_type=v+'_ORDER', business_id=oid, payer_id='owner', payee_id='supplier', currency='CNY', amount_minor=100)
            add('omnichannel_payment_intent', dict(payment, state='SUCCEEDED'))
            add('payment_order_fact_binding', dict(payment, source_decision_id=sid, evidence_reference='isolated-fact'))
            add('vertical_source_decision', dict(vertical_source_decision_id=sid, vertical=v, business_id=oid, selected_source_id='supplier', evidence_reference='isolated-source'))
            for kind, parent in [('AUTHORIZATION',None), ('CAPTURE',iid+'AUTHORIZATION'), ('REFUND',iid+'CAPTURE')]:
                mid=iid+kind
                add('omnichannel_money_movement', dict(root_payment_intent_id=iid, business_type=v+'_ORDER', business_id=oid, state='CONFIRMED', currency='CNY', movement_type=kind, money_movement_id=mid, parent_movement_id=parent, amount_minor=100))
                if kind!='AUTHORIZATION':
                    for direction in ['DEBIT','CREDIT']:
                        add('omnichannel_ledger_entry', dict(payment_intent_id=iid, transaction_id=mid, direction=direction, amount_minor=100, currency='CNY', entry_type=kind))
            add(rt, dict(order_id=oid, vertical=v, status='REFUND_COMPLETED', currency='CNY', **{amount:100}))
            add('omnichannel_payment_attempt', dict(payment_intent_id=iid, external_invoked=0))
            checks.append(dict(vertical=v, order_id=oid, quoted_refund_minor=100, final=dict(order=dict(status='REFUND_COMPLETED'), original_payment=dict(captured_minor=100, refunded_minor=100, net_minor=0))))
        db.commit()
        (root/'runtime-binding.json').write_text(json.dumps(dict(source_tree_sha256='synthetic-only')))
        (root/'browser-results.json').write_text(json.dumps(dict(commit='synthetic-fixture', source_tree_sha256='synthetic-only', order_checks=checks)))
        return db

    def run_case(self, mutate=None):
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory)
            db=self.fixture(root)
            if mutate:
                mutate(db)
                db.commit()
            db.close()
            before=(root/'acceptance.db').read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                if mutate:
                    with self.assertRaises(AssertionError): ledger.audit(root,root)
                else: ledger.audit(root,root)
            self.assertEqual(before,(root/'acceptance.db').read_bytes())
            result=json.loads((root/'independent-ledger-audit.json').read_text())
            self.assertEqual(result['result'],'HOLD' if mutate else 'PASS')

    def test_valid_six_vertical_fixture(self):
        self.run_case()

    def test_jointly_wrong_payee_rejected_for_every_vertical(self):
        for v in ledger.TABLES:
            with self.subTest(vertical=v):
                def mutate(db):
                    for table in ['omnichannel_payment_intent','payment_order_fact_binding']:
                        db.execute('UPDATE '+table+' SET payee_id=? WHERE business_id=?',('wrong',v+'_order'))
                self.run_case(mutate)

    def test_self_consistent_money_cannot_override_order_price(self):
        for v,(ot,_,_) in ledger.TABLES.items():
            with self.subTest(vertical=v):
                self.run_case(lambda db: db.execute('UPDATE '+ot+' SET total_amount_minor=200 WHERE order_id=?',(v+'_order',)))

    def test_source_from_other_order_rejected(self):
        self.run_case(lambda db: db.execute("UPDATE vertical_source_decision SET business_id='other' WHERE vertical='FLIGHT'"))

    def test_missing_source_evidence_rejected(self):
        self.run_case(lambda db: db.execute("UPDATE vertical_source_decision SET evidence_reference='' WHERE vertical='RAIL'"))

    def test_wrong_movement_vertical_rejected(self):
        self.run_case(lambda db: db.execute("UPDATE omnichannel_money_movement SET business_type='RAIL_ORDER' WHERE business_id='FLIGHT_order'"))

    def test_intent_currency_mismatch_rejected(self):
        self.run_case(lambda db: db.execute("UPDATE omnichannel_payment_intent SET currency='USD' WHERE business_id='RIDE_order'"))


if __name__=='__main__': unittest.main()
