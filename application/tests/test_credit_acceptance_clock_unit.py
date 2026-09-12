"""Dependency-isolated source-function tests; no database/browser acceptance claim."""
import ast
import asyncio
from contextlib import nullcontext
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import Mock, patch


class CreditAcceptanceClock(unittest.TestCase):
    def setUp(self):
        source=Path(__file__).parents[1]/'src/go_hotel/services/catalog_stay_credit.py'
        tree=ast.parse(source.read_text())
        selected=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in {'conversion_facts','convert'}]
        self.assertEqual(len(selected),2)
        self.clock=datetime(2026,9,13,23,55,tzinfo=timezone.utc)
        self.cash={'check_in':'2026-09-14','forfeited_change_value_minor':0}
        model=SimpleNamespace(original_order_id='id',order_id='id',status='status')
        self.s=Mock()
        self.s.scalar.return_value=None
        self.s.get.return_value=SimpleNamespace(offer_id='offer',amount_minor=100)
        self.remedy=SimpleNamespace(Case=model,paid_facts=Mock(return_value=(100,0,[{'capture_id':'capture','amount_minor':100,'payment_intent_id':'pi'}])),connector=Mock())
        self.order=SimpleNamespace(status='CONFIRMED',currency='CNY',order_id='order',prebook_id='prebook',version=1,account_id='owner',hotel_id='hotel',supplier_id='supplier',supplier_confirmation_no='confirmed')
        self.rule={'stay_credit_allowed':True,'stay_credit_scope':'PROPERTY_ONLY','stay_credit_validity_days':365,'tiers':[]}
        self.ns=dict(date=date,now=lambda:self.clock,select=lambda _:SimpleNamespace(where=lambda *args:None),Credit=model,OrderChangeRow=model,PrebookRow='prebook',OfferRow='offer',Source='source',Movement='movement',remedy=self.remedy,deepcopy=deepcopy,TERMS={'version':'CATALOG_CREDIT_V1'},funds=SimpleNamespace(require_isolated=lambda:None),transaction=lambda:nullcontext(self.s),Order='order-model',aware=lambda x:x)
        exec(compile(ast.Module(body=selected,type_ignores=[]),str(source),'exec'),self.ns)
        self.module=ModuleType('go_hotel.services.catalog_cash_fare')
        self.module.facts=lambda *args:dict(self.cash)

    def facts(self):
        def get(model,key,**kw):
            if model=='source': return None
            return SimpleNamespace(offer_id='offer',amount_minor=100)
        self.s.get.side_effect=get
        with patch.dict(sys.modules,{'go_hotel.services.catalog_cash_fare':self.module}):
            return self.ns['conversion_facts'](self.s,self.order,self.rule)

    def test_future_stay_preserves_contract_payload(self):
        result=self.facts()
        self.assertEqual(result['credit_value_minor'],100)
        self.assertEqual(result['validity_days'],365)
        self.assertEqual(result['rule_snapshot'],self.rule)
        self.assertNotIn('check_in',result)  # No rewriting accepted payload shape.

    def test_same_day_and_past_stay_rejected_before_source_allocation(self):
        for ci in ['2026-09-13','2026-09-12']:
            with self.subTest(check_in=ci):
                self.cash['check_in']=ci
                with self.assertRaisesRegex(ValueError,'UNUSED_FUTURE_STAY_REQUIRED'): self.facts()
        self.remedy.paid_facts.assert_not_called()
        self.s.add_all.assert_not_called()

    def test_latest_confirmed_date_used(self):
        self.cash['check_in']='2026-09-13'
        with self.assertRaisesRegex(ValueError,'UNUSED_FUTURE_STAY_REQUIRED'): self.facts()
        self.cash['check_in']='2026-10-01'
        self.assertEqual(self.facts()['credit_value_minor'],100)

    def test_acceptance_crosses_midnight_before_quote_expiry(self):
        payload=self.facts()
        self.remedy.connector.side_effect=AssertionError('EXPIRED_STAY_REACHED_SUPPLIER_PREPARATION')
        self.clock+=timedelta(minutes=6)
        q=SimpleNamespace(order_id='order',expires_at=self.clock+timedelta(minutes=4),payload_json=payload)
        self.ns['checked_quote']=lambda *args,**kwargs:q
        original_get=self.s.get.side_effect
        self.s.get.side_effect=lambda model,key,**kw:self.order if model=='order-model' else original_get(model,key,**kw)
        with patch.dict(sys.modules,{'go_hotel.services.catalog_cash_fare':self.module}):
            with self.assertRaisesRegex(ValueError,'UNUSED_FUTURE_STAY_REQUIRED'):
                asyncio.run(self.ns['convert']('order','quote','hash',True,'owner'))
        self.remedy.connector.assert_not_called()
        self.s.add_all.assert_not_called()
        self.s.add.assert_not_called()

    def test_existing_conversion_replay_keeps_accepted_contract(self):
        self.clock+=timedelta(days=400)
        existing=SimpleNamespace(stay_credit_id='credit')
        self.s.scalar.return_value=existing
        self.s.get.return_value=self.order
        self.ns['checked_quote']=lambda *args,**kw:SimpleNamespace(order_id='order')
        original={'expires_at':'2027-09-13','status':'EXPIRED'}
        self.ns['value']=SimpleNamespace(checked=lambda *args:(existing,SimpleNamespace(quote_id='quote',accepted_by='owner')),public=lambda *args:original)
        self.assertEqual(asyncio.run(self.ns['convert']('order','quote','hash',True,'owner')),original)
        self.remedy.connector.assert_not_called()
        self.s.add_all.assert_not_called()


if __name__=='__main__': unittest.main()
