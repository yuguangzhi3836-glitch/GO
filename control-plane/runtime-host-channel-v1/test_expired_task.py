"""Expired historical task objects must be inert.

Covers the delivery-window classification, the poll order that keeps a completed task
replayable, the BRIDGE_PENDING -> BRIDGE_EXPIRED transition, and the integrity failures
that must keep failing closed.

Offline only: temporary files, temporary SQLite, in-memory transports, no network.
The Runtime-backed cases use the real frozen Runtime and Supervisor source, located via
GO_C1_C14_RUNTIME_SRC or /opt/go/c1-c14-runtime; otherwise they skip explicitly.
"""
import json
import os
import sqlite3
import tempfile
import unittest

from channel import (
    BRIDGE_EXPIRED, BRIDGE_PENDING, HOST_ACTION, RUNTIME_ACTION, TASK_ACTIVE, TASK_EXPIRED,
    TASK_FUTURE, Reject, digest, signed, task_temporal_state,
)
from test_c1_bridge import BridgeFixture, ExplodingBridge, MemoryTransport, load_runtime_modules

# The fixture registration is valid for 1000 <= now < 2000, and the default fixture task
# for 1001 <= now < 1200. Every clock below stays inside the registration window so the
# only thing under test is the external task's own delivery window.
def read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


REGISTRATION_VALID_CLOCK = lambda: 1300          # noqa: E731 -- past the default task window
ACTIVE_CLOCK = lambda: 1002                      # noqa: E731 -- inside the default task window


class TemporalStateHelperTests(unittest.TestCase):
    """One explicit helper, and structural faults stay fail-closed."""

    BASE = {"issued_at": 1000, "expires_at": 1300}

    def test_classification_boundaries(self):
        self.assertEqual(task_temporal_state(self.BASE, 999), TASK_FUTURE)
        self.assertEqual(task_temporal_state(self.BASE, 1000), TASK_ACTIVE)
        self.assertEqual(task_temporal_state(self.BASE, 1299), TASK_ACTIVE)
        self.assertEqual(task_temporal_state(self.BASE, 1300), TASK_EXPIRED)
        self.assertEqual(task_temporal_state(self.BASE, 10 ** 9), TASK_EXPIRED)
        self.assertEqual((TASK_ACTIVE, TASK_FUTURE, TASK_EXPIRED), ("ACTIVE", "FUTURE", "EXPIRED"))

    def test_structural_faults_are_never_a_classification(self):
        cases = [{"issued_at": True, "expires_at": 1300},
                 {"issued_at": 1000, "expires_at": True},
                 {"issued_at": "1000", "expires_at": 1300},
                 {"issued_at": 1000.0, "expires_at": 1300},
                 {"issued_at": 1000, "expires_at": 1400},     # lifetime > 300
                 {"issued_at": 1000, "expires_at": 1000},     # lifetime == 0
                 {"issued_at": 1000, "expires_at": 999},      # negative lifetime
                 {}]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(Reject):
                task_temporal_state(case, 1000)


