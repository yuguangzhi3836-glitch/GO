import unittest
from c13_gate import (ACTION, FIXED_APPLICATION_TREE, FIXED_C14_RECEIPT_ID,
                      FIXED_CANDIDATE_SHA, Refusal, derive_task, validate_request)

REQ={"schema_version":"1","action_id":ACTION,"candidate_sha":FIXED_CANDIDATE_SHA,
     "application_tree":FIXED_APPLICATION_TREE,"c14_receipt_id":FIXED_C14_RECEIPT_ID}

class C13GateTests(unittest.TestCase):
 def test_fixed_binding_only(self): self.assertEqual(validate_request(REQ),REQ)
 def test_refuses_extra_execution_control(self):
  with self.assertRaises(Refusal): validate_request({**REQ,"command":"x"})
 def test_refuses_unqualified_runner_input(self):
  with self.assertRaises(TypeError): derive_task(REQ, {"runner_id":"caller-selected"})
 def test_refuses_non_independent_runner(self):
  with self.assertRaises(Refusal): validate_request({**REQ,"application_tree":"1"*40})
 def test_task_has_no_deploy_surface(self):
  t=derive_task(REQ); self.assertEqual(t["parameters"]["deployment"],"disabled")
 def test_refuses_non_hex_candidate_sha(self):
  with self.assertRaises(Refusal): validate_request({**REQ,"candidate_sha":"z"*40})
 def test_refuses_unverified_numeric_receipt(self):
  with self.assertRaises(Refusal): validate_request({**REQ,"c14_receipt_id":"999"})
 def test_host_registry_selects_runner(self): self.assertEqual(derive_task(REQ)["runner_id"],"isolated-c13-01")

if __name__ == "__main__": unittest.main()
