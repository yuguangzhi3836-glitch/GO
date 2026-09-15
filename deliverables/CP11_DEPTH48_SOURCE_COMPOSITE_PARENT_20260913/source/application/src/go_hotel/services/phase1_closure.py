from dataclasses import dataclass

VERTICALS=('FLIGHT','RAIL','HOTEL','RIDE','RENTAL','ATTRACTION')
CAPABILITIES=('SEARCH','DETAIL','QUOTE','REVALIDATE','ORDER','PAYMENT','TRIP','CHANGE','CANCEL','REFUND','RECONCILIATION')
OFFICIAL={'FLIGHT':'AIRLINE_OFFICIAL','RAIL':'RAIL_OPERATOR_OFFICIAL','HOTEL':'HOTEL_OFFICIAL_DIRECT','RIDE':'FLEET_OFFICIAL','RENTAL':'RENTAL_COMPANY_OFFICIAL','ATTRACTION':'ATTRACTION_OFFICIAL'}
@dataclass(frozen=True)
class SourceCandidate:
 source_id:str;source_type:str;authorized:bool;available:bool;evidence_reference:str|None
class Phase1ClosureService:
 def capability_matrix(self):
  return {'verticals':[{'vertical':v,'capabilities':{c:{'required':True,'truth_state':'RUNTIME_PENDING'} for c in CAPABILITIES},'official_source_type':OFFICIAL[v]} for v in VERTICALS],'surfaces':['CONSUMER','SUPPLIER','ADMIN','FINANCE'],'uniform_state_contract':['LOADING','EMPTY','READY','ERROR_RETRY','UNKNOWN_EXTERNAL_STATE','MANUAL_REVIEW'],'production_live':False}
 def select_source(self,vertical,candidates):
  if vertical not in VERTICALS:raise ValueError('UNSUPPORTED_VERTICAL')
  parsed=[SourceCandidate(**x) for x in candidates]
  official=[x for x in parsed if x.source_type==OFFICIAL[vertical] and x.authorized and x.available and x.evidence_reference]
  if official:return {'selected_source_id':official[0].source_id,'route':'OFFICIAL_DIRECT','reason_codes':['DIRECT_FIRST','AUTHORIZED_AVAILABLE_OFFICIAL_SOURCE']}
  fallback=[x for x in parsed if x.source_type=='AUTHORIZED_FALLBACK' and x.authorized and x.available and x.evidence_reference]
  if fallback:return {'selected_source_id':fallback[0].source_id,'route':'AUTHORIZED_FALLBACK','reason_codes':['OFFICIAL_UNAVAILABLE','EXPLICIT_FALLBACK_AUTHORITY_AND_EVIDENCE']}
  return {'selected_source_id':None,'route':'UNAVAILABLE','reason_codes':['NO_AUTHORIZED_EVIDENCED_SOURCE'],'silent_fallback':False}
 def evidence_policy(self):
  return {'mutations_require':['actor','rule_version','evidence_reference','idempotency_key','occurred_at'],'immutable_domains':['PAYMENT_LEDGER','COMMERCIAL_AUDIT','RECOMMENDATION_DECISION','SUPPLIER_FACT','FINANCE_CLOSE'],'forbidden':['ADMIN_BUYS_RECOMMENDATION','TIMEOUT_RESEND','SILENT_FALLBACK','MOCK_SUCCESS','UNVERIFIED_EXTERNAL_FACT']}
phase1_closure_service=Phase1ClosureService()
