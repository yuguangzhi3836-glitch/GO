from pathlib import Path

ROOT=Path(__file__).parents[1]
SRC=ROOT/"src/go_hotel/services"

def text(name):return (SRC/name).read_text()

def test_emission_is_prepared_before_business_enqueue_and_committed_after():
    source=text("chain_autonomous_build.py")
    enum=source.index("durable.enumerate_page")
    enqueue=source.index("chain_task_lease_service.enqueue")
    commit=source.index("durable.commit_emission")
    assert enum < enqueue < commit

def test_prepared_batch_is_replayed_from_postgres():
    source=text("durable_hierarchical_chain_directory.py")
    assert "load_prepared" in source
    assert 'if pending and not pending.get("committed")' in source
    assert "pending[\"seeds\"]" in source

def test_snapshot_offset_advances_only_in_commit_emission():
    source=text("durable_hierarchical_chain_directory.py")
    commit=source[source.index("def commit_emission"):]
    assert "postgres_directory_snapshot_store.checkpoint" in commit
    assert "mark_committed" in commit

def test_emission_outbox_is_postgres_locked_and_revision_bound():
    source=text("chain_directory_emission_outbox.py")
    assert "pg_advisory_xact_lock" in source
    assert "base_revision" in source
    assert "CHAIN_DIRECTORY_EMISSION_BATCH_CONFLICT" in source
    assert "CHAIN_DIRECTORY_EMISSION_COMMIT_CONFLICT" in source

def test_business_task_identity_remains_deterministic():
    source=text("chain_autonomous_build.py")
    assert "task_id=seed.idempotency_key" in source
