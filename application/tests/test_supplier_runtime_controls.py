from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import multiprocessing
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select, update

from go_hotel.connectors.external_sandbox_runtime import ContractDrivenHotelSupplyExecutor
from go_hotel.connectors.supplier_runtime_controls import (
    ContractResponseValidator, EncryptedSQLEvidenceSink, SQLMutationJournal,
    SQLWebhookReplayStore, metadata, raw_evidence,
)
from test_supplier_preflight_runtime import contract, Resolver, Replay, Transport

pytestmark = pytest.mark.no_db
NOW = datetime(2026, 9, 17, 12, tzinfo=timezone.utc)
KEY = bytes(range(32))  # Deterministic test key, never runtime configuration.
assert len(KEY) == 32


@pytest.fixture
def database(tmp_path):
    # PG URL is an explicit isolated CI fixture, never DATABASE_URL.
    url = os.getenv("SUPPLIER_CONTROLS_TEST_DATABASE_URL") or ("sqlite:///" + str(tmp_path / "controls.db"))
    engine = create_engine(url, hide_parameters=True)
    metadata.create_all(engine)
    yield engine, uuid4().hex
    engine.dispose()


def sink(engine, scope, **kwargs):
    return EncryptedSQLEvidenceSink(engine, scope=scope, keys=kwargs.get("keys", {"k1": KEY}),
                                    active_key_id=kwargs.get("active_key_id", "k1"))


def seal(store):
    return store.seal_attempt(
        operation="BOOK", attempt=1, method="POST",
        url="https://supplier.test/book?email=private@example.test",
        request_body=b'{"guest":"private-person"}', response_status=200,
        response_headers={"Set-Cookie": "secret-response-token"},
        response_body=b'{"token":"secret-response-token"}', transport_error=None,
    )


def build_runtime(engine, scope, transport=None, clock=None):
    return ContractDrivenHotelSupplyExecutor(
        contract=contract(), resolver=Resolver(), transport=transport or Transport(),
        evidence_sink=sink(engine, scope),
        replay_store=SQLWebhookReplayStore(engine, scope=scope, clock=clock),
        mutation_journal=SQLMutationJournal(engine, scope=scope), clock=clock,
    )


def book(runtime, payload=None):
    return runtime._execute_operation(
        "BOOK", endpoint="https://sandbox.supplier.test",
        credential_reference="vault://supplier/auth",
        payload=payload or {"hotel": "H-1"}, idempotency_key="same-booking",
    )


def _claim_worker(url, scope, ready, go, out):
    engine = create_engine(url)
    ready.put(True)
    if not go.wait(20):
        raise RuntimeError("worker barrier timed out")
    try:
        out.put(SQLWebhookReplayStore(engine, scope=scope, clock=lambda: NOW).claim(
            "a" * 64, expires_at=NOW + timedelta(seconds=300)))
    finally:
        engine.dispose()


