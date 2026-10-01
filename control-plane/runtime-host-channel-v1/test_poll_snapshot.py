"""Contract tests for the per-pass read snapshot used by flow.poll_once.

Offline only: in-memory counting stores, temporary SQLite, a local bare Git
fixture, in-memory keys. No network, no SSH, no Task or Evidence publication.

The counting store mirrors GitTransport's cost model: keys(), read(), create()
and snapshot() each cost exactly one repository clone, and the objects returned
by snapshot() do not.
"""
import contextlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from channel import *
from flow import *
from git_transport import GitTransport
import test_flow as fixtures


class _View:
    """Read-only snapshot view: no clone, and no write surface."""

    __slots__ = ("_store",)

    def __init__(self, store):
        self._store = store

    def keys(self):
        return sorted(self._store.store)

    def read(self, key):
        return self._store.store.get(key)


class CountingStore:
    """Clone-counting stand-in for GitTransport."""

    def __init__(self, initial=None):
        self.store = dict(initial or {})
        self.clones = 0
        self.snapshot_calls = 0

    def keys(self):
        self.clones += 1
        return sorted(self.store)

    def read(self, key):
        self.clones += 1
        return self.store.get(key)

    def create(self, key, raw):
        self.clones += 1
        if key in self.store:
            if self.store[key] != raw:
                raise Reject("conflict")
            return
        self.store[key] = raw

    @contextlib.contextmanager
    def snapshot(self):
        self.clones += 1
        self.snapshot_calls += 1
        yield _View(self)


class SnapshotPollTests(fixtures.FlowTests):
    def setUp(self):
        super().setUp()
        self.tasks = CountingStore()
        self.evidence = CountingStore()
        self.probe_calls = 0
        real_probe = self.registry.probe

        def counting_probe(*args, **kwargs):
            self.probe_calls += 1
            return real_probe(*args, **kwargs)

        self.registry.probe = counting_probe

    def task_key_path(self, task=None):
        return "tasks/" + (task or self.task)["task_id"] + ".json"

    def evidence_key_path(self, task=None):
        return "evidence/" + (task or self.task)["task_id"] + ".json"

    def extra_task(self, index):
        task = dict(self.task)
        task["task_id"] = "fixture-task-%02d" % index
        task["nonce"] = "fixture-nonce-%02d" % index
        return task

    def publish_task(self, task=None):
        self.tasks.store[self.task_key_path(task)] = signed(task or self.task, self.task_key)

    def complete(self, task=None, receipt=b"stored-receipt-bytes"):
        task = task or self.task
        self.registry.db.execute("INSERT OR REPLACE INTO tasks VALUES (?,?,?,'COMPLETE',?)",
                                 (task["task_id"], task["nonce"], digest(task), receipt))
        self.publish_task(task)
        self.evidence.store[self.evidence_key_path(task)] = receipt
        return receipt

    def reset_counters(self):
        self.tasks.clones = self.evidence.clones = 0
        self.tasks.snapshot_calls = self.evidence.snapshot_calls = 0
        self.probe_calls = 0

    # ---- A: retained completed task ---------------------------------------
    def test_a_completed_task_costs_one_clone_per_repository(self):
        receipt = self.complete()
        before = dict(self.evidence.store)
        results = self.poll()
        self.assertEqual(results, [(self.task["task_id"], "EVIDENCE_PUBLISHED")])
        self.assertEqual(self.tasks.clones, 1)
        self.assertEqual(self.evidence.clones, 1)
        self.assertEqual(self.tasks.snapshot_calls, 1)
        self.assertEqual(self.evidence.snapshot_calls, 1)
        self.assertEqual(self.probe_calls, 0)
        self.assertEqual(self.evidence.store, before)  # bytes unchanged
        self.assertEqual(self.registry.evidence(self.task["task_id"]),
                         ("COMPLETE", receipt))

    # ---- B: several completed tasks ---------------------------------------
    def test_b_clone_count_does_not_grow_with_task_count(self):
        tasks = [self.task, self.extra_task(2), self.extra_task(3)]
        for task in tasks:
            self.complete(task)
        results = self.poll()
        self.assertEqual(sorted(results), sorted((t["task_id"], "EVIDENCE_PUBLISHED")
                                                 for t in tasks))
        self.assertEqual(self.tasks.clones, 1)
        self.assertEqual(self.evidence.clones, 1)
        self.assertEqual(self.evidence.snapshot_calls, 1)

    # ---- C: no task --------------------------------------------------------
    def test_c_no_task_clones_tasks_once_and_evidence_not_at_all(self):
        results = self.poll()
        self.assertEqual(results, [])
        self.assertEqual(self.tasks.clones, 1)
        self.assertEqual(self.evidence.clones, 0)
        self.assertEqual(self.evidence.snapshot_calls, 0)

    # ---- D: new task, no Evidence yet -------------------------------------
    def test_d_new_task_executes_once_and_writes_evidence_once(self):
        self.publish_task()
        results = self.poll()
        self.assertEqual(results, [(self.task["task_id"], "EVIDENCE_PUBLISHED")])
        self.assertEqual(self.probe_calls, 1)
        # snapshot + create + the mandatory fresh post-write readback
        self.assertEqual(self.evidence.clones, 3)
        self.assertEqual(self.evidence.snapshot_calls, 1)
        state, stored = self.registry.evidence(self.task["task_id"])
        self.assertEqual(state, "COMPLETE")
        self.assertEqual(self.evidence.store[self.evidence_key_path()], stored)

    def test_d2_second_pass_does_not_re_execute_or_rewrite(self):
        self.publish_task()
        self.poll()
        after_first = dict(self.evidence.store)
        self.reset_counters()
        results = self.poll()
        self.assertEqual(results, [(self.task["task_id"], "EVIDENCE_PUBLISHED")])
        self.assertEqual(self.probe_calls, 0)          # never executed twice
        self.assertEqual(self.evidence.store, after_first)
        self.assertEqual(self.tasks.clones, 1)
        self.assertEqual(self.evidence.clones, 1)

    def test_d3_receipt_loss_still_reuses_the_stored_bytes(self):
        self.publish_task()
        self.poll()
        state, stored = self.registry.evidence(self.task["task_id"])
        self.evidence.store.pop(self.evidence_key_path())
        self.reset_counters()
        self.poll()
        self.assertEqual(self.probe_calls, 0)
        self.assertEqual(self.evidence.store[self.evidence_key_path()], stored)
        self.assertEqual(self.evidence.clones, 3)      # snapshot + create + readback

    # ---- E: conflicting remote Evidence -----------------------------------
    def test_e_conflicting_remote_evidence_is_rejected_and_not_overwritten(self):
        self.complete()
        key = self.evidence_key_path()
        self.evidence.store[key] = b"different-bytes"
        with self.assertRaises(Reject):
            self.poll()
        self.assertEqual(self.evidence.store[key], b"different-bytes")

    # ---- retained semantics ------------------------------------------------
    def test_task_digest_rebound_is_still_rejected(self):
        self.complete()
        other = dict(self.task)
        other["issued_at"] = self.task["issued_at"] - 1
        self.tasks.store[self.task_key_path()] = signed(other, self.task_key)
        self.assertNotEqual(digest(other), digest(self.task))
        with self.assertRaises(Reject):
            self.poll()

    def test_task_path_binding_is_still_enforced(self):
        task = dict(self.task)
        task["task_id"] = "fixture-task-mismatch"
        self.tasks.store["tasks/" + self.task["task_id"] + ".json"] = signed(task, self.task_key)
        with self.assertRaises(Reject):
            self.poll()

    def test_claimed_but_incomplete_task_stays_uncertain_and_untouched(self):
        """A pass with only a claimed-but-incomplete task never executes it and never
        writes Evidence. Both snapshots are still opened at most once for the pass."""
        self.registry.db.execute("INSERT INTO tasks VALUES (?,?,?,'CLAIMED',NULL)",
                                 (self.task["task_id"], self.task["nonce"], digest(self.task)))
        self.publish_task()
        results = self.poll()
        self.assertEqual(results, [(self.task["task_id"], "UNCERTAIN")])
        self.assertEqual(self.probe_calls, 0)
        self.assertEqual(self.tasks.snapshot_calls, 1)
        self.assertEqual(self.evidence.snapshot_calls, 1)
        self.assertEqual(self.evidence.store, {})  # nothing written
        self.assertEqual(self.registry.evidence(self.task["task_id"]), ("CLAIMED", None))

    def test_wrong_environment_task_is_skipped(self):
        other = dict(self.task)
        other["environment"] = "SOME-OTHER-ENV"
        self.publish_task(other)
        self.assertEqual(self.poll(), [])

    def test_snapshot_helper_falls_back_for_in_memory_transports(self):
        class Plain:
            def keys(self):
                return []

            def read(self, key):
                return None
        with read_snapshot(Plain()) as view:
            self.assertEqual(view.keys(), [])


