import tempfile,unittest,time,sqlite3
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from runtime import Runtime,RuntimeErrorInvariant
from review_chain import ReviewChain,CandidateBinding

class ChaosAcceptance(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.db=Path(self.tmp.name)/"r.db"; self.rt=Runtime(self.db)
 def tearDown(self): self.tmp.cleanup()

 def test_runtime_restart_keeps_state_and_queue(self):
  self.rt.set_state("C3","checkpoint",{"offset":42})
  tid=self.rt.enqueue("C3","RESUME",{"x":1})
  restarted=Runtime(self.db)
  self.assertEqual({"offset":42},restarted.get_state("C3","checkpoint"))
  self.assertEqual(tid,restarted.claim("C3",worker_id="after-restart").task_id)

 def test_expired_lease_cannot_be_completed_by_dead_worker(self):
  tid=self.rt.enqueue("C5","WORK",{},max_attempts=3)
  first=self.rt.claim("C5",worker_id="dead",lease_s=1)
  self.rt.recover_stale(now=first.lease_until+1)
  second=self.rt.claim("C5",worker_id="replacement")
  with self.assertRaises(RuntimeErrorInvariant):
   self.rt.complete("C5",tid,worker_id="dead",expected_attempt=first.attempts,success=True)
  self.rt.complete("C5",tid,worker_id="replacement",expected_attempt=second.attempts,success=True)

 def test_evidence_tamper_is_detected(self):
  tid=self.rt.enqueue("C6","AUDIT",{})
  self.assertTrue(self.rt.verify_evidence_chain())
  with sqlite3.connect(self.db) as conn:
   conn.execute("UPDATE evidence SET body_json='{}' WHERE task_id=?",(tid,))
  self.assertFalse(self.rt.verify_evidence_chain())

 def test_unknown_permission_fails_closed(self):
  self.assertEqual("DENY",self.rt.authorize("C1","MAGIC_PRODUCTION_BYPASS"))

 def test_c13_bypass_without_c14_rejected(self):
  chain=ReviewChain(self.rt); b=CandidateBinding("sha","tree","ev")
  with self.assertRaises(RuntimeErrorInvariant):
   chain.advance_to_c13(c14_task_id="missing",binding=b)

if __name__=="__main__": unittest.main()