class ExpiredObjectTests(BridgeFixture):
    """A, B, C, D, H, I, J, K -- poll_once behaviour with a stale object."""

    def setUp(self):
        super().setUp()
        self.tasks = MemoryTransport()
        self.evidence = MemoryTransport()

    # ---- A -----------------------------------------------------------------
    def test_a_unknown_expired_host_probe_is_ignored(self):
        self.install_registration(self.BOTH)
        task = self.make_task(HOST_ACTION, task_id="rh-probe-expired01")
        self.publish(task, self.tasks)
        results = self.poll(self.tasks, self.evidence, bridge=self.bridge,
                            clock=REGISTRATION_VALID_CLOCK)
        self.assertEqual(results, [(task["task_id"], "EXPIRED_IGNORED")])
        self.assertIsNone(self.registry.evidence(task["task_id"]))
        self.assertEqual(self.evidence.writes, 0)
        self.assertEqual(self.registry.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)

    # ---- B -----------------------------------------------------------------
    def test_b_unknown_expired_c1_probe_never_reaches_the_bridge(self):
        self.install_registration(self.BOTH)
        task = self.make_task(RUNTIME_ACTION, task_id="rh-c1probe-expired01")
        self.publish(task, self.tasks)
        results = self.poll(self.tasks, self.evidence, bridge=ExplodingBridge(),
                            clock=REGISTRATION_VALID_CLOCK)
        self.assertEqual(results, [(task["task_id"], "EXPIRED_IGNORED")])
        self.assertIsNone(self.registry.evidence(task["task_id"]))
        self.assertEqual(self.evidence.writes, 0)
        self.assertEqual(self.registry.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)
        self.assertFalse(os.path.isdir(self.inbox) and os.listdir(self.inbox))

    # ---- C -----------------------------------------------------------------
    def test_c_future_task_is_held_back_and_then_processes_normally(self):
        self.install_registration(self.BOTH)
        task = self.make_task(HOST_ACTION, task_id="rh-probe-future01",
                              issued_at=1500, expires_at=1700)
        self.publish(task, self.tasks)

        self.assertEqual(self.poll(self.tasks, self.evidence, bridge=self.bridge,
                                   clock=REGISTRATION_VALID_CLOCK),
                         [(task["task_id"], "NOT_YET_VALID")])
        self.assertIsNone(self.registry.evidence(task["task_id"]))
        self.assertEqual(self.evidence.writes, 0)

        # The same object, once its window opens, is processed exactly as before.
        self.assertEqual(self.poll(self.tasks, self.evidence, bridge=self.bridge, clock=lambda: 1550),
                         [(task["task_id"], "EVIDENCE_PUBLISHED")])
        self.assertEqual(self.registry.evidence(task["task_id"])[0], "COMPLETE")

    def test_c2_future_c1_task_does_not_touch_the_bridge(self):
        self.install_registration(self.BOTH)
        task = self.make_task(RUNTIME_ACTION, task_id="rh-c1probe-future01",
                              issued_at=1500, expires_at=1700)
        self.publish(task, self.tasks)
        self.assertEqual(self.poll(self.tasks, self.evidence, bridge=ExplodingBridge(),
                                   clock=REGISTRATION_VALID_CLOCK),
                         [(task["task_id"], "NOT_YET_VALID")])
        self.assertFalse(os.path.isdir(self.inbox) and os.listdir(self.inbox))

    # ---- D -----------------------------------------------------------------
    def test_d_completed_host_probe_replays_after_its_window_closed(self):
        self.install_registration(self.BOTH)
        task = self.make_task(HOST_ACTION, task_id="rh-probe-done01")
        self.publish(task, self.tasks)
        self.assertEqual(self.poll(self.tasks, self.evidence, bridge=self.bridge),
                         [(task["task_id"], "EVIDENCE_PUBLISHED")])
        receipt = self.evidence.store["evidence/" + task["task_id"] + ".json"]
        writes = self.evidence.writes

        self.assertEqual(self.poll(self.tasks, self.evidence, bridge=self.bridge,
                                   clock=REGISTRATION_VALID_CLOCK),
                         [(task["task_id"], "EVIDENCE_PUBLISHED")])
        self.assertEqual(self.evidence.writes, writes)
        self.assertEqual(self.registry.evidence(task["task_id"]), ("COMPLETE", receipt))

    # ---- H -----------------------------------------------------------------
    def test_h_out_of_contract_lifetime_is_still_refused(self):
        self.install_registration(self.BOTH)
        task = self.make_task(HOST_ACTION, task_id="rh-probe-longlife01", expires_at=1500)
        self.publish(task, self.tasks)
        with self.assertRaises(Reject) as ctx:
            self.poll(self.tasks, self.evidence, bridge=self.bridge)
        self.assertIn("lifetime", str(ctx.exception))
        self.assertIsNone(self.registry.evidence(task["task_id"]))
        self.assertEqual(self.evidence.writes, 0)

    # ---- I -----------------------------------------------------------------
    def test_i_bad_signature_is_still_refused_even_when_expired(self):
        self.install_registration(self.BOTH)
        task = self.make_task(HOST_ACTION, task_id="rh-probe-badsig01")
        self.tasks.store["tasks/" + task["task_id"] + ".json"] = signed(task, self.agent)
        with self.assertRaises(Reject) as ctx:
            self.poll(self.tasks, self.evidence, bridge=self.bridge,
                      clock=REGISTRATION_VALID_CLOCK)
        self.assertIn("signature", str(ctx.exception))
        self.assertEqual(self.evidence.writes, 0)

    # ---- J -----------------------------------------------------------------
    def test_j_task_id_rebound_is_still_refused_even_when_expired(self):
        self.install_registration(self.BOTH)
        task = self.make_task(HOST_ACTION, task_id="rh-probe-rebound01")
        self.publish(task, self.tasks)
        self.registry.db.execute("INSERT INTO tasks VALUES (?,?,?,'COMPLETE',?)",
                                 (task["task_id"], task["nonce"], "0" * 64, b"stale"))
        with self.assertRaises(Reject) as ctx:
            self.poll(self.tasks, self.evidence, bridge=self.bridge,
                      clock=REGISTRATION_VALID_CLOCK)
        self.assertIn("task_id_rebound", str(ctx.exception))

    # ---- K -----------------------------------------------------------------
    def test_k_evidence_conflict_is_still_refused_even_when_expired(self):
        self.install_registration(self.BOTH)
        task = self.make_task(HOST_ACTION, task_id="rh-probe-conflict01")
        self.publish(task, self.tasks)
        self.poll(self.tasks, self.evidence, bridge=self.bridge)
        self.evidence.store["evidence/" + task["task_id"] + ".json"] = b'{"body":{},"signature":"AAAA"}'
        with self.assertRaises(Reject) as ctx:
            self.poll(self.tasks, self.evidence, bridge=self.bridge,
                      clock=REGISTRATION_VALID_CLOCK)
        self.assertIn("evidence_publication_conflict", str(ctx.exception))