class RealGitSnapshotTests(unittest.TestCase):
    """The snapshot against a real bare repository. No network."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        seed, bare = root / "seed", root / "remote.git"
        subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
        (seed / "README").write_text("isolated fixture\n")
        subprocess.run(["git", "-C", str(seed), "add", "README"], check=True)
        subprocess.run(["git", "-C", str(seed), "-c", "user.name=Fixture",
                        "-c", "user.email=fixture@localhost", "commit", "-qm", "fixture"],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "clone", "--bare", "-q", str(seed), str(bare)], check=True)
        self.bare = str(bare)

    def tearDown(self):
        self.tmp.cleanup()

    def test_snapshot_reads_everything_from_a_single_clone(self):
        transport = GitTransport(self.bare, "main", "tasks", git_env=dict(os.environ))
        transport.create("tasks/fixture-task.json", b"one")
        transport.clones = 0
        with transport.snapshot() as view:
            self.assertEqual(view.keys(), ["tasks/fixture-task.json"])
            self.assertEqual(view.read("tasks/fixture-task.json"), b"one")
            self.assertIsNone(view.read("tasks/absent.json"))
            with self.assertRaises(Reject):
                view.read("evidence/fixture.json")
            with self.assertRaises(Reject):
                view.read("tasks/../../escape.json")
            self.assertFalse(hasattr(view, "create"))
            self.assertFalse(hasattr(view, "clone"))
        self.assertEqual(transport.clones, 1)

    def test_keys_and_read_are_unchanged_outside_a_snapshot(self):
        transport = GitTransport(self.bare, "main", "tasks", git_env=dict(os.environ))
        transport.create("tasks/fixture-task.json", b"one")
        transport.clones = 0
        self.assertEqual(transport.keys(), ["tasks/fixture-task.json"])
        self.assertEqual(transport.read("tasks/fixture-task.json"), b"one")
        self.assertEqual(transport.clones, 2)  # one clone per call, as before


for _name in list(fixtures.FlowTests.__dict__):
    if _name.startswith("test_"):
        setattr(SnapshotPollTests, _name, None)


if __name__ == "__main__":
    unittest.main()
