import copy
import hashlib
import tempfile
import unittest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from channel import *

class ChannelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name + '/registry.db'
        self.registry = Registry(self.path)
        self.authority, self.task_key, self.agent = [Ed25519PrivateKey.generate() for _ in range(3)]
        pub = self.agent.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.reg = dict(version=1, kind='runtime-host-registration', environment='TEST-ONLY-01',
                        host_id='fixture-host-01', agent_id='fixture-agent-01', generation=1,
                        candidate_sha='a'*40, plan_sha256='b'*64, executor_sha256='c'*64,
                        evidence_key_sha256=hashlib.sha256(pub).hexdigest(), approval_ref='fixture-approval',
                        issued_at=1000, expires_at=2000, actions=[ACTION])
        self.registry.enroll(signed(self.reg,self.authority),self.authority.public_key(),1001)
        self.task = dict(version=1,kind='runtime-host-task',task_id='fixture-task-01',nonce='fixture-nonce-01',
                         environment=self.reg['environment'], host_id=self.reg['host_id'],agent_id=self.reg['agent_id'],
                         generation=1,registration_sha256=digest(self.reg),action=ACTION,parameters={},issued_at=1001,expires_at=1200)
    def tearDown(self):
        self.registry.db.close()
        self.tmp.cleanup()
    def run_probe(self, task=None, **overrides):
        args=dict(raw=signed(task or self.task,self.task_key),task_key=self.task_key.public_key(),
                  live_host_id=self.reg['host_id'],executor_sha256=self.reg['executor_sha256'],evidence_key=self.agent,now=1002)
        args.update(overrides)
        return self.registry.probe(**args)
    def test_roundtrip_and_persistent_readback(self):
        result=self.run_probe()
        self.registry.db.close(); self.registry=Registry(self.path)
        self.assertEqual(self.registry.evidence(self.task['task_id']),('COMPLETE',result))
        self.assertEqual(verify_evidence(result,self.agent.public_key(),self.task,self.reg,1003)['status'],'PROBE_ONLY')
    def test_registration_idempotency(self):
        self.assertEqual(self.registry.enroll(signed(self.reg,self.authority),self.authority.public_key(),1002),'UNCHANGED')
    def test_registration_scope(self):
        for key,value in [('environment','HK-STAGING-01'),('actions',[ACTION,'SHELL']),('version',True),('generation',True),('candidate_sha','main'),('expires_at',1000)]:
            with self.subTest(key=key), self.assertRaises(Reject):
                reg={**self.reg,key:value}; registration(signed(reg,self.authority),self.authority.public_key(),1001)
    def test_registration_bad_signature(self):
        with self.assertRaises(Reject): registration(signed(self.reg,self.agent),self.authority.public_key(),1001)
    def test_rebind_and_rollback(self):
        for update in ({'generation':1,'plan_sha256':'d'*64},{'generation':2,'host_id':'different-host'}):
            with self.subTest(update=update),self.assertRaises(Reject):
                self.registry.enroll(signed({**self.reg,**update},self.authority),self.authority.public_key(),1002)
    def test_generation_invalidates_old_task(self):
        self.registry.enroll(signed({**self.reg,'generation':2},self.authority),self.authority.public_key(),1002)
        with self.assertRaises(Reject): self.run_probe()
    def test_task_scope_and_binding(self):
        for key,value in [('environment','PRODUCTION'),('host_id','other-host'),('agent_id','other-agent'),('action','HK_STAGING_DEPLOY'),('parameters',{'command':'id'}),('generation',True),('registration_sha256','d'*64),('issued_at',1100),('expires_at',1002),('version',True)]:
            with self.subTest(key=key),self.assertRaises(Reject): self.run_probe({**self.task,key:value})
        with self.assertRaises(Reject): self.run_probe({**self.task,'shell':'id'})
    def test_wrong_host_artifact_key(self):
        for update in ({'live_host_id':'other-host'},{'executor_sha256':'e'*64},{'evidence_key':self.task_key},{'task_key':self.agent.public_key()}):
            with self.subTest(update=list(update)),self.assertRaises(Reject): self.run_probe(**update)
    def test_duplicate_json(self):
        with self.assertRaises(Reject): decode(b'{"x":1,"x":2}')
    def test_replay_across_connections(self):
        self.run_probe(); other=Registry(self.path)
        try:
            with self.assertRaises(Reject): other.probe(signed(self.task,self.task_key),self.task_key.public_key(),self.reg['host_id'],'c'*64,self.agent,1003)
        finally: other.db.close()
    def test_nonce_replay_with_new_task(self):
        self.run_probe()
        with self.assertRaises(Reject): self.run_probe({**self.task,'task_id':'new-task-id'})
    def test_claimed_crash_is_not_reexecuted(self):
        self.registry.db.execute('INSERT INTO tasks VALUES (?,?,?,\'CLAIMED\',NULL)',(self.task['task_id'],self.task['nonce'],digest(self.task)))
        with self.assertRaises(Reject): self.run_probe()
        self.assertEqual(self.registry.evidence(self.task['task_id']),('CLAIMED',None))
    def test_registration_expiry(self):
        with self.assertRaises(Reject): self.run_probe({**self.task,'issued_at':2000,'expires_at':2100},now=2001)
    def test_evidence_tampering_and_wrong_key(self):
        evidence=self.run_probe()
        with self.assertRaises(Reject): verify_evidence(evidence,self.task_key.public_key(),self.task,self.reg,1003)
        result=verified(evidence,self.agent.public_key()); result['runtime_acceptance']='PASS'
        with self.assertRaises(Reject): verify_evidence(signed(result,self.agent),self.agent.public_key(),self.task,self.reg,1003)
    def test_evidence_wrong_task_and_stale(self):
        evidence=self.run_probe()
        with self.assertRaises(Reject): verify_evidence(evidence,self.agent.public_key(),{**self.task,'task_id':'different-task'},self.reg,1003)
        with self.assertRaises(Reject): verify_evidence(evidence,self.agent.public_key(),self.task,self.reg,1400)
    def test_no_reservation_on_reject(self):
        with self.assertRaises(Reject): self.run_probe({**self.task,'parameters':{'url':'https://example.invalid'}})
        self.assertIsNone(self.registry.evidence(self.task['task_id']))
        self.run_probe()

if __name__=='__main__': unittest.main()
