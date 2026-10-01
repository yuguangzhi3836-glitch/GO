import unittest
from channel import *
from flow import *
import test_channel as fixtures

class MemoryTransport:
    def __init__(self): self.store={};self.writes=0;self.fail_after=False
    def keys(self): return sorted(self.store)
    def read(self,key): return self.store.get(key)
    def create(self,key,raw):
        self.writes+=1
        if key in self.store:
            if self.store[key]!=raw: raise Reject('conflict')
            return
        self.store[key]=raw
        if self.fail_after: raise OSError('connection lost after write')

class FlowTests(unittest.TestCase):
    def setUp(self):
        fixtures.ChannelTests.setUp(self)
        self.out=Outbox(self.tmp.name+'/out.db')
        self.tasks=MemoryTransport();self.evidence=MemoryTransport()
        self.clock=lambda:1002
        self.regraw=signed(self.reg,self.authority)
        self.req=canonical(dict(version=1,request_id='request-probe-01',action=ACTION,environment=self.reg['environment'],issued_at=1001,expires_at=1200))
    def tearDown(self):
        self.out.db.close();fixtures.ChannelTests.tearDown(self)
    def prepare(self):
        return self.out.prepare(self.req,self.regraw,self.authority.public_key(),'owner',{'owner'},self.task_key,self.clock)
    def publish(self): return self.out.publish('request-probe-01',self.tasks,self.task_key.public_key(),self.clock)
    def poll(self): return poll_once(self.registry,self.regraw,self.authority.public_key(),self.task_key.public_key(),self.agent,self.reg['host_id'],'c'*64,self.tasks,self.evidence,self.clock)
    def test_e2e_initialize_sign_publish_poll_collect(self):
        raw=self.prepare();self.publish();self.poll()
        receipt=collect(raw,self.regraw,self.authority.public_key(),self.task_key.public_key(),self.agent.public_key(),self.evidence,self.clock)
        self.assertEqual(receipt['runtime_acceptance'],'NOT_RUN')
        self.assertEqual(receipt['status'],'PROBE_ONLY')
    def test_prepare_idempotent_durable(self):
        first=self.prepare();self.out.db.close();self.out=Outbox(self.tmp.name+'/out.db')
        self.assertEqual(first,self.prepare())
    def test_ambiguous_publication_reconciles_no_resign(self):
        raw=self.prepare();self.tasks.fail_after=True
        with self.assertRaises(OSError):self.publish()
        self.assertEqual(self.tasks.writes,1)
        self.publish();self.assertEqual(self.tasks.writes,1)
        self.assertEqual(self.prepare(),raw)
    def test_unresolved_publication_does_not_retry(self):
        self.prepare()
        self.out.db.execute("UPDATE outbox SET state='ATTEMPTED'")
        with self.assertRaises(Reject):self.publish()
        self.assertEqual(self.tasks.writes,0)
    def test_receipt_write_lost_ack_reuses_stored_bytes(self):
        self.prepare();self.publish();self.evidence.fail_after=True
        with self.assertRaises(OSError):self.poll()
        original=dict(self.evidence.store)
        self.poll();self.assertEqual(self.evidence.store,original);self.assertEqual(self.evidence.writes,1)
        self.assertEqual(self.registry.db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],1)
    def test_unauthorized_author(self):
        with self.assertRaises(Reject):self.out.prepare(self.req,self.regraw,self.authority.public_key(),'other',{'owner'},self.task_key,self.clock)
    def test_expired_before_publish(self):
        self.prepare();self.clock=lambda:1200
        with self.assertRaises(Reject):self.publish()
        self.assertEqual(self.tasks.writes,0)
    def test_wrong_instance_does_not_emit_evidence(self):
        self.prepare();self.publish()
        with self.assertRaises(Reject):poll_once(self.registry,self.regraw,self.authority.public_key(),self.task_key.public_key(),self.agent,'wrong-host','c'*64,self.tasks,self.evidence,self.clock)
        self.assertEqual(self.evidence.writes,0)
    def test_conflicting_receipt_not_overwritten(self):
        raw=self.prepare();tid=self.publish();self.evidence.store['evidence/'+tid+'.json']=b'conflict'
        with self.assertRaises(Reject):self.poll()
        self.assertEqual(self.evidence.writes,0)

    def test_bootstrap_wrong_host_leaves_empty_registry(self):
        clean=Registry(self.tmp.name+'/new.db')
        try:
            with self.assertRaises(Reject):initialize(clean,self.regraw,self.authority.public_key(),self.agent,'wrong-host','c'*64,self.clock)
            self.assertEqual(clean.db.execute('SELECT COUNT(*) FROM registry').fetchone()[0],0)
            initialize(clean,self.regraw,self.authority.public_key(),self.agent,self.reg['host_id'],'c'*64,self.clock)
            self.assertEqual(clean.db.execute('SELECT COUNT(*) FROM registry').fetchone()[0],1)
        finally:clean.db.close()
