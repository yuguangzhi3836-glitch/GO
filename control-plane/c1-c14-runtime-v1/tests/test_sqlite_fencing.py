"""Behavioral lease races against a real on-disk SQLite database."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime import Runtime, RuntimeErrorInvariant
from supervisor import Supervisor

class SQLiteFencingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'runtime.db'
        self.rt = Runtime(self.path)
        self.tid = self.rt.enqueue('C1', 'RUNTIME_PROBE', {}, max_attempts=3)
    def tearDown(self):
        self.temp.cleanup()
    def row(self):
        with self.rt._connect() as c:
            return dict(c.execute('SELECT * FROM tasks WHERE task_id=?', (self.tid,)).fetchone())
    def expire(self):
        with self.rt.tx() as c:
            c.execute('UPDATE tasks SET lease_until=0 WHERE task_id=?', (self.tid,))
    def test_same_worker_id_after_recovery_rejects_old_complete_and_renew(self):
        old = self.rt.claim('C1', worker_id='same')
        self.expire(); self.rt.recover_stale()
        restarted = Runtime(self.path)
        new = restarted.claim('C1', worker_id='same')
        before = self.row()
        for success in (True, False):
            with self.assertRaises(RuntimeErrorInvariant):
                self.rt.complete('C1', self.tid, worker_id='same', expected_attempt=old.attempts, success=success)
        with self.assertRaises(RuntimeErrorInvariant):
            self.rt.renew_task(self.tid, worker_id='same', expected_attempt=old.attempts)
        self.assertEqual(before, self.row())
        restarted.renew_task(self.tid, worker_id='same', expected_attempt=new.attempts)
        restarted.complete('C1', self.tid, worker_id='same', expected_attempt=new.attempts, success=True)
        with self.rt._connect() as c:
            rows=c.execute("SELECT body_json FROM evidence WHERE event_type='TASK_COMPLETED'").fetchall()
        self.assertEqual([new.attempts], [json.loads(r[0])['attempt'] for r in rows])
    def test_expired_lease_rejected_before_recovery_including_exact_boundary(self):
        task = self.rt.claim('C1', worker_id='w')
        with patch('runtime.time.time', return_value=task.lease_until):
            with self.assertRaises(RuntimeErrorInvariant):
                self.rt.complete('C1', self.tid, worker_id='w', expected_attempt=task.attempts, success=True)
            with self.assertRaises(RuntimeErrorInvariant):
                self.rt.renew_task(self.tid, worker_id='w', expected_attempt=task.attempts)
            self.assertEqual(1, self.rt.recover_stale()['requeued'])
    def test_missing_or_invalid_epoch_never_mutates(self):
        task = self.rt.claim('C1', worker_id='w')
        before=self.row()
        with self.assertRaises(TypeError):
            self.rt.complete('C1', self.tid, worker_id='w', success=True)
        for epoch in (None, True, 0, -1, '1', 1.0, task.attempts+1):
            with self.assertRaises(RuntimeErrorInvariant):
                self.rt.complete('C1', self.tid, worker_id='w', expected_attempt=epoch, success=True)
        self.assertEqual(before,self.row())
    def test_evidence_write_failure_rolls_back_completion(self):
        task=self.rt.claim('C1',worker_id='w')
        with patch.object(self.rt, '_append_evidence', side_effect=sqlite3.OperationalError('injected disk failure')):
            with self.assertRaises(sqlite3.OperationalError):
                self.rt.complete('C1',self.tid,worker_id='w',expected_attempt=task.attempts,success=True)
        self.assertEqual('RUNNING',self.row()['status'])
        self.rt.complete('C1',self.tid,worker_id='w',expected_attempt=task.attempts,success=True)
        self.assertTrue(self.rt.verify_evidence_chain())
    def test_evidence_order_survives_equal_or_backward_timestamps(self):
        for when in (1000.0,1000.0,999.0):
            with patch('runtime.time.time',return_value=when):
                self.rt.append_evidence('C1',self.tid,'CLOCK_TEST',{})
        self.assertTrue(self.rt.verify_evidence_chain())
    def test_supervisor_lost_lease_cannot_escalate_replacement(self):
        outer=self
        class TakeoverWorker:
            def execute(self,c_id,task):
                outer.expire();outer.rt.recover_stale()
                outer.new=outer.rt.claim(c_id,worker_id='supervisor:C1')
                raise RuntimeError('late worker failure')
        out=Supervisor(self.rt,TakeoverWorker()).tick()
        self.assertEqual('LEASE_LOST',out['executed'][0]['status'])
        self.assertEqual('RUNNING',self.row()['status'])
        self.assertEqual(self.new.attempts,self.row()['attempts'])
        self.assertEqual(0,self.rt.snapshot()['open_escalations'])
    def test_probe_filter_leaves_review_and_business_tasks_queued(self):
        review=self.rt.enqueue('C14','INDEPENDENT_REVIEW',{})
        from supervisor import NoopWorker
        Supervisor(self.rt,NoopWorker(),task_kinds=('RUNTIME_PROBE',)).tick()
        with self.rt._connect() as c:
            self.assertEqual('QUEUED',c.execute('SELECT status FROM tasks WHERE task_id=?',(review,)).fetchone()[0])
    def test_completion_checks_expiry_after_waiting_for_write_lock(self):
        task=self.rt.claim('C1',worker_id='w',lease_s=1)
        entered=threading.Event();outcome=[]
        original=self.rt.tx
        @contextmanager
        def signalled_tx():
            entered.set()
            with original() as conn:yield conn
        self.rt.tx=signalled_tx
        lock=sqlite3.connect(self.path,timeout=2)
        lock.execute('BEGIN IMMEDIATE')
        def complete():
            try:
                self.rt.complete('C1',self.tid,worker_id='w',expected_attempt=task.attempts,success=True)
                outcome.append('accepted')
            except RuntimeErrorInvariant:outcome.append('rejected')
        thread=threading.Thread(target=complete)
        try:
            thread.start();self.assertTrue(entered.wait(2))
            # The caller began while valid; by the time it obtains the lock it is expired.
            time.sleep(max(0,task.lease_until-time.time())+.03)
        finally:
            lock.rollback();lock.close();thread.join(3)
        self.assertFalse(thread.is_alive());self.assertEqual(['rejected'],outcome)
        self.assertEqual('RUNNING',self.row()['status'])

    def test_invalid_lease_durations_rejected(self):
        for duration in (0,-1,float('nan'),float('inf'),True):
            with self.assertRaises(ValueError):self.rt.claim('C1',worker_id='w',lease_s=duration)

if __name__=='__main__':unittest.main()
