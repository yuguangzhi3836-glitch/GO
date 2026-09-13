"""Independently audit the disposable SQLite ledger, using only read-only SQL.

Do not use application projection functions: matching three API views alone
does not prove the money records are complete or correctly paired.
"""
import hashlib, json, pathlib, sqlite3, sys

TABLES = {
    'HOTEL': ('hotel_order_runtime','refund_runtime','amount_minor'),
    'FLIGHT': ('flight_order_runtime','flight_refund_runtime','refund_amount_minor'),
    'RAIL': ('rail_order_runtime','rail_refund_runtime','refund_amount_minor'),
    'RIDE': ('mobility_ride_order_runtime','mobility_refund_runtime','refund_amount_minor'),
    'RENTAL': ('mobility_rental_order_runtime','mobility_refund_runtime','refund_amount_minor'),
    'ATTRACTION': ('attraction_order_runtime','attraction_refund_runtime','refund_amount_minor'),
}


def audit(state, evidence, report_name="browser-results.json"):
    report=json.loads((evidence/report_name).read_text())
    binding=json.loads((state/'runtime-binding.json').read_text())
    assert report['source_tree_sha256']==binding['source_tree_sha256']
    result={'schema':'go.independent-sqlite-ledger.v1','commit':report['commit'],
            'source_tree_sha256':binding['source_tree_sha256'],'mode':'SYNTHETIC_READ_ONLY_SQL',
            'input_report':report_name,'bank_settlement_verified':False,'orders':[],'result':'HOLD'}
    db=sqlite3.connect((state/'acceptance.db').resolve().as_uri()+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    def rows(sql,*args): return [dict(x) for x in db.execute(sql,args)]
    def one(sql,*args):
        found=rows(sql,*args);assert len(found)==1,(sql,len(found));return found[0]
    try:
        checks=report['order_checks']
        assert len(checks)==6 and {x['vertical'] for x in checks}==set(TABLES)
        assert len({x['order_id'] for x in checks})==6
        for check in checks:
            v,oid=check['vertical'],check['order_id'];ot,rt,amount=TABLES[v]
            # Table identifiers come exclusively from the constant allowlist.
            order=one(f'SELECT * FROM {ot} WHERE order_id=?',oid)
            assert order['status']==check['final']['order']['status']
            root=one('SELECT * FROM payment_order_root WHERE business_type=? AND business_id=?',v+'_ORDER',oid)
            iid=root['payment_intent_id']
            intent=one('SELECT * FROM omnichannel_payment_intent WHERE payment_intent_id=?',iid)
            fact=one('SELECT * FROM payment_order_fact_binding WHERE payment_intent_id=?',iid)
            decision=one('SELECT * FROM vertical_source_decision WHERE vertical_source_decision_id=?',fact['source_decision_id'])
            assert (decision['vertical'],decision['business_id'])==(v,oid), 'SOURCE_ORDER_MISMATCH'
            assert decision['selected_source_id'] and decision['evidence_reference'] and fact['evidence_reference'], 'SOURCE_EVIDENCE_REQUIRED'
            payee=order['supplier_id'] if v=='HOTEL' else decision['selected_source_id']
            assert decision['selected_source_id']==payee, 'SOURCE_PAYEE_MISMATCH'
            for payment in (intent,fact):
                assert payment['payee_id']==payee, 'ORDER_PAYEE_MISMATCH'
                assert payment['amount_minor']==order['total_amount_minor'], 'ORDER_AMOUNT_MISMATCH'
                assert payment['currency']==order['currency'], 'ORDER_CURRENCY_MISMATCH'
            assert (intent['business_type'],intent['business_id'],intent['payer_id'],intent['state'])==(v+'_ORDER',oid,order['account_id'],'SUCCEEDED')
            assert (fact['business_type'],fact['business_id'],fact['payer_id'],fact['payee_id'],fact['currency'],fact['amount_minor'])==(v+'_ORDER',oid,order['account_id'],intent['payee_id'],order['currency'],intent['amount_minor'])
            movements=rows('SELECT * FROM omnichannel_money_movement WHERE root_payment_intent_id=?',iid)
            assert all(x['state']=='CONFIRMED' and x['currency']==order['currency'] and x['business_id']==oid and x['business_type']==v+'_ORDER' for x in movements)
            groups={kind:[x for x in movements if x['movement_type']==kind] for kind in ('AUTHORIZATION','CAPTURE','REFUND')}
            assert len(movements)==3 and all(len(x)==1 for x in groups.values())
            auth,cap,ref=(groups[k][0] for k in ('AUTHORIZATION','CAPTURE','REFUND'))
            assert cap['parent_movement_id']==auth['money_movement_id']
            assert ref['parent_movement_id']==cap['money_movement_id']
            assert auth['amount_minor']==cap['amount_minor']==intent['amount_minor']
            assert 0 < ref['amount_minor']==check['quoted_refund_minor'] <= cap['amount_minor']
            ledger=rows('SELECT * FROM omnichannel_ledger_entry WHERE payment_intent_id=?',iid)
            assert len(ledger)==4
            for movement in (cap,ref):
                pair=[x for x in ledger if x['transaction_id']==movement['money_movement_id']]
                assert len(pair)==2 and {x['direction'] for x in pair}=={'DEBIT','CREDIT'}
                assert all(x['amount_minor']==movement['amount_minor'] and x['currency']==order['currency'] and x['entry_type']==movement['movement_type'] for x in pair)
            refund_sql=f'SELECT * FROM {rt} WHERE order_id=?'
            refunds=rows(refund_sql,oid)
            if v in {'RIDE','RENTAL'}:refunds=[x for x in refunds if x['vertical']==v]
            assert len(refunds)==1
            receipt=refunds[0]
            assert receipt['status'] in {'COMPLETED','REFUND_COMPLETED'}
            assert receipt[amount]==ref['amount_minor'] and receipt['currency']==order['currency']
            attempts=rows('SELECT external_invoked FROM omnichannel_payment_attempt WHERE payment_intent_id=?',iid)
            assert not any(x['external_invoked'] for x in attempts)
            api=check['final']['original_payment']
            assert (api['captured_minor'],api['refunded_minor'],api['net_minor'])==(cap['amount_minor'],ref['amount_minor'],cap['amount_minor']-ref['amount_minor'])
            result['orders'].append({'vertical':v,'order_id':oid,'status':order['status'],
                'payment_intent_id':iid,'currency':order['currency'],'captured_minor':cap['amount_minor'],
                'refunded_minor':ref['amount_minor'],'net_minor':cap['amount_minor']-ref['amount_minor'],
                'capture_count':1,'refund_count':1,'ledger_pairs':2,'result':'PASS'})
        result['result']='PASS'
    except Exception as exc:
        result['error']=str(exc);raise
    finally:
        db.close()
        data=json.dumps(result,indent=2)+'\n'
        (evidence/'independent-ledger-audit.json').write_text(data)
        print(json.dumps({'independent_ledger_audit':result['result'],'orders':len(result['orders']),
                          'sha256':hashlib.sha256(data.encode()).hexdigest()}))


if __name__=='__main__':
    audit(pathlib.Path(sys.argv[1]),pathlib.Path(sys.argv[2]))
