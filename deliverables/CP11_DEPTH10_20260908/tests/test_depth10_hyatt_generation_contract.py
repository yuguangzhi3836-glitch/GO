from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUNNER=ROOT/"acceptance"/"run_hyatt_10_real_e2e.py"
KILL=ROOT/"acceptance"/"hyatt_cohort_forced_kill.py"


def test_runner_requires_three_real_generations_and_db_snapshots():
    source=RUNNER.read_text(encoding="utf-8")
    assert "for generation in (1,2,3)" in source
    assert "chain_task_lease_service.rerun" in source
    assert "db_snapshot(hotel_id=hotel_id)" in source
    assert "db_diff(baseline_db[tid],snap)" in source
    assert "authoritative_db_idempotency" in source
    assert "terminal_event_count(tid,generation=generation)!=1" in source


def test_generation_one_uses_real_forced_kill_path():
    source=RUNNER.read_text(encoding="utf-8")
    assert "from hyatt_cohort_forced_kill import run as forced_kill" in source
    assert "forced_kill(task_id=tid,property_id=seed.official_property_id)" in source


def test_forced_kill_recovery_executes_business_service_not_probe_ack():
    source=KILL.read_text(encoding="utf-8")
    assert "os.kill(pid,signal.SIGKILL)" in source
    assert "chain_autonomous_build_service.process_one" in source
    assert "HYATT_RECOVERY_WORKER" in source
    assert "chain_task_lease_service.ack(" not in source
    assert "forced_kill_probe" not in source
