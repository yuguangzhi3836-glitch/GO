"""Contract tests for PostgreSQL adapter.

These use a fake DB-API connection to validate exact transactional/fencing semantics
without requiring network/database access in ordinary CI. Real isolated PostgreSQL
contention remains a separate acceptance gate.
"""
import unittest
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from postgres_runtime import PostgresRuntimeRepository,CLAIM_SQL,COMPLETE_SQL,INSERT_EFFECT_SQL

class FakeCursor:
    def __init__(self,rows): self.rows=list(rows); self.executed=[]
    def execute(self,sql,args=None): self.executed.append((sql,args))
    def fetchone(self): return self.rows.pop(0) if self.rows else None
    def fetchall(self): out=list(self.rows); self.rows=[]; return out
    def __enter__(self): return self
    def __exit__(self,*a): pass
class FakeConn:
    def __init__(self,rows): self.cur=FakeCursor(rows)
    def cursor(self): return self.cur
    def transaction(self): return self
    def __enter__(self): return self
    def __exit__(self,*a): pass

class PostgresContractTests(unittest.TestCase):
    def test_claim_uses_skip_locked(self):
        self.assertIn("FOR UPDATE SKIP LOCKED",CLAIM_SQL)
    def test_completion_is_lease_fenced(self):
        self.assertIn("status='RUNNING'",COMPLETE_SQL)
        self.assertIn("lease_owner=%s",COMPLETE_SQL)
    def test_effects_are_exactly_once_by_key(self):
        self.assertIn("ON CONFLICT(effect_key) DO NOTHING",INSERT_EFFECT_SQL)
    def test_record_effect_reports_conflict(self):
        c=FakeConn([None]); r=PostgresRuntimeRepository(c)
        self.assertFalse(r.record_effect_once(effect_key="k",task_id="t",effect_type="x",body={"a":1}))
    def test_claim_returns_single_row(self):
        row=("t","C1","K",{},1,"later"); c=FakeConn([row]); r=PostgresRuntimeRepository(c)
        self.assertEqual(row,r.claim_one("C1","w"))

if __name__=="__main__": unittest.main()
