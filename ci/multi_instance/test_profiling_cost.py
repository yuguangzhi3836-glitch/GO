"""Qualify nested CPU accounting; no GO application/database required."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from pathlib import Path
import sys
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool
sys.path.insert(0,str(Path(__file__).parent))
from profiling import Metrics


def test_nested_cpu_and_commit_have_distinct_scopes():
    engine=create_engine('sqlite://',poolclass=QueuePool)
    m=Metrics(engine)
    def child():
        with engine.begin() as c:c.execute(text('select 1'))
        return sum(i*i for i in range(5000))
    service=SimpleNamespace(child=child)
    service.parent=lambda:service.child()
    m.track(service,'child','child');m.track(service,'parent','parent')
    assert service.parent()>0
    data=m.snapshot();calls=data['service_calls']
    assert calls['parent']['inclusive_calling_thread_cpu_seconds']==pytest.approx(
        calls['parent']['exclusive_calling_thread_cpu_seconds']+calls['child']['inclusive_calling_thread_cpu_seconds'])
    assert calls['child']['inclusive_calling_thread_cpu_seconds']==calls['child']['exclusive_calling_thread_cpu_seconds']
    assert data['service_context_calls']['child|parent=parent']['calls']==1
    assert data['dbapi_commits_by_service']['child']['calls']==1
    assert data['sql_by_service']['child']['count']==1
    assert data['sql_by_service']['child']['calling_thread_cpu_seconds']>=0
    engine.dispose()


def test_failure_preserves_exception_and_clears_scope():
    engine=create_engine('sqlite://',poolclass=QueuePool);m=Metrics(engine)
    def fail():raise ValueError('unchanged')
    s=SimpleNamespace(fail=fail,ok=lambda:42)
    m.track(s,'fail','fail');m.track(s,'ok','ok')
    with pytest.raises(ValueError,match='unchanged'):s.fail()
    assert s.ok()==42
    assert set(m.snapshot()['service_context_calls'])=={'fail|parent=root','ok|parent=root'}
    engine.dispose()


def test_child_thread_is_root_not_nested_cpu():
    engine=create_engine('sqlite://',poolclass=QueuePool);m=Metrics(engine)
    s=SimpleNamespace(child=lambda:sum(range(10000)))
    def parent():
        with ThreadPoolExecutor(max_workers=2) as pool:return sum(pool.map(lambda _:s.child(),range(2)))
    s.parent=parent;m.track(s,'child','child');m.track(s,'parent','parent')
    assert s.parent()==99990000
    data=m.snapshot()
    assert data['service_context_calls']['child|parent=root']['calls']==2
    p=data['service_calls']['parent']
    assert p['exclusive_calling_thread_cpu_seconds']==p['inclusive_calling_thread_cpu_seconds']
    engine.dispose()
