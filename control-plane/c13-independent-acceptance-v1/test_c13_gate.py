import unittest
from c13_gate import ACTION, ENVIRONMENT, Refusal, derive_task, validate_request

REQ={"schema_version":"1","action_id":ACTION,"candidate_sha":"0"*40,"application_tree":"1"*40,"c14_receipt_id":"5740342803"}
RUNNER={"runner_id":"isolated-c13-01","qualification":"C13_INDEPENDENT","environment":ENVIRONMENT,"independence_attested_for":["implementation","c14"]}

class C13GateTests(unittest.TestCase):
 def test_fixed_binding_only(self): self.assertEqual(validate_request(REQ),REQ)
 def test_refuses_extra_execution_control(self):
  with self.assertRaises(Refusal): validate_request({**REQ,"command":"x"})
 def test_refuses_unqualified_runner(self):
  with self.assertRaises(Refusal): derive_task(REQ,{**RUNNER,"qualification":"C13"})
 def test_refuses_non_independent_runner(self):
  with self.assertRaises(Refusal): derive_task(REQ,{**RUNNER,"independence_attested_for":["implementation"]})
 def test_task_has_no_deploy_surface(self):
  t=derive_task(REQ,RUNNER); self.assertEqual(t["parameters"]["deployment"],"disabled")

if __name__ == "__main__": unittest.main()
