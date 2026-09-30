import tempfile,unittest,time
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from runtime import Runtime,RuntimeErrorInvariant
from watchdog import Watchdog
from review_chain import ReviewChain,CandidateBinding

class WatchdogAndChainTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.rt=Runtime(Path(self.tmp.name)/"r.db")
 def tearDown(self): self.tmp.cleanup()
 def test_watchdog_marks_stale_and_recovers(self):
  self.rt.heartbeat("C2",ttl_s=1)
  tid=self.rt.enqueue("C2","X",{},max_attempts=3)
  t=self.rt.claim("C2",worker_id="dead",lease_s=1)
  out=Watchdog(self.rt,stale_after_s=1).inspect(now=t.lease_until+2)
  self.assertIn("C2",out["stale_domains"])
  self.assertEqual(1,out["recovery"]["requeued"])
 def test_c13_requires_completed_c14(self):
  chain=ReviewChain(self.rt); b=CandidateBinding("sha","tree","ev")
  t14=chain.start_c14("C4",b)
  with self.assertRaises(RuntimeErrorInvariant):
   chain.advance_to_c13(c14_task_id=t14,binding=b)
  self.assertIsNone(self.rt.claim("C13",worker_id="independent-c13"))

if __name__=="__main__": unittest.main()

