from pathlib import Path
import importlib.util
import sys
import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from observe import cpu_delta, statement_delta, proc_stat, STAT_FIELDS
spec = importlib.util.spec_from_file_location('cost_run', HERE / 'run.py')
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


def test_pid_reuse_or_disappearance_invalidates_cpu_cost():
    before = {'apps': [{'pid': 1, 'start_ticks': 10, 'user_ticks': 4, 'system_ticks': 2}]}
    after = {'apps': [{'pid': 1, 'start_ticks': 20, 'user_ticks': 5, 'system_ticks': 3}]}
    with pytest.raises(AssertionError, match='PROCESS_EXITED'):
        cpu_delta(before, after, 'apps')


def test_new_backend_cpu_and_existing_delta_are_counted():
    before = {'postgres': [{'pid': 1, 'start_ticks': 10, 'user_ticks': 4, 'system_ticks': 2}]}
    after = {'postgres': [dict(before['postgres'][0], user_ticks=6),
                          {'pid': 2, 'start_ticks': 20, 'user_ticks': 3, 'system_ticks': 1}]}
    value = cpu_delta(before, after, 'postgres')
    assert value['new_processes'] == 1 and value['end_processes'] == 2
    assert value['total_seconds'] > 0


def test_statement_counter_reset_is_rejected():
    row = dict.fromkeys(STAT_FIELDS, 2)
    with pytest.raises(AssertionError, match='STATISTICS_RESET'):
        statement_delta({'id': row}, {'id': dict(row, calls=1)})


def test_statement_delta_excludes_old_cost_and_has_no_query_text():
    row = dict.fromkeys(STAT_FIELDS, 2)
    result = statement_delta({'id': row}, {'id': {k: v+1 for k,v in row.items()}})
    assert result == [{'queryid': 'id', **dict.fromkeys(STAT_FIELDS, 1)}]


def test_formal_thresholds_are_preserved_and_nonoverlap_invalid():
    rows = [{'start_ns': 1, 'end_ns': 3, 'duration_ms': 5001, 'ok': True} for _ in range(20)]
    assert not run.stage_summary(rows)['within_original_latency_limits']
    rows[-1].update(start_ns=4, end_ns=5)
    with pytest.raises(AssertionError, match='INVALID_BURST'):
        run.stage_summary(rows)


def test_proc_stat_parses_names_containing_spaces_or_parentheses(monkeypatch):
    fields = ['R', '2'] + ['0'] * 9 + ['4', '5'] + ['0'] * 6 + ['100', '0', '42']
    monkeypatch.setattr(Path, 'read_text', lambda self: '77 (worker (test)) ' + ' '.join(fields))
    row = proc_stat(77)
    assert row == {'pid': 77, 'ppid': 2, 'state': 'R', 'user_ticks': 4,
                   'system_ticks': 5, 'start_ticks': 100, 'rss_pages': 42}


@pytest.mark.parametrize('mode', ['control', 'observed'])
def test_round_observation_mode_cannot_be_overwritten_by_diagnostic_status(mode):
    result = {'mode': 'SAME_WINDOW_DIAGNOSTIC_NOT_ACCEPTANCE', 'correctness': 'PASS'}
    row = run.round_record(1, mode, 'mi_test', result)
    assert row['mode'] == mode
    assert row['diagnostic_mode'] == result['mode']
    assert result['mode'] == 'SAME_WINDOW_DIAGNOSTIC_NOT_ACCEPTANCE'
