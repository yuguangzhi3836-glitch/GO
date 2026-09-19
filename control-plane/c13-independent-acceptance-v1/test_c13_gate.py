import unittest
from c13_gate import ACTION, FIXED_APPLICATION_TREE, FIXED_CANDIDATE_SHA, Refusal, derive_task, validate_request

REQ={"schema_version":"1","action_id":ACTION,"candidate_sha":FIXED_CANDIDATE_SHA,
     "application_tree":FIXED_APPLICATION_TREE,"c14_receipt_reference":"host://c14/receipt-1"}

class GoodHost:
 def verify_c14_receipt(self, ref, binding): return {"issuer":"c14-independent","verdict":"PASS",**binding,"digest":"a"*64,"signature_verified":True}
 def select_independent_runner(self, binding): return {"runner_id":"isolated-c13-01","qualification":"C13_INDEPENDENT","environment":"GO-ISOLATED-ACCEPTANCE-01","independent_of":["implementation","c14"],"registration_verified":True}

class C13GateTests(unittest.TestCase):
 def test_fixed_binding_and_signed_host_receipt_only(self): self.assertEqual(derive_task(REQ,GoodHost())["parameters"]["source"],{"candidate_sha":FIXED_CANDIDATE_SHA,"application_tree":FIXED_APPLICATION_TREE})
 def test_refuses_extra_execution_control(self):
  with self.assertRaises(Refusal): validate_request({**REQ,"command":"deploy"})
 def test_refuses_tree_tampering(self):
  with self.assertRaises(Refusal): validate_request({**REQ,"application_tree":"0"*40})
 def test_refuses_non_hex_source(self):
  with self.assertRaises(Refusal): validate_request({**REQ,"candidate_sha":"z"*40})
 def test_refuses_unconfigured_host(self):
  with self.assertRaises(Refusal): derive_task(REQ)
 def test_refuses_unsigned_or_misbinding_receipt(self):
  class BadReceipt(GoodHost):
   def verify_c14_receipt(self, ref, binding): return {"issuer":"c14","verdict":"PASS",**binding,"digest":"a"*64,"signature_verified":False}
  with self.assertRaises(Refusal): derive_task(REQ,BadReceipt())
 def test_refuses_forged_runner_independence(self):
  class BadRunner(GoodHost):
   def select_independent_runner(self,binding): return {"runner_id":"forged","qualification":"C13_INDEPENDENT","environment":"GO-ISOLATED-ACCEPTANCE-01","independent_of":["implementation"],"registration_verified":True}
  with self.assertRaises(Refusal): derive_task(REQ,BadRunner())
 def test_task_has_no_deploy_or_network_surface(self):
  p=derive_task(REQ,GoodHost())["parameters"]
  self.assertEqual((p["deployment"],p["network"],p["providers"],p["payments"],p["production"]),("disabled",)*5)

if __name__ == "__main__": unittest.main()
