from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).parent))
from cpu_candidate import evaluate
import cpu_candidate
import json


def rounds(**overrides):
    baseline={'cpu_seconds':10.,'p95_ms':8000.,'p99_ms':9000.,'max_worker_rss_kib':200000.}
    candidate={'cpu_seconds':8.,'p95_ms':6800.,'p99_ms':9000.,'max_worker_rss_kib':220000.}|overrides
    return [baseline|{'label':'baseline'},candidate|{'label':'candidate'},
            candidate|{'label':'candidate'},baseline|{'label':'baseline'}]


def test_exact_budget_can_pass_but_does_not_accept_5000ms_capacity():
    result=evaluate(rounds())
    assert result['meets_budget']
    assert result['medians']['candidate']['p95_ms']>5000


@pytest.mark.parametrize('change',[{'cpu_seconds':8.1},{'p95_ms':6801.},
                                  {'p99_ms':9001.},{'max_worker_rss_kib':220001.}])
def test_each_required_budget_blocks_adoption(change):
    assert not evaluate(rounds(**change))['meets_budget']


@pytest.mark.parametrize('value',[float('nan'),float('inf'),0,-1,None,True])
def test_invalid_metrics_fail_closed(value):
    with pytest.raises(ValueError):
        evaluate(rounds(cpu_seconds=value))


def test_missing_or_reordered_rounds_are_not_evidence():
    with pytest.raises(ValueError):
        evaluate(rounds()[:2])
    with pytest.raises(ValueError):
        evaluate(list(reversed(rounds()))[1:]+[rounds()[0]])


@pytest.mark.parametrize('same_tree',[True,False])
def test_absent_or_unarmed_candidate_does_not_start_benchmark(tmp_path,monkeypatch,same_tree):
    monkeypatch.setattr(cpu_candidate,'ROOT',tmp_path)
    monkeypatch.setenv('EXPECTED_HEAD','candidate')
    (tmp_path/'ci').mkdir()
    (tmp_path/'ci/cpu_candidate.json').write_text('{"candidate_application_tree":null}')
    def git(*args):
        assert args[0]=='rev-parse', 'Must not create worktrees or run a comparison'
        if args[1]=='HEAD': return 'candidate'
        if args[1].startswith(cpu_candidate.BASELINE): return 'baseline-tree'
        return 'baseline-tree' if same_tree else 'candidate-tree'
    monkeypatch.setattr(cpu_candidate,'git',git)
    assert cpu_candidate.main()==0
    summary=json.loads((tmp_path/'cpu-candidate-evidence/summary.json').read_text())
    assert summary['status']==('NO_APPLICATION_CANDIDATE_NOT_EVALUATED' if same_tree else 'CANDIDATE_NOT_ARMED_NOT_EVALUATED')
    assert summary['rounds']==[] and summary['budget'] is None
