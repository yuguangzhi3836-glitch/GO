import tempfile,unittest
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from runtime import Runtime,RuntimeErrorInvariant
from handoff import ReviewRequest,request_independent_review,verify_review_binding
from receipt import canonical_receipt,verify_unsigned_receipt

class GovernanceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.rt=Runtime(Path(self.tmp.name)/"r.db")
 def tearDown(self): self.tmp.cleanup()
 def test_c13_review_is_bound_and_idempotent(self):
  req=ReviewRequest("C4","C13","abc","tree","ev-1")
  a=request_independent_review(self.rt,req); b=request_independent_review(self.rt,req)
  self.assertEqual(a,b)
  task=self.rt.claim("C13",worker_id="independent-c13")
  self.assertTrue(verify_review_binding(task.payload))
 def test_self_review_rejected(self):
  with self.assertRaises(RuntimeErrorInvariant):
   request_independent_review(self.rt,ReviewRequest("C13","C13","a","b","c"))
 def test_runtime_receipt_is_canonical_and_unsigned(self):
  r=canonical_receipt(self.rt.snapshot(),runtime_version="v1",head_sha="candidate")
  self.assertTrue(verify_unsigned_receipt(r)); self.assertIsNone(r["signature"])
 def test_duplicate_dispatch_claims_once(self):
  tid=self.rt.enqueue("C9","X",{},idempotency_key="dup")
  self.assertEqual(tid,self.rt.enqueue("C9","X",{},idempotency_key="dup"))
  self.assertIsNotNone(self.rt.claim("C9",worker_id="a"))
  self.assertIsNone(self.rt.claim("C9",worker_id="b"))
 def test_process_death_recovery_preserves_task(self):
  tid=self.rt.enqueue("C10","X",{},max_attempts=3)
  t=self.rt.claim("C10",worker_id="dead",lease_s=1)
  out=self.rt.recover_stale(now=t.lease_until+1)
  self.assertEqual(1,out["requeued"])
  recovered=self.rt.claim("C10",worker_id="replacement")
  self.assertEqual(tid,recovered.task_id)

if __name__=="__main__": unittest.main()
