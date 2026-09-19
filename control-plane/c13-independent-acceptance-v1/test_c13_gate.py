import unittest

from c13_gate import (ACTION, ENVIRONMENT, FIXED_APPLICATION_TREE, FIXED_CANDIDATE_SHA,
                      Refusal, UnconfiguredHostTrustBoundary, _qualified_runner,
                      _verified_receipt, derive_task, validate_request)

REQ = {"schema_version":"1","action_id":ACTION,"candidate_sha":FIXED_CANDIDATE_SHA,
       "application_tree":FIXED_APPLICATION_TREE,"c14_receipt_reference":"host://c14/receipt-1"}
BINDING = {"candidate_sha":FIXED_CANDIDATE_SHA,"application_tree":FIXED_APPLICATION_TREE}

class GoodHost:
    def __init__(self, receipt=None, runner=None):
        self.receipt = {"issuer":"c14-independent","verdict":"PASS",**BINDING,"digest":"a"*64,"signature_verified":True} if receipt is None else receipt
        self.runner = {"runner_id":"isolated-c13-01","qualification":"C13_INDEPENDENT","environment":ENVIRONMENT,"independent_of":["implementation","c14"],"registration_verified":True} if runner is None else runner
    def verify_c14_receipt(self, reference, binding): return self.receipt
    def select_independent_runner(self, binding): return self.runner

class C13GateTests(unittest.TestCase):
    def refused(self, reason, fn, *args):
        with self.assertRaises(Refusal) as cm: fn(*args)
        self.assertEqual(cm.exception.args[0], reason)
    def test_01_fixed_source_identity_literals(self):
        self.assertEqual((FIXED_CANDIDATE_SHA,FIXED_APPLICATION_TREE,ACTION,ENVIRONMENT),
                         ("0c3da07bc32009dee16c69125111f8e4ea9d546b","f6d329352dd8484010036448810a927d5eec4be7","GO_C13_INDEPENDENT_ACCEPTANCE","GO-ISOLATED-ACCEPTANCE-01"))
    def test_02_valid_request(self): self.assertEqual(validate_request(REQ),REQ)
    def test_03_task_parameter_keys_and_surfaces(self):
        p=derive_task(REQ,GoodHost())["parameters"]
        self.assertEqual(set(p),{"source","c14_receipt","profile","network","providers","payments","deployment","production"})
        self.assertEqual((p["network"],p["providers"],p["payments"],p["deployment"],p["production"]),("disabled",)*5)

def _case(reason, fn, *args):
    def test(self): self.refused(reason, fn, *args)
    return test

_r = GoodHost().receipt
_runner = GoodHost().runner
_missing = _r.copy(); del _missing["digest"]
_runner_missing = _runner.copy(); del _runner_missing["qualification"]
CASES = [
 ("04_unknown_schema_field","schema_fields",validate_request,{**REQ,"command":"x"}),
 ("05_missing_schema_field","schema_fields",validate_request,{k:v for k,v in REQ.items() if k!="action_id"}),
 ("06_schema_version","action_not_enabled_in_channel",validate_request,{**REQ,"schema_version":"2"}),
 ("07_action","action_not_enabled_in_channel",validate_request,{**REQ,"action_id":"DEPLOY"}),
 ("08_nonhex_candidate","source_identity_format",validate_request,{**REQ,"candidate_sha":"z"*40}),
 ("09_nonhex_tree","source_identity_format",validate_request,{**REQ,"application_tree":"z"*40}),
 ("10_candidate_binding","source_binding_not_authorized",validate_request,{**REQ,"candidate_sha":"0"*40}),
 ("11_tree_binding","source_binding_not_authorized",validate_request,{**REQ,"application_tree":"0"*40}),
 ("12_empty_receipt_ref","receipt_reference_format",validate_request,{**REQ,"c14_receipt_reference":""}),
 ("13_unconfigured_receipt","host_trust_boundary_unconfigured",_verified_receipt,UnconfiguredHostTrustBoundary(),REQ,BINDING),
 ("14_unconfigured_runner","host_trust_boundary_unconfigured",_qualified_runner,UnconfiguredHostTrustBoundary(),BINDING),
 ("15_default_host","host_trust_boundary_unconfigured",derive_task,REQ),
 ("16_receipt_not_mapping","receipt_schema",_verified_receipt,GoodHost(receipt=[]),REQ,BINDING),
 ("17_receipt_missing_key","receipt_schema",_verified_receipt,GoodHost(receipt=_missing),REQ,BINDING),
 ("18_unsigned_receipt","receipt_not_signed_pass",_verified_receipt,GoodHost(receipt={**_r,"signature_verified":False}),REQ,BINDING),
 ("19_nonpass_receipt","receipt_not_signed_pass",_verified_receipt,GoodHost(receipt={**_r,"verdict":"FAIL"}),REQ,BINDING),
 ("20_empty_issuer","receipt_issuer",_verified_receipt,GoodHost(receipt={**_r,"issuer":""}),REQ,BINDING),
 ("21_nonstring_issuer","receipt_issuer",_verified_receipt,GoodHost(receipt={**_r,"issuer":1}),REQ,BINDING),
 ("22_short_digest","receipt_digest",_verified_receipt,GoodHost(receipt={**_r,"digest":"a"*63}),REQ,BINDING),
 ("23_nonhex_digest","receipt_digest",_verified_receipt,GoodHost(receipt={**_r,"digest":"z"*64}),REQ,BINDING),
 ("24_receipt_candidate_mismatch","receipt_binding",_verified_receipt,GoodHost(receipt={**_r,"candidate_sha":"0"*40}),REQ,BINDING),
 ("25_receipt_tree_mismatch","receipt_binding",_verified_receipt,GoodHost(receipt={**_r,"application_tree":"0"*40}),REQ,BINDING),
 ("26_runner_not_mapping","runner_schema",_qualified_runner,GoodHost(runner=[]),BINDING),
 ("27_runner_missing_key","runner_schema",_qualified_runner,GoodHost(runner=_runner_missing),BINDING),
 ("28_unregistered_runner","runner_not_qualified",_qualified_runner,GoodHost(runner={**_runner,"registration_verified":False}),BINDING),
 ("29_wrong_qualification","runner_not_qualified",_qualified_runner,GoodHost(runner={**_runner,"qualification":"C13"}),BINDING),
 ("30_wrong_environment","runner_environment",_qualified_runner,GoodHost(runner={**_runner,"environment":"HK"}),BINDING),
 ("31_empty_runner_id","runner_environment",_qualified_runner,GoodHost(runner={**_runner,"runner_id":""}),BINDING),
 ("32_nonstring_runner_id","runner_environment",_qualified_runner,GoodHost(runner={**_runner,"runner_id":1}),BINDING),
 ("33_not_independent_implementation","runner_not_independent",_qualified_runner,GoodHost(runner={**_runner,"independent_of":["c14"]}),BINDING),
 ("34_not_independent_c14","runner_not_independent",_qualified_runner,GoodHost(runner={**_runner,"independent_of":["implementation"]}),BINDING),
 ("35_extra_execution_surface","schema_fields",validate_request,{**REQ,"network":"enabled"}),
]
for _name,_reason,_fn,*_args in CASES:
    setattr(C13GateTests,"test_"+_name,_case(_reason,_fn,*_args))
