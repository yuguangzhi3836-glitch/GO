import base64
import hashlib
import unittest

from acceptance_gate import Refusal
from c14_isolated_runner import execute
from c13_attestation import CANDIDATE, TREE, SCOPE
from house_bridge import issue, receive_evidence
from test_house_bridge import Host

PINNED_REQUEST = {"candidate_sha": CANDIDATE, "application_tree": TREE,
                  "test_scope_sha256": SCOPE, "c13_evidence_reference": "host-evidence://c13/1"}


class RunnerHost(Host):
    def __init__(self):
        super().__init__()
        self.evidence.update(candidate_sha=CANDIDATE, application_tree=TREE,
                             test_scope_sha256=SCOPE)

    def authorize_candidate(self, sha, tree):
        return (sha, tree) == (CANDIDATE, TREE)

    def registered_runner_id(self):
        return "hk-c14"

    def task_is_fresh(self, task, epoch):
        return epoch == 101

    def claim_task_once(self, task_id, nonce):
        if not hasattr(self, "claims"):
            self.claims = set()
        key = task_id, nonce
        if key in self.claims:
            return False
        self.claims.add(key)
        return True

    def run_fixed_isolated_suite(self, sha, tree, commands):
        self.seen_commands = commands
        return {"candidate_sha": sha, "application_tree": tree,
                "test_scope_sha256": SCOPE,
                "postgres_version": "18.4", "network": False, "providers": False,
                "payments": False, "deployment": False, "production": False,
                "junit": b"<testsuites><testsuite tests='61' failures='0' errors='0' skipped='0'/>"
                         b"<testsuite tests='10' failures='0' errors='0' skipped='0'/></testsuites>",
                "stdout": b"frozen suite 71 passed; PostgreSQL 18.4\n"}

    def agent_version(self):
        return "synthetic-agent"

    def runner_version(self):
        return "synthetic-runner"

    def sign_acceptance_evidence(self, raw):
        return base64.b64encode(hashlib.sha256(b"hk-c14" + raw).digest()).decode()

    def publish_house_artifact(self, task_id, nonce, name, blob):
        self.artifacts[(task_id, nonce, name)] = blob

    def publish_house_evidence(self, task_id, nonce, raw):
        self.results[(task_id, nonce)] = raw


class RunnerTests(unittest.TestCase):
    def test_signed_c14_evidence_and_command_center_receipt(self):
        host = RunnerHost()
        task = issue(PINNED_REQUEST, "C14", 100, host)
        evidence = execute(task, 101, host)
        self.assertEqual(evidence["executor_result"]["test_count"], 71)
        self.assertEqual(len(host.seen_commands), 2)
        self.assertEqual(receive_evidence(task, 101, host)["receipt"]["verdict"], "PASS_SCOPED")
        with self.assertRaisesRegex(Refusal, "runner_replay"):
            execute(task, 101, host)

    def test_caller_command_and_untrusted_task_are_refused(self):
        host = RunnerHost()
        task = issue(PINNED_REQUEST, "C14", 100, host)
        task["parameters"] = {**task["parameters"], "command": "deploy"}
        with self.assertRaisesRegex(Refusal, "runner_scope"):
            execute(task, 101, host)
        self.assertFalse(hasattr(host, "claims"))

    def test_isolation_mismatch_refused_without_publishing_evidence(self):
        class BadHost(RunnerHost):
            def run_fixed_isolated_suite(self, sha, tree, commands):
                return {**super().run_fixed_isolated_suite(sha, tree, commands), "network": True}
        host = BadHost()
        task = issue(PINNED_REQUEST, "C14", 100, host)
        with self.assertRaisesRegex(Refusal, "runner_isolation"):
            execute(task, 101, host)
        self.assertFalse(host.results)


if __name__ == "__main__":
    unittest.main()
