"""Bounded external C1 probe bridge: offline contract tests.

Covers the closed action vector, the fixed bridge request/result schema, the local
filesystem handoff, the Runtime enqueue/observe path and the external Evidence
contract -- all with temporary files, temporary SQLite and no network.

The Runtime half of the loop uses the real frozen Runtime and Supervisor source, which
lives outside this component. Point GO_C1_C14_RUNTIME_SRC at a directory containing
runtime.py/supervisor.py, or have /opt/go/c1-c14-runtime installed; otherwise the
Runtime-backed cases are skipped explicitly rather than silently weakened.
"""
import contextlib
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import channel
import runtime_bridge
from channel import *
from flow import poll_once
from runtime_bridge import LocalBridge
import test_channel as fixtures


def read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def runtime_source_dir():
    candidates = [os.environ.get("GO_C1_C14_RUNTIME_SRC"), "/opt/go/c1-c14-runtime",
                  str(Path(__file__).resolve().parents[1] / "c1-c14-runtime-v1")]
    for candidate in candidates:
        if candidate and (Path(candidate) / "runtime.py").is_file():
            return candidate
    return None


def load_runtime_modules():
    directory = runtime_source_dir()
    if directory is None:
        raise unittest.SkipTest(
            "frozen Runtime source not available; set GO_C1_C14_RUNTIME_SRC")
    if directory not in sys.path:
        sys.path.insert(0, directory)
    import runtime as runtime_module
    import supervisor as supervisor_module
    return runtime_module, supervisor_module


class MemoryTransport:
    """In-memory stand-in. No clone, no network, no git."""

    def __init__(self):
        self.store = {}
        self.writes = 0

    def keys(self):
        return sorted(self.store)

    def read(self, key):
        return self.store.get(key)

    def create(self, key, raw):
        self.writes += 1
        if key in self.store:
            if self.store[key] != raw:
                raise Reject("conflict")
            return
        self.store[key] = raw


class SnapshotMemoryTransport(MemoryTransport):
    """Counts how many times a pass opens a repository snapshot."""

    def __init__(self):
        super().__init__()
        self.snapshot_calls = 0

    @contextlib.contextmanager
    def snapshot(self):
        self.snapshot_calls += 1
        yield self


class ExplodingBridge:
    """Fails the test if the host-probe path ever consults the C1 bridge."""

    def request(self, *args, **kwargs):
        raise AssertionError("the host probe must never reach the C1 bridge")

    def result(self, *args, **kwargs):
        raise AssertionError("the host probe must never reach the C1 bridge")