def _book_worker(url, scope, counter, ready, go, out):
    class CountedTransport(Transport):
        def request(self, method, url, **kwargs):
            fd = os.open(counter, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(fd, b"sent\n")
            finally:
                os.close(fd)
            return super().request(method, url, **kwargs)
    engine = create_engine(url)
    ready.put(True)
    if not go.wait(20):
        raise RuntimeError("worker barrier timed out")
    try:
        result = book(build_runtime(engine, scope, CountedTransport()))
        out.put(result.ok or result.payload.get("idempotency_claim") == "PENDING")
    finally:
        engine.dispose()


def _crash_after_claim(url, scope):
    engine = create_engine(url)
    SQLMutationJournal(engine, scope=scope).begin("d" * 64, "e" * 64)
    os._exit(23)


def run_processes(target, arguments):
    context = multiprocessing.get_context("spawn")
    ready, out, go = context.Queue(), context.Queue(), context.Event()
    processes = [context.Process(target=target, args=(*arguments, ready, go, out)) for _ in range(6)]
    for process in processes:
        process.start()
    try:
        for _ in processes:
            assert ready.get(timeout=30) is True
        go.set()
        results = [out.get(timeout=30) for _ in processes]
        for process in processes:
            process.join(30)
            assert process.exitcode == 0
        return results
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(10)


def test_replay_is_atomic_across_processes_and_survives_restart(database):
    engine, scope = database
    outcomes = run_processes(_claim_worker, (engine.url.render_as_string(hide_password=False), scope))
    assert outcomes.count(True) == 1
    engine.dispose()
    reopened = create_engine(engine.url)
    try:
        assert SQLWebhookReplayStore(reopened, scope=scope, clock=lambda: NOW).claim(
            "a" * 64, expires_at=NOW + timedelta(seconds=300)) is False
        assert SQLWebhookReplayStore(reopened, scope=scope + "-other", clock=lambda: NOW).claim(
            "a" * 64, expires_at=NOW + timedelta(seconds=300)) is True
    finally:
        reopened.dispose()


def test_replay_expiry_is_half_open_and_expired_requests_cannot_claim(database):
    engine, scope = database
    clock = [NOW]
    store = SQLWebhookReplayStore(engine, scope=scope, clock=lambda: clock[0])
    until = NOW + timedelta(seconds=599)
    assert store.claim("b" * 64, expires_at=until)
    clock[0] = NOW + timedelta(seconds=301)
    assert not store.claim("b" * 64, expires_at=until)
    clock[0] = until
    assert not store.claim("b" * 64, expires_at=until)
    assert store.claim("b" * 64, expires_at=until + timedelta(seconds=10))


def test_real_webhook_replay_store_rejects_future_signature_through_full_window(database):
    import hmac
    engine, scope = database
    clock = [NOW]
    runtime = build_runtime(engine, scope, clock=lambda: clock[0])
    timestamp = str(int((NOW + timedelta(seconds=299)).timestamp()))
    body = b'{"event":"updated"}'
    signature = hmac.new(b"hook", timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    arguments = dict(body=body, signature=signature, timestamp=timestamp, resolved_secret={"webhook_secret": "hook"})
    assert runtime.verify_webhook(**arguments)["replay_claimed"]
    clock[0] += timedelta(seconds=301)
    with pytest.raises(ValueError, match="REPLAYED"):
        runtime.verify_webhook(**arguments)
    clock[0] = NOW + timedelta(seconds=599)
    with pytest.raises(ValueError, match="OUTSIDE_TOLERANCE"):
        runtime.verify_webhook(**arguments)


def test_encrypted_raw_evidence_roundtrips_after_reopen_without_plaintext_columns(database):
    engine, scope = database
    reference = seal(sink(engine, scope))
    with engine.connect() as connection:
        row = connection.execute(select(raw_evidence).where(raw_evidence.c.scope == scope)).mappings().one()
        serialized = repr(dict(row))
        assert "secret-response-token" not in serialized
        assert "private-person" not in serialized
        assert "private@example.test" not in serialized
    engine.dispose()
    reopened = create_engine(engine.url)
    try:
        doc = sink(reopened, scope).read_raw(reference)
        raw = base64.b64decode(doc["response_body_b64"])
        assert raw == b'{"token":"secret-response-token"}'
        assert doc["response_sha256"] == hashlib.sha256(raw).hexdigest()
        assert doc["response_headers"]["Set-Cookie"] == "secret-response-token"
    finally:
        reopened.dispose()


def test_evidence_tampering_and_wrong_keys_fail_closed(database):
    engine, scope = database
    store = sink(engine, scope)
    reference = seal(store)
    with pytest.raises(ValueError, match="AUTHENTICATION_FAILED"):
        sink(engine, scope, keys={"k1": b"x" * 32}).read_raw(reference)
    with engine.begin() as connection:
        row = connection.execute(select(raw_evidence).where(raw_evidence.c.scope == scope)).mappings().one()
        connection.execute(update(raw_evidence).where(raw_evidence.c.scope == scope).values(
            ciphertext=row["ciphertext"][:-1] + bytes([row["ciphertext"][-1] ^ 1])))
    with pytest.raises(ValueError, match="AUTHENTICATION_FAILED"):
        store.read_raw(reference)


def test_ciphertext_cannot_move_between_records_or_accounts(database):
    engine, scope = database
    reference = seal(sink(engine, scope))
    other_reference = seal(sink(engine, scope + "-other"))
    with engine.begin() as connection:
        original = connection.execute(select(raw_evidence).where(raw_evidence.c.scope == scope)).mappings().one()
        connection.execute(update(raw_evidence).where(raw_evidence.c.scope == scope + "-other").values(
            nonce=original["nonce"], ciphertext=original["ciphertext"]))
    with pytest.raises(ValueError, match="AUTHENTICATION_FAILED"):
        sink(engine, scope + "-other").read_raw(other_reference)
    with pytest.raises(ValueError, match="NOT_FOUND"):
        sink(engine, scope + "-other").read_raw(reference)


def test_key_rotation_preserves_prior_raw_evidence(database):
    engine, scope = database
    old = seal(sink(engine, scope))
    rotated = sink(engine, scope, keys={"k1": KEY, "k2": b"y" * 32}, active_key_id="k2")
    new = seal(rotated)
    assert rotated.read_raw(old) == rotated.read_raw(new)
    with pytest.raises(ValueError, match="KEY_UNAVAILABLE"):
        sink(engine, scope, keys={"k2": b"y" * 32}, active_key_id="k2").read_raw(old)


def test_no_receipt_is_returned_when_database_commit_fails(database):
    engine, scope = database
    def fail_commit(connection):
        raise RuntimeError("injected database commit failure")
    event.listen(engine, "commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="commit failure"):
            seal(sink(engine, scope))
    finally:
        event.remove(engine, "commit", fail_commit)
    with engine.connect() as connection:
        assert connection.execute(select(raw_evidence).where(raw_evidence.c.scope == scope)).first() is None


def test_mutating_request_is_sent_once_across_processes_and_restart(database, tmp_path):
    engine, scope = database
    counter = str(tmp_path / "requests")
    outcomes = run_processes(_book_worker, (engine.url.render_as_string(hide_password=False), scope, counter))
    assert all(outcomes)
    assert Path(counter).read_text() == "sent\n"
    reopened_transport = Transport()
    replay = book(build_runtime(engine, scope, reopened_transport))
    assert replay.ok
    assert reopened_transport.calls == []


def test_idempotency_conflict_and_crashed_owner_never_resend(database):
    engine, scope = database
    journal = SQLMutationJournal(engine, scope=scope)
    key, digest = "a" * 64, "b" * 64
    assert journal.begin(key, digest)["claimed"]
    assert not SQLMutationJournal(engine, scope=scope).begin(key, digest)["claimed"]
    assert SQLMutationJournal(engine, scope=scope).begin(key, digest)["result"] is None
    with pytest.raises(ValueError, match="IDEMPOTENCY_CONFLICT"):
        journal.begin(key, "c" * 64)


def test_hard_exit_leaves_durable_pending_claim(database):
    engine, scope = database
    context = multiprocessing.get_context("spawn")
    process = context.Process(target=_crash_after_claim, args=(
        engine.url.render_as_string(hide_password=False), scope))
    process.start()
    process.join(30)
    if process.is_alive():
        process.terminate()
        process.join(10)
    assert process.exitcode == 23
    assert SQLMutationJournal(engine, scope=scope).begin("d" * 64, "e" * 64) == {
        "claimed": False, "result": None}


def test_evidence_failure_leaves_mutation_pending_and_restart_does_not_resend(database):
    engine, scope = database
    class BrokenEvidence:
        def seal_attempt(self, **kwargs):
            raise RuntimeError("storage offline")
    transport = Transport()
    runtime = build_runtime(engine, scope, transport)
    runtime.evidence_sink = BrokenEvidence()
    with pytest.raises(RuntimeError, match="storage offline"):
        book(runtime)
    restarted = build_runtime(engine, scope, transport)
    result = book(restarted)
    assert not result.ok and result.payload["idempotency_claim"] == "PENDING"
    assert len(transport.calls) == 1


@pytest.mark.parametrize("raw", [b"", b"[]", b"null", b'{"error":"sold_out"}',
                                b'{"status":"failed","supplier_reference":"S-1"}',
                                b'{"status":"ok","supplier_reference":""}',
                                b'{"status":true,"supplier_reference":"S-1"}'])
def test_http_200_does_not_imply_business_success(database, raw):
    engine, scope = database
    runtime = build_runtime(engine, scope, Transport([(200, {}, raw)]))
    result = book(runtime)
    assert not result.ok
    assert result.payload["normalized_error"] == "SUPPLIER_RESPONSE_VALIDATION_FAILED"
    assert len(runtime.audits) == 1


def test_missing_response_rules_block_before_network(database):
    engine, scope = database
    transport = Transport()
    runtime = build_runtime(engine, scope, transport)
    del runtime.contract["operations"]["book"]["response_validation"]
    with pytest.raises(ValueError, match="RESPONSE_RULES_REQUIRED"):
        book(runtime)
    assert transport.calls == []


@pytest.mark.parametrize("changed", ["endpoint", "credential", "provider", "auth"])
def test_contract_identity_drift_conflicts_instead_of_opening_new_mutation(database, changed):
    engine, scope = database
    transport = Transport()
    runtime = build_runtime(engine, scope, transport)
    assert book(runtime).ok
    if changed == "endpoint":
        runtime.contract["transport"]["base_url"] = "https://other.supplier.test"
    elif changed == "credential":
        runtime.contract["transport"]["auth"]["credential_reference"] = "vault://supplier/rotated"
    elif changed == "auth":
        runtime.contract["transport"]["auth"]["method"] = "BASIC"
    else:
        runtime.contract["provider"]["provider_code"] = "PROVIDER_RENAMED"
    with pytest.raises(ValueError, match="SUPPLIER_IDEMPOTENCY_CONFLICT"):
        runtime._execute_operation(
            "BOOK", endpoint=runtime.contract["transport"]["base_url"],
            credential_reference=runtime.contract["transport"]["auth"]["credential_reference"],
            payload={"hotel": "H-1"}, idempotency_key="same-booking")
    assert len(transport.calls) == 1


def test_response_success_type_mismatch_cannot_equal_true(database):
    engine, scope = database
    runtime = build_runtime(engine, scope)
    rules = runtime.contract["operations"]["book"]["response_validation"]
    rules["required_fields"]["status"] = "boolean"
    rules["success_equals"]["status"] = 1
    with pytest.raises(ValueError, match="SUCCESS_RULES_INVALID"):
        book(runtime)


def test_suite_stops_before_book_after_failed_availability(database):
    engine, scope = database
    transport = Transport([(200, {}, b'{"error":"unavailable"}')])
    runtime = build_runtime(engine, scope, transport)
    results = runtime.execute_suite(
        supplier_name="Signed Supplier Ltd", endpoint="https://sandbox.supplier.test",
        credential_reference="vault://supplier/auth", test_hotel_reference="H-1",
        mapping={"supplier_property_id": "P", "go_hotel_id": "G", "rooms": ["R"]},
        idempotency_key="suite",
    )
    assert len(transport.calls) == 1
    assert next(r for r in results if r.operation == "BOOK").payload["error"] == "PREREQUISITE_FAILED_NOT_SENT"
    for name in ("BOOK_IDEMPOTENCY", "SIGNED_WEBHOOK", "RECONCILIATION"):
        assert next(r for r in results if r.operation == name).ok is False


def test_unbound_endpoint_and_credentials_are_rejected_before_request(database):
    engine, scope = database
    transport = Transport()
    runtime = build_runtime(engine, scope, transport)
    for endpoint, credential in [
        ("https://uncontracted.test", "vault://supplier/auth"),
        ("https://sandbox.supplier.test", "vault://other/account"),
    ]:
        with pytest.raises(ValueError, match="PROVIDER_CONTRACT_.*_MISMATCH"):
            runtime._execute_operation("BOOK", endpoint=endpoint, credential_reference=credential,
                                       payload={}, idempotency_key="once")
    assert transport.calls == []


@pytest.mark.parametrize("url", ["sqlite:///:memory:", "sqlite:///file::memory:?cache=shared&uri=true"])
def test_memory_only_database_is_rejected(url):
    engine = create_engine(url)
    with pytest.raises(ValueError, match="DURABLE_CONTROLS_DATABASE_REQUIRED"):
        SQLWebhookReplayStore(engine, scope="account")
