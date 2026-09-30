import tempfile
import unittest
from pathlib import Path
import sys
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from runtime import Runtime
from supervisor import Supervisor

class RecordingWorker:
    def __init__(self): self.calls=[]
    def execute(self,c_id,task):
        self.calls.append((c_id,task.task_id))
        return {"ok":True}

class FailingWorker:
    def execute(self,c_id,task):
        raise RuntimeError("boom")

class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.rt=Runtime(Path(self.tmp.name)/"runtime.db")
    def tearDown(self): self.tmp.cleanup()

    def test_tick_wakes_and_executes_each_runnable_domain(self):
        self.rt.enqueue("C1","A",{})
        self.rt.enqueue("C12","B",{})
        worker=RecordingWorker()
        out=Supervisor(self.rt,worker).tick()
        self.assertEqual(["C1","C12"],out["runnable"])
        self.assertEqual(2,len(worker.calls))
        self.assertEqual(2,self.rt.snapshot()["task_counts"]["SUCCEEDED"])

    def test_worker_failure_escalates(self):
        self.rt.enqueue("C8","A",{})
        out=Supervisor(self.rt,FailingWorker()).tick()
        self.assertEqual("ESCALATED",out["executed"][0]["status"])
        self.assertEqual(1,self.rt.snapshot()["open_escalations"])

if __name__=="__main__":
    unittest.main()
