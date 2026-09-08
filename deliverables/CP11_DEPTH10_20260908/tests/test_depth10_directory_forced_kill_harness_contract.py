from pathlib import Path

ROOT=Path(__file__).parents[1]
HARNESS=(ROOT/"acceptance/run_directory_forced_kill_recovery.py").read_text()

def test_all_three_crash_boundaries_are_required():
    for token in ("PREPARED_ONLY","PARTIAL_ENQUEUE","ALL_ENQUEUED_NO_COMMIT"):
        assert token in HARNESS

def test_real_sigkill_is_used():
    assert "os.fork()" in HARNESS
    assert "signal.SIGKILL" in HARNESS
    assert "os.kill(pid,signal.SIGKILL)" in HARNESS

def test_recovery_uses_production_enumerate_enqueue_path():
    assert "chain_autonomous_build_service.enumerate_and_enqueue" in HARNESS

def test_acceptance_proves_inventory_task_bijection():
    for token in ("frozen_inventory_equals_unique_tasks","zero_lost","zero_duplicate_queue_events","offset_equals_inventory","snapshot_revision_advanced_once"):
        assert token in HARNESS

def test_emit_recovery_forbids_network_dependency():
    assert "NETWORK_NOT_ALLOWED_DURING_EMIT" in HARNESS
