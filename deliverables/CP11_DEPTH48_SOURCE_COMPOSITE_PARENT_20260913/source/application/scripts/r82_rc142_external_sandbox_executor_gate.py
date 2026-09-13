#!/usr/bin/env python3
from pathlib import Path
import sys, json
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src'))
from go_hotel.connectors.hotel_supply_sandbox import hotel_supply_sandbox_executor
from go_hotel.connectors.external_sandbox_runtime import ContractDrivenHotelSupplyExecutor

class Resolver:
    def resolve(self, ref): return {'token':'sandbox-token','webhook_secret':'hook'}
class Transport:
    def __init__(self): self.calls=[]
    def request(self, method,url,headers,json_body,timeout_seconds):
        self.calls.append((method,url,headers.get('Idempotency-Key')))
        return 200, {}, {'supplier_reference':'ref-'+url.rsplit('/',1)[-1]}

def op(path): return {'method':'POST','path':path,'request_mapping':{'x':'x'},'response_mapping':{'x':'x'}}
contract={
'provider':{'provider_code':'TEST','supplier_legal_name':'Test Supplier','environment':'SANDBOX'},
'contract_source':{'authority':'SIGNED_SUPPLIER_DOCUMENTATION','documentation_reference':'contract://test','documentation_version':'1','documentation_hash':'a'*64},
'transport':{'base_url':'https://sandbox.example.com','auth':{'method':'BEARER','credential_reference':'vault://test'},'ip_allowlist_reference':'allow://test'},
'operations':{k:op('/'+k) for k in ('availability','quote','book','query','cancel')},
'canonical_mapping':{k:{'field':'field'} for k in ('property','room','rate_plan','availability','quote','booking','cancellation')},
'webhook':{'callback_path':'/hook','event_mapping':{'x':'x'},'signature':{'scheme':'HMAC_SHA256','signature_header':'X-Sig','timestamp_header':'X-Time','replay_tolerance_seconds':300,'secret_reference':'vault://hook'}},
'error_mapping':{'supplier_to_go':{'429':'SUPPLIER_RATE_LIMITED'},'unknown_error_policy':'FAIL_CLOSED'},
'limits':{'requests_per_second':1000,'max_concurrency':2,'connect_timeout_ms':1000,'read_timeout_ms':1000,'max_attempts':2,'retryable_go_errors':['SUPPLIER_RATE_LIMITED']},
'attestation':{'contract_reference':'contract://test','sandbox_account_reference':'acct://test','test_property_reference':'hotel://test','authorized_scope':['HOTEL'],'evidence_references':['evidence://test'],'prepared_by':'gate','prepared_at':'2026-08-24T00:00:00+00:00','external_transport_verified':False}
}
checks={}
try:
    hotel_supply_sandbox_executor.execute_suite(supplier_name='x',endpoint='https://x',credential_reference='vault://x',test_hotel_reference='x',mapping={},idempotency_key='x')
    checks['default_fail_closed']=False
except ValueError as e: checks['default_fail_closed']=str(e)=='HOTEL_SUPPLY_SANDBOX_EXECUTOR_NOT_CONFIGURED'
transport=Transport(); ex=ContractDrivenHotelSupplyExecutor(contract=contract,resolver=Resolver(),transport=transport)
hotel_supply_sandbox_executor.install(ex)
results=hotel_supply_sandbox_executor.execute_suite(supplier_name='Test Supplier',endpoint='https://sandbox.example.com',credential_reference='vault://test',test_hotel_reference='hotel://test',mapping={'supplier_property_id':'p','go_hotel_id':'g','rooms':[{'x':1}]},idempotency_key='idem')
by={x.operation:x.ok for x in results}
checks.update({
'executor_injection_controlled':hotel_supply_sandbox_executor.configured,
'availability_quote_book_query_cancel':all(by.get(x) for x in ('AVAILABILITY','QUOTE','BOOK','QUERY','CANCEL')),
'book_idempotency':by.get('BOOK_IDEMPOTENCY') is True,
'signed_webhook_contract':by.get('SIGNED_WEBHOOK') is True,
'error_mapping_fail_closed':by.get('ERROR_MAPPING') is True,
'reconciliation_runtime':by.get('RECONCILIATION') is True,
'audit_evidence':len(ex.audits)==5 and all(a.evidence_reference for a in ex.audits),
})
hotel_supply_sandbox_executor.clear()
for k,v in checks.items(): print(f'{k}={"PASS" if v else "FAIL"}')
if not all(checks.values()): raise SystemExit(1)
print('R8.2_RC14_2_EXTERNAL_SANDBOX_EXECUTOR_GATE: PASS')