class BridgeFixture(unittest.TestCase):
    HOST_ONLY = "host-only"
    BOTH = "host-and-runtime"

    def setUp(self):
        fixtures.ChannelTests.setUp(self)
        self.tmpdir = tempfile.TemporaryDirectory()
        self.inbox = os.path.join(self.tmpdir.name, "inbox")
        self.outbox = os.path.join(self.tmpdir.name, "outbox")
        self.bridge = LocalBridge(self.inbox, self.outbox)

    def tearDown(self):
        self.tmpdir.cleanup()
        fixtures.ChannelTests.tearDown(self)

    # ---- fixtures ---------------------------------------------------------
    def make_registration(self, scope):
        actions = [HOST_ACTION] if scope == self.HOST_ONLY else [HOST_ACTION, RUNTIME_ACTION]
        return dict(version=1, kind="runtime-host-registration", environment="TEST-ONLY-01",
                    host_id="fixture-host-01", agent_id="fixture-agent-01", generation=2,
                    candidate_sha="a" * 40, plan_sha256="b" * 64, executor_sha256="c" * 64,
                    evidence_key_sha256=hashlib.sha256(
                        self.agent.public_key().public_bytes(
                            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
                    ).hexdigest(),
                    approval_ref="fixture-approval", issued_at=1000, expires_at=2000,
                    actions=actions)

    def make_task(self, action, task_id="rh-c1probe-fixture01", **overrides):
        task = dict(version=1, kind="runtime-host-task", task_id=task_id,
                    nonce="fixture-nonce-" + task_id[-4:], environment=self.reg["environment"],
                    host_id=self.reg["host_id"], agent_id=self.reg["agent_id"], generation=2,
                    registration_sha256=digest(self.reg), action=action, parameters={},
                    issued_at=1001, expires_at=1200)
        task.update(overrides)
        return task

    def install_registration(self, scope):
        self.reg = self.make_registration(scope)
        self.registry.enroll(signed(self.reg, self.authority), self.authority.public_key(), 1001)
        self.regraw = signed(self.reg, self.authority)
        return self.reg

    def publish(self, task, transport):
        raw = signed(task, self.task_key)
        transport.store["tasks/" + task["task_id"] + ".json"] = raw
        return raw

    def poll(self, tasks, evidence, bridge=None, clock=None):
        return poll_once(self.registry, self.regraw, self.authority.public_key(),
                         self.task_key.public_key(), self.agent, self.reg["host_id"], "c" * 64,
                         tasks, evidence, clock or (lambda: 1002), bridge=bridge)


class ActionScopeTests(unittest.TestCase):
    """A, B, C, D -- the action vector stays closed and backward compatible."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.authority = Ed25519PrivateKey.generate()
        self.agent = Ed25519PrivateKey.generate()
        self.pub = hashlib.sha256(self.agent.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)).hexdigest()
        self.base = dict(version=1, kind="runtime-host-registration", environment="TEST-ONLY-01",
                         host_id="fixture-host-01", agent_id="fixture-agent-01", generation=1,
                         candidate_sha="a" * 40, plan_sha256="b" * 64, executor_sha256="c" * 64,
                         evidence_key_sha256=self.pub, approval_ref="fixture-approval",
                         issued_at=1000, expires_at=2000)

    def tearDown(self):
        self.tmp.cleanup()

    def parse(self, **overrides):
        body = dict(self.base, **overrides)
        return registration(signed(body, self.authority), self.authority.public_key(), 1001)

    def test_original_host_action_alias_is_unchanged(self):
        # A: the original single-action contract still parses exactly as before.
        self.assertEqual(ACTION, "RUNTIME_HOST_PROBE_V1")
        self.assertEqual(HOST_ACTION, ACTION)
        self.assertEqual(ACTIONS, (HOST_ACTION, RUNTIME_ACTION))
        self.assertEqual(self.parse(actions=[HOST_ACTION])["actions"], [HOST_ACTION])

    def test_installed_host_only_registration_stays_valid(self):
        # B: an already-installed registration survives the rollout.
        body = self.parse(actions=[HOST_ACTION])
        self.assertEqual(body["actions"], [HOST_ACTION])
        self.assertNotIn(RUNTIME_ACTION, body["actions"])

    def test_registration_may_authorize_both_actions(self):
        # C
        self.assertEqual(self.parse(actions=[HOST_ACTION, RUNTIME_ACTION])["actions"],
                         [HOST_ACTION, RUNTIME_ACTION])

    def test_unknown_or_malformed_action_vectors_are_rejected(self):
        # D
        for actions in ([HOST_ACTION, RUNTIME_ACTION, "SHELL"], ["SHELL"], [], "RUNTIME_C1_PROBE_V1",
                        [HOST_ACTION, HOST_ACTION], [HOST_ACTION, 7], None):
            with self.subTest(actions=actions), self.assertRaises(Reject):
                self.parse(actions=actions)


class BridgeSchemaTests(unittest.TestCase):
    """F, H -- the bridge request/result schema is fixed and closed."""

    def test_request_is_pinned_to_c1_runtime_probe(self):
        raw = runtime_bridge.encode_request("rh-c1probe-fixture01", "a" * 64, "b" * 64)
        body = runtime_bridge.parse_request(raw)
        self.assertEqual(body["owner_c"], "C1")
        self.assertEqual(body["runtime_kind"], "RUNTIME_PROBE")
        self.assertEqual(body["kind"], "runtime-c1-probe-request")
        self.assertEqual(set(body), set(runtime_bridge.REQUEST_FIELDS.split()))
        self.assertEqual(body["owner_c"], channel.RUNTIME_OWNER_C)
        self.assertEqual(body["runtime_kind"], channel.RUNTIME_KIND)

    def test_request_with_another_target_is_rejected(self):
        for field, value in (("owner_c", "C2"), ("runtime_kind", "RUNTIME_SHELL"),
                             ("owner_c", "C14")):
            body = json.loads(runtime_bridge.encode_request("rh-c1probe-fixture01", "a" * 64,
                                                            "b" * 64).decode())
            body[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(Reject):
                runtime_bridge.parse_request(canonical(body))

    def test_request_schema_rejects_extra_or_malformed_fields(self):
        body = json.loads(runtime_bridge.encode_request("rh-c1probe-fixture01", "a" * 64,
                                                        "b" * 64).decode())
        for mutation in ({"payload": {"command": "id"}}, {"url": "https://example.invalid"},
                         {"external_task_sha256": "short"}, {"external_task_id": "../../etc/passwd"}):
            with self.subTest(mutation=mutation), self.assertRaises(Reject):
                runtime_bridge.parse_request(canonical(dict(body, **mutation)))
        with self.assertRaises(Reject):
            runtime_bridge.parse_request(canonical(dict(body, version=2)))

    def test_result_schema_is_closed(self):
        raw = runtime_bridge.encode_result("rh-c1probe-fixture01", "a" * 64, "rt_" + "f" * 32,
                                           "SUCCEEDED", "c" * 64, "d" * 64)
        body = runtime_bridge.parse_result(raw)
        self.assertEqual(set(body), set(runtime_bridge.RESULT_FIELDS.split()))
        for mutation in ({"runtime_owner_c": "C2"}, {"runtime_status": "QUEUED"},
                         {"runtime_event_hash": "zz"}, {"extra": 1}):
            with self.subTest(mutation=mutation), self.assertRaises(Reject):
                runtime_bridge.parse_result(canonical(dict(body, **mutation)))

    def test_duplicate_json_keys_are_rejected(self):
        raw = b'{"version":1,"version":1}'
        with self.assertRaises(Reject):
            runtime_bridge.parse_request(raw)


class LocalBridgeTests(BridgeFixture):
    """H -- inbox/outbox immutability."""

    def setUp(self):
        super().setUp()
        self.install_registration(self.BOTH)

    def test_same_request_bytes_are_reused(self):
        first = self.bridge.request("rh-c1probe-fixture01", "a" * 64, "b" * 64)
        path = os.path.join(self.inbox, "rh-c1probe-fixture01.json")
        before = read_bytes(path)
        second = self.bridge.request("rh-c1probe-fixture01", "a" * 64, "b" * 64)
        self.assertEqual(first, second)
        self.assertEqual(read_bytes(path), before)
        self.assertEqual(len(os.listdir(self.inbox)), 1)

    def test_different_bytes_for_the_same_task_are_refused_and_not_overwritten(self):
        self.bridge.request("rh-c1probe-fixture01", "a" * 64, "b" * 64)
        path = os.path.join(self.inbox, "rh-c1probe-fixture01.json")
        before = read_bytes(path)
        with self.assertRaises(Reject) as ctx:
            self.bridge.request("rh-c1probe-fixture01", "e" * 64, "b" * 64)
        self.assertIn("bridge_request_conflict", str(ctx.exception))
        self.assertEqual(read_bytes(path), before)

    def test_missing_result_reads_as_none(self):
        self.assertIsNone(self.bridge.result("rh-c1probe-fixture01"))

    def test_symlinked_request_is_not_followed(self):
        os.makedirs(self.inbox, exist_ok=True)
        target = os.path.join(self.tmpdir.name, "outside.json")
        with open(target, "wb") as fh:
            fh.write(runtime_bridge.encode_request("rh-c1probe-fixture01", "a" * 64, "b" * 64))
        link = os.path.join(self.inbox, "rh-c1probe-fixture01.json")
        os.symlink(target, link)
        with self.assertRaises(Reject):
            self.bridge.request("rh-c1probe-fixture01", "a" * 64, "b" * 64)


class BridgeFlowTests(BridgeFixture):
    """E, O, P -- dispatch, backward compatibility and the PR294 snapshot behaviour."""

    def setUp(self):
        super().setUp()
        self.tasks = MemoryTransport()
        self.evidence = MemoryTransport()

    def test_host_probe_never_consults_the_bridge(self):
        # O: the retained host probe keeps its exact old behaviour.
        self.install_registration(self.BOTH)
        task = self.make_task(HOST_ACTION, task_id="rh-probe-fixture01")
        self.publish(task, self.tasks)
        results = self.poll(self.tasks, self.evidence, bridge=ExplodingBridge())
        self.assertEqual(results, [(task["task_id"], "EVIDENCE_PUBLISHED")])
        self.assertEqual(0 if not os.path.isdir(self.inbox) else len(os.listdir(self.inbox)), 0)
        receipt = self.evidence.store["evidence/" + task["task_id"] + ".json"]
        self.assertEqual(verify_evidence(receipt, self.agent.public_key(), task, self.reg, 1003)
                         ["runtime_acceptance"], "NOT_RUN")
        self.assertEqual(self.registry.evidence(task["task_id"])[0], "COMPLETE")

    def test_runtime_action_requires_the_bridge(self):
        self.install_registration(self.BOTH)
        task = self.make_task(RUNTIME_ACTION)
        self.publish(task, self.tasks)
        with self.assertRaises(Reject) as ctx:
            self.poll(self.tasks, self.evidence, bridge=None)
        self.assertIn("bridge_unavailable", str(ctx.exception))
        self.assertEqual(self.evidence.writes, 0)

    def test_runtime_action_with_parameters_is_rejected(self):
        # E
        self.install_registration(self.BOTH)
        task = self.make_task(RUNTIME_ACTION, parameters={"owner_c": "C2"})
        self.publish(task, self.tasks)
        with self.assertRaises(Reject):
            self.poll(self.tasks, self.evidence, bridge=self.bridge)
        self.assertEqual(self.evidence.writes, 0)
        self.assertFalse(os.path.isdir(self.inbox) and os.listdir(self.inbox))

    def test_runtime_action_requires_a_registration_that_authorizes_it(self):
        self.install_registration(self.HOST_ONLY)
        task = self.make_task(RUNTIME_ACTION)
        self.publish(task, self.tasks)
        with self.assertRaises(Reject) as ctx:
            self.poll(self.tasks, self.evidence, bridge=self.bridge)
        self.assertIn("action_not_authorized", str(ctx.exception))

    def test_host_probe_receipt_cannot_be_produced_for_the_bridge_action(self):
        self.install_registration(self.BOTH)
        task = self.make_task(RUNTIME_ACTION)
        with self.assertRaises(Reject) as ctx:
            self.registry.probe(signed(task, self.task_key), self.task_key.public_key(),
                                self.reg["host_id"], "c" * 64, self.agent, 1002)
        self.assertIn("bridge_required", str(ctx.exception))

    def test_evidence_receipt_shape_is_action_dispatched(self):
        # A receipt never carries the other action's shape.
        self.install_registration(self.BOTH)
        host_task = self.make_task(HOST_ACTION, task_id="rh-probe-fixture01")
        host_receipt = self.registry.probe(signed(host_task, self.task_key),
                                           self.task_key.public_key(), self.reg["host_id"],
                                           "c" * 64, self.agent, 1002)
        # A host-shaped receipt is refused for the bridge action: the field sets differ.
        with self.assertRaises(Reject) as ctx:
            verify_evidence(host_receipt, self.agent.public_key(),
                            self.make_task(RUNTIME_ACTION), self.reg, 1003)
        self.assertIn("fields", str(ctx.exception))
        # An action outside the closed set has no receipt contract at all.
        unknown = dict(host_task, action="SOMETHING_ELSE")
        with self.assertRaises(Reject) as ctx:
            verify_evidence(host_receipt, self.agent.public_key(), unknown, self.reg, 1003)
        self.assertIn("evidence_action", str(ctx.exception))

    def test_snapshot_is_still_one_per_repository_per_pass(self):
        # P: the PR294 optimisation is untouched by this round.
        self.install_registration(self.BOTH)
        tasks = SnapshotMemoryTransport()
        evidence = SnapshotMemoryTransport()
        task = self.make_task(HOST_ACTION, task_id="rh-probe-fixture01")
        self.publish(task, tasks)
        self.poll(tasks, evidence, bridge=self.bridge)
        self.assertEqual(tasks.snapshot_calls, 1)
        self.assertEqual(evidence.snapshot_calls, 1)


class C1BridgeEndToEndTests(BridgeFixture):
    """G, I, J, K, L, M, N -- the whole offline loop with the real frozen Runtime."""

    def setUp(self):
        super().setUp()
        self.install_registration(self.BOTH)
        runtime_module, supervisor_module = load_runtime_modules()
        self.runtime_module = runtime_module
        self.supervisor_module = supervisor_module
        self.rt_db = os.path.join(self.tmpdir.name, "runtime.db")
        self.rt = runtime_module.Runtime(self.rt_db)
        self.tasks = MemoryTransport()
        self.evidence = MemoryTransport()
        self.task = self.make_task(RUNTIME_ACTION, task_id="rh-c1probe-fixture01")
        self.publish(self.task, self.tasks)

    def drain(self, passes=4):
        for _ in range(passes):
            self.supervisor_module.Supervisor(
                self.rt, self.supervisor_module.NoopWorker(),
                task_kinds=("RUNTIME_PROBE",)).tick()

    def service(self):
        import runtime_bridge_service as service
        return service.process_once(self.inbox, self.outbox, self.rt, self.rt_db)

    def read_result(self):
        path = os.path.join(self.outbox, self.task["task_id"] + ".json")
        return json.loads(read_bytes(path).decode("utf-8"))

    def test_full_loop_publishes_exactly_one_bound_receipt(self):
        # First pass: the Runtime result does not exist yet, so nothing is published.
        first = self.poll(self.tasks, self.evidence, bridge=self.bridge)
        self.assertEqual(first, [(self.task["task_id"], "RUNTIME_PENDING")])
        self.assertEqual(self.evidence.writes, 0)
        self.assertEqual(self.registry.evidence(self.task["task_id"]),
                         ("RUNTIME_PENDING", None))

        request_files = os.listdir(self.inbox)
        self.assertEqual(request_files, [self.task["task_id"] + ".json"])

        # G: two service scans map the same external task to the same Runtime task.
        summary = self.service()
        self.assertEqual(summary["enqueued"], 1)
        self.assertEqual(summary["pending"], 1)
        first_runtime_task = summary["results"][0][2]
        second = self.service()
        self.assertEqual(second["enqueued"], 1)
        self.assertEqual(second["results"][0][2], first_runtime_task)
        connection = sqlite3.connect(self.rt_db)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 1)
        finally:
            connection.close()

        # The frozen Supervisor and NoopWorker complete it.
        self.drain()
        summary = self.service()
        self.assertEqual(summary["completed"], 1)

        # Second pass: the terminal result is bound into the signed Evidence.
        second_pass = self.poll(self.tasks, self.evidence, bridge=self.bridge)
        self.assertEqual(second_pass, [(self.task["task_id"], "EVIDENCE_PUBLISHED")])
        self.assertEqual(self.evidence.writes, 1)
        dest = "evidence/" + self.task["task_id"] + ".json"
        receipt = self.evidence.store[dest]

        # F: the request really was pinned to C1/RUNTIME_PROBE.
        request = runtime_bridge.parse_request(
            read_bytes(os.path.join(self.inbox, self.task["task_id"] + ".json")))
        self.assertEqual((request["owner_c"], request["runtime_kind"]), ("C1", "RUNTIME_PROBE"))
        self.assertEqual(request["external_task_sha256"], digest(self.task))

        # L: the result references the exact Runtime task.
        result = self.read_result()
        self.assertEqual(result["runtime_task_id"], first_runtime_task)
        self.assertEqual(result["runtime_owner_c"], "C1")
        self.assertEqual(result["runtime_kind"], "RUNTIME_PROBE")
        self.assertEqual(result["runtime_status"], "SUCCEEDED")

        # Message contract.
        verified_receipt = verify_evidence(receipt, self.agent.public_key(), self.task, self.reg, 1003)
        self.assertEqual(verified_receipt["status"], "RUNTIME_COMPLETED")
        self.assertEqual(verified_receipt["runtime_acceptance"], "SUCCEEDED")
        self.assertEqual(verified_receipt["runtime_task_id"], first_runtime_task)
        self.assertEqual(verified_receipt["runtime_owner_c"], "C1")
        self.assertEqual(verified_receipt["runtime_kind"], "RUNTIME_PROBE")
        self.assertEqual(verified_receipt["runtime_event_hash"], result["runtime_event_hash"])
        self.assertEqual(verified_receipt["runtime_result_sha256"], result["runtime_result_sha256"])

        # I, J, K: the Runtime really ran it, once, with a valid evidence chain.
        connection = sqlite3.connect(self.rt_db)
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                "SELECT owner_c,kind,status,attempts,lease_owner,lease_until FROM tasks "
                "WHERE task_id=?", (first_runtime_task,)).fetchone()
            self.assertEqual((row["owner_c"], row["kind"], row["status"], row["attempts"]),
                             ("C1", "RUNTIME_PROBE", "SUCCEEDED", 1))
            self.assertIsNone(row["lease_owner"])
            self.assertIsNone(row["lease_until"])
            events = [r["event_type"] for r in connection.execute(
                "SELECT event_type FROM evidence WHERE task_id=? ORDER BY rowid",
                (first_runtime_task,))]
            self.assertEqual(events, ["TASK_ENQUEUED", "TASK_CLAIMED", "TASK_COMPLETED"])
            completed = connection.execute(
                "SELECT body_json,event_hash FROM evidence WHERE task_id=? AND event_type='TASK_COMPLETED'",
                (first_runtime_task,)).fetchone()
            body = json.loads(completed["body_json"])
            self.assertEqual(body["result"]["adapter"], "noop")
            self.assertEqual(body["result"]["c_id"], "C1")
            self.assertTrue(body["result"]["accepted"])
            self.assertEqual(completed["event_hash"], result["runtime_event_hash"])
            self.assertTrue(self.rt.verify_evidence_chain())
        finally:
            connection.close()

        # N: later passes reuse the exact stored bytes and enqueue nothing new.
        inbox_path = os.path.join(self.inbox, self.task["task_id"] + ".json")
        before_bytes = read_bytes(inbox_path)
        before_mtime = os.stat(inbox_path).st_mtime_ns
        outbox_path = os.path.join(self.outbox, self.task["task_id"] + ".json")
        outbox_bytes = read_bytes(outbox_path)
        for _ in range(3):
            self.assertEqual(self.poll(self.tasks, self.evidence, bridge=self.bridge),
                             [(self.task["task_id"], "EVIDENCE_PUBLISHED")])
        self.assertEqual(self.evidence.writes, 1)
        self.assertEqual(self.evidence.store[dest], receipt)
        self.assertEqual(read_bytes(inbox_path), before_bytes)
        self.assertEqual(os.stat(inbox_path).st_mtime_ns, before_mtime)
        self.assertEqual(read_bytes(outbox_path), outbox_bytes)
        self.assertEqual(self.registry.evidence(self.task["task_id"]), ("COMPLETE", receipt))
        self.assertEqual(self.service()["completed"], 1)
        connection = sqlite3.connect(self.rt_db)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 1)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM evidence WHERE event_type='TASK_ENQUEUED'").fetchone()[0], 1)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM evidence WHERE event_type='TASK_COMPLETED'").fetchone()[0], 1)
        finally:
            connection.close()

    def test_conflicting_outbox_bytes_are_preserved(self):
        # H, service side: an existing different result is never overwritten.
        self.poll(self.tasks, self.evidence, bridge=self.bridge)
        os.makedirs(self.outbox, exist_ok=True)
        path = os.path.join(self.outbox, self.task["task_id"] + ".json")
        with open(path, "wb") as fh:
            fh.write(b'{"kind":"runtime-c1-probe-result","version":1}')
        os.chmod(path, 0o640)
        summary = self.service()
        self.assertEqual(summary["refused"], 1)
        self.assertEqual(read_bytes(path), b'{"kind":"runtime-c1-probe-result","version":1}')

    def test_bad_requests_are_refused_without_stalling_the_scan(self):
        os.makedirs(self.inbox, exist_ok=True)
        with open(os.path.join(self.inbox, "not-a-request.json"), "wb") as fh:
            fh.write(b'{"kind":"runtime-c1-probe-request"}')
        with open(os.path.join(self.inbox, "ignored.txt"), "wb") as fh:
            fh.write(b"junk")
        summary = self.service()
        self.assertEqual(summary["scanned"], 1)
        self.assertEqual(summary["refused"], 1)
        self.assertEqual(summary["enqueued"], 0)


class DispatchGuardTests(unittest.TestCase):
    def test_actions_constant_is_closed_and_ordered(self):
        self.assertEqual(channel.ACTIONS, ("RUNTIME_HOST_PROBE_V1", "RUNTIME_C1_PROBE_V1"))
        self.assertEqual(channel.RUNTIME_OWNER_C, "C1")
        self.assertEqual(channel.RUNTIME_KIND, "RUNTIME_PROBE")
        self.assertEqual(channel.BRIDGE_PENDING, "RUNTIME_PENDING")
        self.assertIsNotNone(channel.RUNTIME_TASK_ID.fullmatch("rt_" + "0" * 32))
        self.assertIsNone(channel.RUNTIME_TASK_ID.fullmatch("rt_ZZ"))
        self.assertEqual(set(channel.EVIDENCE_FIELDS), set(channel.ACTIONS))


if __name__ == "__main__":
    unittest.main()
