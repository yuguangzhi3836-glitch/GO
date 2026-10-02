from copy import deepcopy
import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('ride_money_experiment',Path(__file__).with_name('experiment.py'))
experiment=importlib.util.module_from_spec(spec);spec.loader.exec_module(experiment)

def rounds():
    result=[]
    for label in ('baseline','candidate','candidate','baseline'):
        ratio=1 if label=='baseline' else .75
        stages=[]
        for n in (20,100):
            stages.append(dict(concurrent_transactions=n,errors=0,sql='PASS',observed_peak_inflight=n,
                observed_peak_executing=n,application_cpu_seconds=10*ratio,lifetime_cpu_seconds=20*ratio,
                p95_ms=(2000 if n==20 else 6000)*ratio,p99_ms=6500*ratio,sum_worker_max_rss_kib=1000,
                **{'pass':n==20 or label=='candidate'}))
        result.append(dict(label=label,stages=stages))
    return result

def test_budget_and_100_gate_are_separate():
    data=rounds();result=experiment.evaluate(data)
    assert result['meets_budget'] and result['candidate_100_pass']
    assert result['adoption_authorized'] is False
    for row in data:
        if row['label']=='candidate':row['stages'][1]['pass']=False
    assert experiment.evaluate(data)['candidate_100_pass'] is False

@pytest.mark.parametrize('field',['application_cpu_seconds','lifetime_cpu_seconds','p95_ms'])
def test_missing_required_gain_rejects(field):
    data=rounds()
    for row in data:
        if row['label']=='candidate':row['stages'][1][field]=data[0]['stages'][1][field]*.99
    assert experiment.evaluate(data)['meets_budget'] is False

@pytest.mark.parametrize('mutation',['incomplete','order','overlap','money','nonfinite','twenty'])
def test_invalid_evidence_never_passes(mutation):
    data=rounds()
    if mutation=='incomplete':data.pop()
    elif mutation=='order':data.reverse();data[0]['label']='candidate'
    elif mutation=='overlap':data[1]['stages'][1]['observed_peak_executing']=99
    elif mutation=='money':data[1]['stages'][1]['sql']='FAIL'
    elif mutation=='nonfinite':data[1]['stages'][1]['application_cpu_seconds']=float('nan')
    elif mutation=='twenty':data[1]['stages'][0]['pass']=False
    with pytest.raises(AssertionError):experiment.evaluate(data)