class ExpireBridgePendingMethodTests(BridgeFixture):
    """The narrow Registry transition itself."""

    def setUp(self):
        super().setUp()
        self.install_registration(self.BOTH)
        self.tasks = MemoryTransport()
        self.evidence = MemoryTransport()
        self.task = self.make_task(RUNTIME_ACTION, task_id="rh-c1probe-expiemeth01")
        self.publish(self.task, self.tasks)

    def enter_pending(self):
        results = self.poll(self.tasks, self.evidence, bridge=self.bridge, clock=ACTIVE_CLOCK)
        self.assertEqual(results, [(self.task["task_id"], BRIDGE_PENDING)])
        self.assertEqual(self.registry.evidence(self.task["task_id"]), (BRIDGE_PENDING, None))

    def test_unknown_task_is_refused(self):
        with self.assertRaises(Reject) as ctx:
            self.registry.expire_bridge_pending("rh-c1probe-unknown01", "a" * 64)
        self.assertIn("unknown_task", str(ctx.exception))

    def test_digest_mismatch_is_refused(self):
        self.enter_pending()
        with self.assertRaises(Reject) as ctx:
            self.registry.expire_bridge_pending(self.task["task_id"], "a" * 64)
        self.assertIn("task_id_rebound", str(ctx.exception))
        self.assertEqual(self.registry.evidence(self.task["task_id"]), (BRIDGE_PENDING, None))

    def test_complete_is_never_changed(self):
        self.enter_pending()
        self.registry.db.execute("UPDATE tasks SET state='COMPLETE',evidence=? WHERE id=?",
                                 (b"stored", self.task["task_id"]))
        with self.assertRaises(Reject) as ctx:
            self.registry.expire_bridge_pending(self.task["task_id"], digest(self.task))
        self.assertIn("state", str(ctx.exception))
        self.assertEqual(self.registry.evidence(self.task["task_id"]), ("COMPLETE", b"stored"))

    def test_transition_is_idempotent_and_leaves_no_evidence(self):
        self.enter_pending()
        self.assertEqual(self.registry.expire_bridge_pending(self.task["task_id"], digest(self.task)),
                         "EXPIRED")
        self.assertEqual(self.registry.evidence(self.task["task_id"]), (BRIDGE_EXPIRED, None))
        self.assertEqual(self.registry.expire_bridge_pending(self.task["task_id"], digest(self.task)),
                         "ALREADY_EXPIRED")
        self.assertEqual(self.registry.evidence(self.task["task_id"]), (BRIDGE_EXPIRED, None))


