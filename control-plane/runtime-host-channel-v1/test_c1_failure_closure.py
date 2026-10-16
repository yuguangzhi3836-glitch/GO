"""Failure closure: bound evidence, bounded retries and one idempotent receipt."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import c1_dispatch_outbox as outbox_mod  # noqa: E402
import c1_execution_contract as contract  # noqa: E402
import c1_failure_closure as closure  # noqa: E402

TASK = "rt_" + "a" * 32
SOURCE = "b" * 40


def request(issue=478, task=TASK):
    payload = contract.build_task_payload(
        cell_id="C12", external_task_id="V83-R1-C12-01",
        objective="close failed executions", scope="bounded failure closure",
        source_anchor=SOURCE, issue_number=issue,
        allowed_owner_cs=contract.allowed_owner_cs_for_kind(contract.GHAW_BUILDER_KIND))
    return contract.build_dispatch_request(
        task, 1, contract.task_spec(contract.GHAW_BUILDER_KIND, payload))


class FakeClient:
    def __init__(self, *, job=None, log=None, log_error=None, post_errors=()):
        self.job = job or {
            "id": 77, "conclusion": "failure", "runner_id": 5,
            "started_at": "2026-10-05T00:00:00Z",
            "steps": [{"name": "Execute tests", "conclusion": "failure"}],
        }
        self.log = log or (
            "2026-10-05T00:00:01Z ##[group]Run python -m pytest tests/x.py\n"
            "2026-10-05T00:00:02Z ##[error]token=ghp_abcdefghijklmnop bad failure\n"
            "2026-10-05T00:00:03Z Process completed with exit code 2.\n")
        self.log_error = log_error
        self.post_errors = list(post_errors)
        self.comments = []
        self.log_reads = 0
        self.posts = 0

    def list_run_jobs(self, run_id, run_attempt):
        self.bound = (run_id, run_attempt)
        return [self.job]

    def download_job_log(self, job_id):
        self.log_reads += 1
        if self.log_error:
            raise contract.Refused(self.log_error)
        return self.log

    def issue_comment_contains(self, issue_number, marker):
        self.issue = issue_number
        return any(marker in body for body in self.comments)

    def post_issue_comment(self, issue_number, body):
        self.posts += 1
        if self.post_errors:
            raise contract.Refused(self.post_errors.pop(0))
        self.comments.append(body)
        return 1000 + self.posts


class FailureClosureCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "outbox.db")
        self.box = outbox_mod.DispatchOutbox(self.path)
        self.addCleanup(self.box.close)
        self.request = request()
        self.box.register(TASK, 1, request=self.request)
        self.run = {"id": 37357407389, "run_attempt": 1,
                    "head_sha": SOURCE, "conclusion": "failure"}

    def close(self, client):
        return closure.close_failed_run(self.request, self.run, self.box, client)

    def test_failed_command_exit_and_sanitized_error_are_published_once(self):
        client = FakeClient()
        report = self.close(client)
        self.assertEqual(report["status"], "PUBLISHED")
        self.assertEqual(report["diagnosis"]["first_failed_command"],
                         "python -m pytest tests/x.py")
        self.assertEqual(report["diagnosis"]["exit_code"], 2)
        self.assertNotIn("ghp_", client.comments[0])
        self.assertIn("[REDACTED]", client.comments[0])
        self.assertIn("run=", client.comments[0])
        self.assertEqual(client.posts, 1)

    def test_failed_command_is_the_group_owning_the_first_nonzero_exit(self):
        client = FakeClient(log=(
            "##[group]Run setup-cache\n"
            "setup ok\n"
            "Process completed with exit code 0.\n"
            "##[group]Run python -m pytest tests/failed.py\n"
            "assertion detail\n"
            "Process completed with exit code 1.\n"))
        report = self.close(client)
        self.assertEqual(report["diagnosis"]["first_failed_command"],
                         "python -m pytest tests/failed.py")
        self.assertEqual(report["diagnosis"]["exit_code"], 1)

        again = self.close(client)
        self.assertEqual(again["status"], "PUBLISHED")
        self.assertEqual(client.posts, 1, "a terminal durable receipt is not posted twice")

    def test_crash_window_reuses_the_marker_after_an_outbox_restart(self):
        client = FakeClient()
        # Model a POST that landed followed by a process crash before the outbox update.
        first = closure.close_failed_run(self.request, self.run, self.box, client)
        marker_comment = client.comments[0]
        self.box._update(self.request["execution_request_id"],  # noqa: SLF001
                         failure_receipt_json=None)
        self.box.close()
        self.box = outbox_mod.DispatchOutbox(self.path)
        client.comments = [marker_comment]

        reused = self.close(client)
        self.assertEqual(reused["status"], "REUSED")
        self.assertEqual(client.posts, 1)
        self.assertEqual(self.box.failure_receipt(
            self.request["execution_request_id"])["status"], "REUSED")

    def test_cancelled_before_runner_allocation_has_no_fake_command_or_exit(self):
        client = FakeClient(job={"id": 88, "conclusion": "cancelled", "runner_id": 0,
                                       "steps": [], "started_at": "2026-10-05T00:00:00Z"})
        report = self.close(client)
        self.assertEqual(report["diagnosis"]["classification"],
                         "EXTERNAL_RUNNER_BLOCKED")
        self.assertIsNone(report["diagnosis"]["first_failed_command"])
        self.assertIsNone(report["diagnosis"]["exit_code"])
        self.assertEqual(client.log_reads, 0)

    def test_expired_or_forbidden_log_is_reported_as_missing_evidence(self):
        client = FakeClient(log_error="GITHUB_HTTP_404")
        report = self.close(client)
        self.assertEqual(report["status"], "PUBLISHED")
        self.assertEqual(report["diagnosis"]["classification"], "EVIDENCE_BLOCKED")
        self.assertEqual(report["diagnosis"]["sanitized_error"], "GITHUB_HTTP_404")

    def test_job_list_permission_failure_is_published_as_evidence_blocked(self):
        client = FakeClient()
        client.list_run_jobs = lambda *_args: (_ for _ in ()).throw(
            contract.Refused("GITHUB_HTTP_403"))
        report = self.close(client)
        self.assertEqual(report["status"], "PUBLISHED")
        self.assertEqual(report["diagnosis"]["classification"], "EVIDENCE_BLOCKED")
        self.assertEqual(report["diagnosis"]["sanitized_error"], "GITHUB_HTTP_403")

    def test_comment_permission_failure_stops_immediately_and_is_durable(self):
        client = FakeClient(post_errors=("GITHUB_HTTP_403",))
        report = self.close(client)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["reason"], "GITHUB_HTTP_403")
        again = self.close(client)
        self.assertEqual(again["status"], "BLOCKED")
        self.assertEqual(client.posts, 1, "permission failures are not retried forever")

    def test_transient_comment_write_has_exactly_three_bounded_attempts(self):
        client = FakeClient(post_errors=("GITHUB_UNREACHABLE",) * 3)
        with self.assertRaises(closure.ReceiptRetry):
            self.close(client)
        with self.assertRaises(closure.ReceiptRetry):
            self.close(client)
        report = self.close(client)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("RECEIPT_RETRY_EXHAUSTED", report["reason"])
        self.assertEqual(client.posts, 3)
        self.assertEqual(self.close(client)["status"], "BLOCKED")
        self.assertEqual(client.posts, 3)

    def test_scope_block_is_assigned_to_the_path_owner_not_retried(self):
        client = FakeClient(log=(
            "##[group]Run safe outputs\n"
            "Result: BLOCKED BY CELL SCOPE\n"
            "##[error]BUILDER_PATCH_GUARD=FAIL reason=NO_CHANGED_PATHS\n"
            "Process completed with exit code 1.\n"))
        report = self.close(client)
        self.assertEqual(report["diagnosis"]["classification"], "OWNERSHIP_BLOCKED")
        self.assertIn("repository owner", report["diagnosis"]["next_action"])
        self.assertEqual(client.posts, 1)

    def test_missing_source_issue_is_blocked_without_guessing_a_target(self):
        other_task = "rt_" + "c" * 32
        no_issue = request(issue=None, task=other_task)
        self.box.register(other_task, 1, request=no_issue)
        no_issue_run = dict(self.run, id=4)
        report = closure.close_failed_run(no_issue, no_issue_run, self.box, FakeClient())
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["reason"], "SOURCE_ISSUE_UNBOUND")


if __name__ == "__main__":
    unittest.main()
