"""Real durable CC claims; synthetic signatures and in-memory bus, no live Task."""
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest

from acceptance_gate import Refusal
from durable_claims import DurableClaims
from house_bridge import issue
from runtime_hosts import CommandCenterAcceptanceHost, CC_DISPATCH_STORE_ID
from test_runtime_hosts import DummyOpinions, DummyReceipts, bus

REQUEST = {"candidate_sha": "a" * 40, "application_tree": "b" * 40,
           "test_scope_sha256": "c" * 64, "c13_evidence_reference": "synthetic-c13"}


def host_for(path, *, fail=None, changed_review=False):
    opinions = DummyOpinions()
    if changed_review:
        original = opinions.verify_c13_evidence
        opinions.verify_c13_evidence = lambda ref: {**original(ref), "evidence_sha256": "e" * 64}
    def sign(raw):
        fd = os.open(str(path) + ".calls", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, b"s")
        finally:
            os.close(fd)
        if fail == "sign":
            raise RuntimeError("signer unavailable")
        return "a" * 128
    def nonce():
        if fail == "crash":
            os._exit(23)
        return "fresh-nonce"
    host = CommandCenterAcceptanceHost(
        opinions=opinions, task_bus=bus("tasks", True),
        evidence_bus=bus("evidence", False), receipts=DummyReceipts(),
        task_signer=sign, task_verifier=lambda raw, sig: sig == "a" * 128,
        runner_verifier=lambda runner, raw, sig: False, nonce_source=nonce,
        dispatch_claims=DurableClaims(path, CC_DISPATCH_STORE_ID))
    stored = {}
    def publish(tid, raw):
        stored[tid] = raw
        if fail == "publish":
            raise RuntimeError("ack lost after publication")
    host.publish_house_task = publish
    host.read_house_task = lambda tid: stored[tid]
    return host


def process_attempt(path, fail, results):
    try:
        task = issue(REQUEST, "C14", 100, host_for(Path(path), fail=fail))
        results.put(task["task_id"])
    except Refusal as exc:
        results.put(str(exc))


class CCDispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "cc-dispatch.db"
        DurableClaims.provision(self.path, CC_DISPATCH_STORE_ID)

    def calls(self):
        p = Path(str(self.path) + ".calls")
        return p.read_bytes() if p.exists() else b""

    def test_repeat_and_reopened_host_never_sign_again(self):
        host = host_for(self.path)
        task = issue(REQUEST, "C14", 100, host)
        self.assertEqual(task["parameters"]["candidate_sha"], REQUEST["candidate_sha"])
        for other in (host, host_for(self.path), host_for(self.path, changed_review=True)):
            with self.assertRaisesRegex(Refusal, "c14_dispatch_already_claimed"):
                issue(REQUEST, "C14", 200, other)
        self.assertEqual(self.calls(), b"s")

    def test_signer_failure_consumes_attempt(self):
        with self.assertRaisesRegex(RuntimeError, "signer unavailable"):
            issue(REQUEST, "C14", 100, host_for(self.path, fail="sign"))
        with self.assertRaisesRegex(Refusal, "already_claimed"):
            issue(REQUEST, "C14", 100, host_for(self.path))
        self.assertEqual(self.calls(), b"s")

    def test_publication_ack_loss_never_creates_replacement(self):
        with self.assertRaisesRegex(RuntimeError, "ack lost"):
            issue(REQUEST, "C14", 100, host_for(self.path, fail="publish"))
        with self.assertRaisesRegex(Refusal, "already_claimed"):
            issue(REQUEST, "C14", 100, host_for(self.path))
        self.assertEqual(self.calls(), b"s")

    def test_c13_rejection_does_not_consume_scope(self):
        host = host_for(self.path)
        original = host.opinions.verify_c13_evidence
        host.opinions.verify_c13_evidence = lambda ref: {**original(ref), "verdict": "FAIL"}
        with self.assertRaisesRegex(Refusal, "c13_not_passed"):
            issue(REQUEST, "C14", 100, host)
        issue(REQUEST, "C14", 100, host_for(self.path))
        self.assertEqual(self.calls(), b"s")

    def test_missing_store_or_method_refuses_before_signing(self):
        host = host_for(self.path)
        host.dispatch_claims = None
        with self.assertRaisesRegex(Refusal, "dispatch_store_not_installed"):
            issue(REQUEST, "C14", 100, host)
        from test_house_bridge import Host
        old = Host()
        def missing(admission):
            raise AttributeError("not installed")
        old.claim_c14_dispatch_once = missing
        with self.assertRaisesRegex(Refusal, "dispatch_store_not_installed"):
            issue(REQUEST, "C14", 100, old)
        self.assertEqual(self.calls(), b"")

    def test_missing_database_is_not_automatically_recreated(self):
        self.path.unlink()  # disposable fixture only
        with self.assertRaisesRegex(Refusal, "claim_store_unavailable"):
            issue(REQUEST, "C14", 100, host_for(self.path))
        self.assertFalse(self.path.exists())
        self.assertEqual(self.calls(), b"")

    def test_concurrent_processes_sign_exactly_once(self):
        ctx = multiprocessing.get_context("spawn")
        results = ctx.Queue()
        processes = [ctx.Process(target=process_attempt, args=(str(self.path), None, results))
                     for _ in range(4)]
        for p in processes:
            p.start()
        for p in processes:
            p.join(15)
            self.assertEqual(p.exitcode, 0)
        values = [results.get(timeout=2) for _ in processes]
        self.assertEqual(values.count("c14_dispatch_already_claimed"), 3)
        self.assertEqual(self.calls(), b"s")
        results.close()

    def test_process_crash_after_claim_is_not_reissued(self):
        ctx = multiprocessing.get_context("spawn")
        results = ctx.Queue()
        p = ctx.Process(target=process_attempt, args=(str(self.path), "crash", results))
        p.start()
        p.join(15)
        self.assertEqual(p.exitcode, 23)
        with self.assertRaisesRegex(Refusal, "already_claimed"):
            issue(REQUEST, "C14", 100, host_for(self.path))
        self.assertEqual(self.calls(), b"")
        results.close()


if __name__ == "__main__":
    unittest.main()