class RuntimeBackedExpiryTests(BridgeFixture):
    """E, F, G -- the bridge lifecycle across the delivery window, with the real Runtime."""

    def setUp(self):
        super().setUp()
        self.install_registration(self.BOTH)
        runtime_module, supervisor_module = load_runtime_modules()
        self.supervisor_module = supervisor_module
        self.rt_db = os.path.join(self.tmpdir.name, "runtime.db")
        self.rt = runtime_module.Runtime(self.rt_db)
        self.tasks = MemoryTransport()
        self.evidence = MemoryTransport()
        self.task = self.make_task(RUNTIME_ACTION, task_id="rh-c1probe-window01")
        self.publish(self.task, self.tasks)

    def service(self):
        import runtime_bridge_service as service
        return service.process_once(self.inbox, self.outbox, self.rt, self.rt_db)

    def drain(self, ticks=4):
        for _ in range(ticks):
            self.supervisor_module.Supervisor(
                self.rt, self.supervisor_module.NoopWorker(),
                task_kinds=("RUNTIME_PROBE",)).tick()

    def runtime_task_ids(self):
        connection = sqlite3.connect(self.rt_db)
        try:
            return [r[0] for r in connection.execute("SELECT task_id FROM tasks ORDER BY rowid")]
        finally:
            connection.close()

    def enter_pending(self):
        results = self.poll(self.tasks, self.evidence, bridge=self.bridge, clock=ACTIVE_CLOCK)
        self.assertEqual(results, [(self.task["task_id"], BRIDGE_PENDING)])
        self.assertEqual(self.registry.evidence(self.task["task_id"]), (BRIDGE_PENDING, None))
        self.assertEqual(self.evidence.writes, 0)

    # ---- E -----------------------------------------------------------------
    def test_e_completed_c1_probe_replays_after_its_window_closed(self):
        self.enter_pending()
        self.service()
        self.drain()
        self.assertEqual(self.service()["completed"], 1)
        self.assertEqual(self.poll(self.tasks, self.evidence, bridge=self.bridge, clock=ACTIVE_CLOCK),
                         [(self.task["task_id"], "EVIDENCE_PUBLISHED")])
        receipt = self.evidence.store["evidence/" + self.task["task_id"] + ".json"]
        writes = self.evidence.writes
        runtime_tasks = self.runtime_task_ids()
        self.assertEqual(len(runtime_tasks), 1)

        # Past the window: the receipt is replayed, nothing is re-bridged or re-enqueued.
        self.assertEqual(self.poll(self.tasks, self.evidence, bridge=ExplodingBridge(),
                                   clock=REGISTRATION_VALID_CLOCK),
                         [(self.task["task_id"], "EVIDENCE_PUBLISHED")])
        self.assertEqual(self.evidence.writes, writes)
        self.assertEqual(self.evidence.store["evidence/" + self.task["task_id"] + ".json"], receipt)
        self.assertEqual(self.registry.evidence(self.task["task_id"]), ("COMPLETE", receipt))
        self.assertEqual(self.runtime_task_ids(), runtime_tasks)
        self.assertEqual(self.service()["completed"], 1)

    # ---- F -----------------------------------------------------------------
    def test_f_pending_bridge_task_expires_without_evidence(self):
        self.enter_pending()
        inbox_path = os.path.join(self.inbox, self.task["task_id"] + ".json")
        inbox_bytes = read_bytes(inbox_path)

        self.assertEqual(self.poll(self.tasks, self.evidence, bridge=ExplodingBridge(),
                                   clock=REGISTRATION_VALID_CLOCK),
                         [(self.task["task_id"], "BRIDGE_EXPIRED")])
        self.assertEqual(self.registry.evidence(self.task["task_id"]), (BRIDGE_EXPIRED, None))
        self.assertEqual(self.evidence.writes, 0)
        self.assertEqual(read_bytes(inbox_path), inbox_bytes)
        self.assertEqual(self.runtime_task_ids(), [])
        self.assertFalse(os.path.isdir(self.outbox) and os.listdir(self.outbox))

    # ---- G -----------------------------------------------------------------
    def test_g_repeated_passes_after_bridge_expiry_stay_inert(self):
        self.enter_pending()
        self.assertEqual(self.poll(self.tasks, self.evidence, bridge=ExplodingBridge(),
                                   clock=REGISTRATION_VALID_CLOCK),
                         [(self.task["task_id"], "BRIDGE_EXPIRED")])
        inbox_path = os.path.join(self.inbox, self.task["task_id"] + ".json")
        before_bytes = read_bytes(inbox_path)
        before_mtime = os.stat(inbox_path).st_mtime_ns

        for _ in range(3):
            self.assertEqual(self.poll(self.tasks, self.evidence, bridge=ExplodingBridge(),
                                       clock=REGISTRATION_VALID_CLOCK),
                             [(self.task["task_id"], "BRIDGE_EXPIRED")])
        self.assertEqual(read_bytes(inbox_path), before_bytes)
        self.assertEqual(os.stat(inbox_path).st_mtime_ns, before_mtime)
        self.assertEqual(self.evidence.writes, 0)
        self.assertEqual(self.runtime_task_ids(), [])
        self.assertEqual(self.registry.evidence(self.task["task_id"]), (BRIDGE_EXPIRED, None))
        # The bridge service finds the request but never a terminal result it may publish.
        self.assertEqual(self.service()["pending"], 1)


