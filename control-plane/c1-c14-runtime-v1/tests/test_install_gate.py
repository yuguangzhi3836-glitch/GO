import unittest
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(HERE))
from install_gate import GateInput,installation_eligibility
from acceptance_harness import Scenario,evaluate

class InstallGateTests(unittest.TestCase):
 def test_acceptance_missing_scenario_fails(self):
  x=[Scenario("claim_contention",True,{})]
  self.assertEqual("FAIL",evaluate(x)["verdict"])
 def test_every_install_gate_required(self):
  base=dict(postgres_acceptance="PASS",c13_verdict="PASS",c14_verdict="PASS",
            evidence_chain_valid=True,sha256_manifest_present=True,human_command_center_authorization=True)
  self.assertTrue(installation_eligibility(GateInput(**base))["eligible"])
  for key in list(base):
   bad=dict(base)
   bad[key]=False if isinstance(base[key],bool) else "FAIL"
   self.assertFalse(installation_eligibility(GateInput(**bad))["eligible"],key)
 def test_no_human_authorization_means_no_install(self):
  x=GateInput("PASS","PASS","PASS",True,True,False)
  self.assertIn("HUMAN_AUTHORIZATION_MISSING",installation_eligibility(x)["blockers"])
if __name__=="__main__": unittest.main()
