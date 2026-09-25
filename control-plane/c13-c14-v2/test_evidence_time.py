"""Synthetic signatures only: exercise temporal refusal, never real verdicts."""
import base64
import hashlib
import json
import unittest

from acceptance_gate import Refusal
from c14_isolated_runner import execute
from evidence_time import utc_epoch
from house_bridge import canonical, iso, issue, receive_evidence
from test_c14_isolated_runner import PINNED_REQUEST, RunnerHost
from test_house_bridge import Host, REQUEST


class EvidenceTimeTests(unittest.TestCase):
    def complete(self):
        host = Host()
        task = issue(REQUEST, "C14", 100, host)
        host.complete(task)
        return host, task

    def change_evidence(self, host, task, **changes):
        key = task["task_id"], task["nonce"]
        value = json.loads(host.results[key])
        value.update(changes)
        value.pop("signature")
        value["signature"] = base64.b64encode(hashlib.sha256(
            task["parameters"]["runner_id"].encode() + canonical(value)).digest()).decode()
        host.results[key] = canonical(value) + b"\n"

    def change_receipt(self, host, task, when):
        key = task["task_id"], task["nonce"]
        value = json.loads(host.receipts[key])
        value["verified_at"] = when
        value.pop("signature")
        value["signature"] = host.sign_control_receipt(canonical(value))
        host.receipts[key] = canonical(value) + b"\n"

    def test_wire_timestamp_rejects_ambiguous_or_invalid_values(self):
        invalid = [None, True, 101, {}, "1970-01-01", "1970-01-01T00:01:41",
                   "1970-01-01T00:01:41+00:00", "1970-01-01T00:01:41.1Z",
                   "1970-02-30T00:00:00Z", "1970-01-01T00:00:60Z"]
        for value in invalid:
            with self.subTest(value=value), self.assertRaisesRegex(Refusal, "time_invalid"):
                utc_epoch(value, "time_invalid")
        self.assertEqual(utc_epoch("1970-01-01T00:01:41Z", "time_invalid"), 101)

    def test_signed_future_completion_refused_before_receipt(self):
        host, task = self.complete()
        self.change_evidence(host, task, completed_at=iso(102))
        with self.assertRaisesRegex(Refusal, "evidence_time"):
            receive_evidence(task, 101, host)
        self.assertFalse(host.receipts)

    def test_signed_future_start_refused(self):
        host, task = self.complete()
        self.change_evidence(host, task, started_at=iso(102), completed_at=iso(102))
        with self.assertRaisesRegex(Refusal, "evidence_time"):
            receive_evidence(task, 101, host)

    def test_signed_missing_timezone_refused(self):
        host, task = self.complete()
        self.change_evidence(host, task, completed_at="1970-01-01T00:01:40")
        with self.assertRaisesRegex(Refusal, "evidence_time"):
            receive_evidence(task, 101, host)

    def test_signed_task_bad_time_is_refusal_not_unhandled_exception(self):
        host, task = self.complete()
        task["issued_at"] = None
        task["signature"] = host.sign_house_task(canonical(
            {key: value for key, value in task.items() if key != "signature"}))
        host.tasks[task["task_id"]] = canonical(task) + b"\n"
        with self.assertRaisesRegex(Refusal, "task_time"):
            receive_evidence(task, 101, host)

    def test_signed_receipt_cannot_precede_evidence_or_postdate_readback(self):
        for when in (iso(99), iso(102), "1970-01-01T00:01:41", None):
            with self.subTest(when=when):
                host, task = self.complete()
                receive_evidence(task, 101, host)
                self.change_receipt(host, task, when)
                with self.assertRaisesRegex(Refusal, "receipt_time"):
                    receive_evidence(task, 101, host)

    def test_completed_evidence_and_receipt_can_be_read_after_task_expiry(self):
        host, task = self.complete()
        first = receive_evidence(task, 101, host)
        self.assertEqual(receive_evidence(task, 10000, host), first)

    def test_runner_records_clock_after_sandbox(self):
        host = RunnerHost()
        host.now_epoch = lambda: 120
        task = issue(PINNED_REQUEST, "C14", 100, host)
        evidence = execute(task, 101, host)
        self.assertEqual(evidence["started_at"], iso(101))
        self.assertEqual(evidence["completed_at"], iso(120))
        self.assertEqual(receive_evidence(task, 121, host)["receipt"]["verdict"], "PASS_SCOPED")

    def test_runner_bad_clock_retains_claim_without_evidence(self):
        for value in (100, 3702, None, True, 101.0):
            with self.subTest(value=value):
                host = RunnerHost()
                host.now_epoch = lambda: value
                task = issue(PINNED_REQUEST, "C14", 100, host)
                with self.assertRaisesRegex(Refusal, "runner_completion_time"):
                    execute(task, 101, host)
                self.assertFalse(host.results)
                self.assertFalse(host.artifacts)
                with self.assertRaisesRegex(Refusal, "runner_replay"):
                    execute(task, 101, host)

    def test_runner_missing_clock_refused_before_claim(self):
        host = RunnerHost()
        host.now_epoch = None
        task = issue(PINNED_REQUEST, "C14", 100, host)
        with self.assertRaisesRegex(Refusal, "runner_clock_unavailable"):
            execute(task, 101, host)
        self.assertFalse(hasattr(host, "claims"))

    def test_runner_core_enforces_expiry_even_if_host_freshness_is_wrong(self):
        for epoch in (99, 1001):
            host = RunnerHost()
            host.task_is_fresh = lambda task, epoch: True
            task = issue(PINNED_REQUEST, "C14", 100, host)
            with self.subTest(epoch=epoch), self.assertRaisesRegex(Refusal, "runner_task_time"):
                execute(task, epoch, host)
            self.assertFalse(hasattr(host, "claims"))


if __name__ == "__main__":
    unittest.main()