class MixedObjectPassTests(BridgeFixture):
    """One poisoning candidate must not disturb the healthy objects around it."""

    def setUp(self):
        super().setUp()
        self.tasks = MemoryTransport()
        self.evidence = MemoryTransport()

    def test_expired_object_and_completed_objects_coexist_in_one_pass(self):
        self.install_registration(self.BOTH)
        done = self.make_task(HOST_ACTION, task_id="rh-probe-healthy01")
        self.publish(done, self.tasks)
        self.assertEqual(self.poll(self.tasks, self.evidence), [(done["task_id"], "EVIDENCE_PUBLISHED")])
        receipt = self.evidence.store["evidence/" + done["task_id"] + ".json"]
        writes = self.evidence.writes

        stale = self.make_task(HOST_ACTION, task_id="rh-probe-stale01")
        future = self.make_task(HOST_ACTION, task_id="rh-probe-notyet01",
                                issued_at=1500, expires_at=1700)
        self.publish(stale, self.tasks)
        self.publish(future, self.tasks)

        results = dict(self.poll(self.tasks, self.evidence, bridge=ExplodingBridge(),
                                 clock=REGISTRATION_VALID_CLOCK))
        self.assertEqual(results, {done["task_id"]: "EVIDENCE_PUBLISHED",
                                   stale["task_id"]: "EXPIRED_IGNORED",
                                   future["task_id"]: "NOT_YET_VALID"})
        self.assertEqual(self.evidence.writes, writes)          # nothing new written
        self.assertEqual(self.evidence.store["evidence/" + done["task_id"] + ".json"], receipt)
        self.assertIsNone(self.registry.evidence(stale["task_id"]))
        self.assertIsNone(self.registry.evidence(future["task_id"]))


if __name__ == "__main__":
    unittest.main()
