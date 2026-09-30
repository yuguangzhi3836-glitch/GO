from pathlib import Path
import importlib.util,subprocess,sys
import pytest

PATH=Path(__file__).with_name('run.py')
spec=importlib.util.spec_from_file_location('process_pool_harness',PATH)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

@pytest.mark.parametrize('instances',[2,4])
@pytest.mark.parametrize('n',[1,2,20,100])
def test_exact_partition_without_duplicates(instances,n):
    groups=mod.partition(list(range(n)),instances)
    assert sorted(x for group in groups for x in group)==list(range(n))
    assert len(groups)==min(instances,n)
    assert max(map(len,groups))-min(map(len,groups))<=1

@pytest.mark.parametrize('args',[[],['--instances','4','--pool','8','--out','trial'],['--instances','2','--pool','4','--out',str(mod.ROOT/'multi-instance-evidence')],['--instances','3','--pool','4','--out','trial']])
def test_invalid_scope_rejected_before_database(args):
    r=subprocess.run([sys.executable,str(PATH),*args],capture_output=True,text=True)
    assert r.returncode==2 and 'Traceback' not in r.stderr

def test_frozen_formal_default_unchanged():
    assert mod.base.plan_for(0)==[20,100,250,500,1000]
    assert mod.CONFIGS==((2,4),(4,2),(2,8),(4,4))
