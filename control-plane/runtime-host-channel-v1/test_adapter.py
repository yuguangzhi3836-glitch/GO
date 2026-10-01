import os
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from channel import *
from adapter import protected_read, derive_probe
import test_channel as fixtures

class AdapterTests(unittest.TestCase):
    setUp = fixtures.ChannelTests.setUp
    tearDown = fixtures.ChannelTests.tearDown
    run_probe = fixtures.ChannelTests.run_probe
    def test_expiry_after_lock_wait(self):
        ticks=iter([1002,1200])
        with self.assertRaises(Reject): self.run_probe(now=lambda:next(ticks))
        self.assertIsNone(self.registry.evidence(self.task['task_id']))
    def test_competing_connections_execute_once(self):
        def run(_):
            db=Registry(self.path)
            try:
                db.probe(signed(self.task,self.task_key),self.task_key.public_key(),self.reg['host_id'],'c'*64,self.agent,1002)
                return 'OK'
            except Reject: return 'REJECT'
            finally: db.db.close()
        with ThreadPoolExecutor(max_workers=4) as pool:
            result=list(pool.map(run,range(4)))
        self.assertEqual(result.count('OK'),1)
        self.assertEqual(result.count('REJECT'),3)
    def test_derived_task_uses_registry_not_request(self):
        req=dict(version=1,request_id='fixture-request',action=ACTION,environment=self.reg['environment'],issued_at=1001,expires_at=1100)
        task=derive_probe(canonical(req),self.reg,'fixture-owner',{'fixture-owner'},1002,'derived-task','derived-nonce')
        self.assertEqual(task['host_id'],self.reg['host_id'])
        self.assertEqual(task['expires_at'],1100)
        self.assertEqual(task['parameters'],{})
        for update in ({'host_id':'other-host'},{'command':'id'},{'action':'HK_STAGING_DEPLOY'}):
            with self.assertRaises(Reject): derive_probe(canonical({**req,**update}),self.reg,'fixture-owner',{'fixture-owner'},1002,'derived-task','derived-nonce')
        with self.assertRaises(Reject): derive_probe(canonical(req),self.reg,'unknown',{'fixture-owner'},1002,'derived-task','derived-nonce')

class ProtectedPathTests(unittest.TestCase):
    def test_relative_parent_and_world_writable_parent(self):
        for path in ('relative','/tmp/../etc/passwd','/tmp/nonexistent'):
            with self.assertRaises(Reject): protected_read(path)
    def test_root_owned_file_and_symlink(self):
        # CI uses an isolated root-owned test directory; no host credentials read.
        if os.geteuid()!=0: self.skipTest('root-owned path verification requires root fixture')
        with tempfile.TemporaryDirectory(dir='/root') as root:
            p=Path(root)/'fixture'; p.write_bytes(b'fixture'); p.chmod(0o600)
            self.assertEqual(protected_read(str(p)),b'fixture')
            q=Path(root)/'link';q.symlink_to(p)
            with self.assertRaises(Reject): protected_read(str(q))
            p.chmod(0o666)
            with self.assertRaises(Reject): protected_read(str(p))
