"""Real disposable child processes; no systemd installation or external I/O."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from runtime import Runtime
from topology import EXPECTED,load_topology,validate_topology
from install_gate import GateInput,installation_eligibility

class TopologyTests(unittest.TestCase):
    def test_proposal_profile_and_scope_expansion_refusal(self):
        load_topology(HERE/'topology.v1.json')
        mutations=[('status','APPROVED'),('authorizes_any_action',True),('environment','HK-STAGING'),
                   ('services',[{'role':'new-worker'}]),('network',{'listeners':[8000],'egress':['all']}),
                   ('credentials',['api-key']),('business_topology_mutation',True),('version',True),
                   ('persistence',{'engine':'postgres'}),('activation_gate','PASS'),('unknown','value')]
        for key,value in mutations:
            doc=copy.deepcopy(EXPECTED);doc[key]=value
            with self.subTest(key=key), self.assertRaises(ValueError):validate_topology(doc)
    def test_old_passes_and_human_flag_do_not_clear_topology_hold(self):
        result=installation_eligibility(GateInput('PASS','PASS','PASS',True,True,True))
        self.assertFalse(result['eligible']);self.assertIn('TOPOLOGY_CHANGE_REQUIRED',result['blockers'])
        self.assertFalse(result['authorizes_any_action'])

class RunnerProcessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'runtime.db'
        self.rt=Runtime(self.db);self.children=[]
        self.health=self.db.with_suffix('.db.health.json')
    def tearDown(self):
        for p in self.children:
            if p.poll() is None:p.kill()
            p.wait(timeout=5)
        self.tmp.cleanup()
    def start(self,*extra):
        p=subprocess.Popen([sys.executable,str(HERE/'runner_service.py'),'--db',str(self.db),'--tick','0.03',*extra],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.children.append(p);return p
    def wait_for(self,predicate,timeout=5):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            try:
                value=predicate()
                if value:return value
            except (FileNotFoundError,json.JSONDecodeError):pass
            time.sleep(.02)
        self.fail('bounded process observation timed out')
    def status(self):return json.loads(self.health.read_text())
    def test_default_refuses_activation(self):
        p=self.start();self.assertNotEqual(0,p.wait(timeout=5));self.assertFalse(self.health.exists())
    def test_singleton_sigkill_restart_probe_only_and_graceful_stop(self):
        probe=self.rt.enqueue('C1','RUNTIME_PROBE',{})
        review=self.rt.enqueue('C14','INDEPENDENT_REVIEW',{})
        self.rt.set_state('C1','cursor',{'offset':42})
        first=self.start('--isolated-validation')
        self.wait_for(lambda:self.status().get('status')=='RUNNING')
        old_id=self.status()['run_id']
        second=self.start('--isolated-validation');self.assertNotEqual(0,second.wait(timeout=5))
        self.assertIsNone(first.poll())
        first.kill();first.wait(timeout=5)
        restarted=self.start('--isolated-validation')
        self.wait_for(lambda:self.status().get('run_id')!=old_id and self.status().get('status')=='RUNNING')
        self.assertEqual({'offset':42},Runtime(self.db).get_state('C1','cursor'))
        with self.rt._connect() as c:
            rows=dict(c.execute('SELECT task_id,status FROM tasks'))
        self.assertEqual('SUCCEEDED',rows[probe]);self.assertEqual('QUEUED',rows[review])
        restarted.terminate();self.assertEqual(0,restarted.wait(timeout=5))
        self.assertEqual('STOPPED',self.status()['status']);self.assertTrue(self.rt.verify_evidence_chain())

if __name__=='__main__':unittest.main()
