"""Exercise real local persistence and competing processes, never HK Tasks."""
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from acceptance_gate import Refusal
from durable_claims import DurableClaims


def compete(path, task_id, nonce):
    return DurableClaims(Path(path), "test-c14-ai").claim_task_once(task_id, nonce)


class DurableClaimTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "claims.sqlite3"
        self.store = DurableClaims.provision(self.path, "test-c14-ai")

    def test_duplicate_task_or_nonce_refused_after_reopen(self):
        self.assertTrue(self.store.claim_task_once("task-one", "nonce-one"))
        reopened = DurableClaims(self.path, "test-c14-ai")
        self.assertFalse(reopened.claim_task_once("task-one", "nonce-one"))
        self.assertFalse(reopened.claim_task_once("task-one", "nonce-two"))
        self.assertFalse(reopened.claim_task_once("task-two", "nonce-one"))
        self.assertTrue(reopened.claim_task_once("task-two", "nonce-two"))

    def test_only_one_process_can_claim(self):
        with ProcessPoolExecutor(max_workers=4, mp_context=multiprocessing.get_context("spawn")) as pool:
            results = list(pool.map(compete, [str(self.path)] * 12, ["task-race"] * 12, ["nonce-race"] * 12))
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 11)

    def test_committed_claim_survives_abrupt_process_exit(self):
        script = ("import os, sys; from pathlib import Path; from durable_claims import DurableClaims; "
                  "assert DurableClaims(Path(sys.argv[1]), 'test-c14-ai').claim_task_once('task-crash', 'nonce-crash'); "
                  "os._exit(17)")
        result = subprocess.run([sys.executable, "-c", script, str(self.path)],
                                cwd=Path(__file__).parent, capture_output=True)
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertFalse(self.store.claim_task_once("task-crash", "nonce-crash"))

    def test_runner_failure_cannot_reenter_sandbox_after_restart(self):
        from c14_isolated_runner import execute
        from house_bridge import issue
        from test_c14_isolated_runner import PINNED_REQUEST, RunnerHost

        host = RunnerHost()  # synthetic authority/sandbox, real durable claim
        task = issue(PINNED_REQUEST, "C14", 100, host)
        host.claim_task_once = self.store.claim_task_once
        calls = []

        def fail(*args):
            calls.append(args)
            raise RuntimeError("sandbox failed after claim")

        host.run_fixed_isolated_suite = fail
        with self.assertRaisesRegex(RuntimeError, "sandbox failed"):
            execute(task, 101, host)
        host.claim_task_once = DurableClaims(self.path, "test-c14-ai").claim_task_once
        with self.assertRaisesRegex(Refusal, "runner_replay"):
            execute(task, 101, host)
        self.assertEqual(len(calls), 1)
        self.assertFalse(host.results)

    def test_wrong_runner_and_reprovision_refused(self):
        with self.assertRaisesRegex(Refusal, "claim_store_identity"):
            DurableClaims(self.path, "different-runner").claim_task_once("task", "nonce")
        with self.assertRaisesRegex(Refusal, "claim_store_provision"):
            DurableClaims.provision(self.path, "test-c14-ai")

    def test_missing_or_corrupt_database_never_recreated(self):
        self.path.unlink()
        with self.assertRaisesRegex(Refusal, "claim_store_unavailable"):
            self.store.claim_task_once("task", "nonce")
        self.assertFalse(self.path.exists())
        self.path.write_bytes(b"corrupted")
        self.path.chmod(0o600)
        with self.assertRaisesRegex(Refusal, "claim_store_unavailable"):
            self.store.claim_task_once("task", "nonce")
        self.assertEqual(self.path.read_bytes(), b"corrupted")

    def test_links_and_shared_permissions_rejected(self):
        target = self.path.with_suffix(".real")
        self.path.rename(target)
        self.path.symlink_to(target)
        with self.assertRaisesRegex(Refusal, "claim_store_permissions"):
            self.store.claim_task_once("task", "nonce")
        self.path.unlink()
        target.rename(self.path)
        self.path.chmod(0o644)
        with self.assertRaisesRegex(Refusal, "claim_store_permissions"):
            self.store.claim_task_once("task", "nonce")

    def test_invalid_identifiers_rejected_before_writes(self):
        for task, nonce in (("", "nonce"), ("../task", "nonce"), ("task", ""), (True, "nonce"), ("task", "a" * 129)):
            with self.subTest(task=task, nonce=nonce), self.assertRaisesRegex(Refusal, "claim_identity"):
                self.store.claim_task_once(task, nonce)

    def test_accepts_full_house_nonce_alphabet(self):
        self.assertTrue(self.store.claim_task_once("task", "_-house-nonce"))


if __name__ == "__main__":
    unittest.main()
