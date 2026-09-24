import copy
import hashlib
import hmac
import unittest

from acceptance_gate import (C13_ACTION, C14_ACTION, C13_ENVIRONMENT,
                             C14_ENVIRONMENT, Refusal)
from task_evidence import canonical, issue_task, read_evidence


BASE = {"candidate_sha": "a" * 40, "application_tree": "b" * 40,
        "test_scope_sha256": "c" * 64, "network": "disabled", "providers": "disabled",
        "payments": "disabled", "deployment": "disabled", "production": "disabled"}
C13 = {**BASE, "action_id": C13_ACTION, "environment": C13_ENVIRONMENT,
       "runner_id": "independent-c13"}
C14 = {**BASE, "action_id": C14_ACTION, "environment": C14_ENVIRONMENT,
       "runner_id": "independent-hk-c14", "c13_evidence_sha256": "d" * 64}


class MemoryHost:
    """Isolated directory stand-in; these bytes are not a real bus or Runner."""
    def __init__(self):
        self.tasks = {}
        self.evidence = {}
        self.artifacts = {}
        self.secret = b"isolated-test-only"

    def sign_task(self, raw):
        return hmac.new(self.secret, raw, "sha256").hexdigest()

    def verify_task_signature(self, raw, signature):
        return hmac.compare_digest(self.sign_task(raw), signature)

    def publish_task(self, task_id, envelope):
        if task_id in self.tasks:
            if self.tasks[task_id] != envelope:
                raise Refusal("task_collision")
            return
        self.tasks[task_id] = copy.deepcopy(envelope)

    def read_task(self, task_id):
        return copy.deepcopy(self.tasks[task_id])

    def read_evidence(self, task_id):
        return copy.deepcopy(self.evidence[task_id])

    def verify_runner_signature(self, runner_id, raw, signature):
        return runner_id in ("independent-c13", "independent-hk-c14") and self.verify_task_signature(raw, signature)

    def read_artifact(self, task_id, name):
        return self.artifacts[(task_id, name)]

    def complete(self, task, verdict="PASS_SCOPED"):
        payload = task["payload"]
        task_id = payload["task_id"]
        digest_fields = {}
        for name, raw in {"junit": b"<testsuite tests='1' failures='0' errors='0' skipped='0'/>",
                          "stdout": b"1 passed\n"}.items():
            self.artifacts[(task_id, name)] = raw
            digest_fields[name + "_sha256"] = hashlib.sha256(raw).hexdigest()
        manifest = {k: payload[k] for k in ("task_id", "action_id", "environment", "runner_id",
                                             "candidate_sha", "application_tree", "test_scope_sha256")}
        manifest.update({"junit_sha256": digest_fields["junit_sha256"],
                         "stdout_sha256": digest_fields["stdout_sha256"],
                         "command": "frozen-test-command"})
        raw = canonical(manifest)
        self.artifacts[(task_id, "manifest")] = raw
        digest_fields["manifest_sha256"] = hashlib.sha256(raw).hexdigest()
        evidence = {k: payload[k] for k in ("task_id", "action_id", "environment", "runner_id",
                                             "candidate_sha", "application_tree", "test_scope_sha256")}
        if payload["action_id"] == C14_ACTION:
            evidence["c13_evidence_sha256"] = payload["c13_evidence_sha256"]
        evidence.update({**digest_fields, "verdict": verdict, "test_count": 1,
                         "failure_count": 0, "error_count": 0, "skipped_count": 0})
        self.evidence[task_id] = {"payload": evidence,
                                  "signature": self.sign_task(canonical(evidence))}


class ProtocolTests(unittest.TestCase):
    def assert_refused(self, reason, fn):
        with self.assertRaises(Refusal) as got:
            fn()
        self.assertEqual(str(got.exception), reason)

    def test_c13_signed_task_and_raw_evidence_readback(self):
        host = MemoryHost()
        task = issue_task(C13, 100, host)
        host.complete(task)
        self.assertEqual(read_evidence(task, C13, 101, host)["verdict"], "PASS_SCOPED")
        self.assertEqual(host.read_task(task["payload"]["task_id"]), task)

    def test_c14_task_and_evidence_bind_prior_c13_digest(self):
        host = MemoryHost()
        task = issue_task(C14, 100, host)
        host.complete(task)
        self.assertEqual(read_evidence(task, C14, 101, host)["c13_evidence_sha256"], "d" * 64)
        bad = {**C14, "c13_evidence_sha256": "e" * 64}
        self.assert_refused("c13_prerequisite", lambda: read_evidence(task, bad, 101, host))

    def test_c14_without_verified_c13_admission_is_refused(self):
        host = MemoryHost()
        self.assert_refused("c13_prerequisite", lambda: issue_task({k: v for k, v in C14.items()
                                                                     if k != "c13_evidence_sha256"}, 100, host))
        self.assertFalse(host.tasks)

    def test_identity_scope_capability_and_time_are_closed(self):
        host = MemoryHost()
        for change in ({"candidate_sha": "e" * 40}, {"test_scope_sha256": "e" * 64},
                       {"deployment": "enabled"}, {"environment": "HK-STAGING-01"}):
            with self.subTest(change=change):
                self.assert_refused("capability" if "deployment" in change else "source_or_scope_mismatch",
                                    lambda: read_evidence(issue_task(C13, 100, host),
                                                          {**C13, **change}, 101, host))
        task = issue_task(C13, 100, host)
        self.assert_refused("task_expired", lambda: read_evidence(task, C13, 2000, host))

    def test_signature_artifact_and_pass_counts_fail_closed(self):
        host = MemoryHost()
        task = issue_task(C13, 100, host)
        host.complete(task)
        task_id = task["payload"]["task_id"]
        host.artifacts[(task_id, "junit")] = b"tampered"
        self.assert_refused("artifact_integrity", lambda: read_evidence(task, C13, 101, host))
        host.complete(task)
        host.evidence[task_id]["signature"] = "invalid"
        self.assert_refused("evidence_signature", lambda: read_evidence(task, C13, 101, host))
        host.complete(task)
        evidence = host.evidence[task_id]["payload"]
        evidence["skipped_count"] = 1
        host.evidence[task_id]["signature"] = host.sign_task(canonical(evidence))
        self.assert_refused("junit_counts", lambda: read_evidence(task, C13, 101, host))

    def test_junit_and_manifest_must_match_signed_counts_and_task(self):
        host = MemoryHost()
        task = issue_task(C13, 100, host)
        host.complete(task)
        task_id = task["payload"]["task_id"]
        evidence = host.evidence[task_id]["payload"]
        evidence["test_count"] = 2
        host.evidence[task_id]["signature"] = host.sign_task(canonical(evidence))
        self.assert_refused("junit_counts", lambda: read_evidence(task, C13, 101, host))
        host.complete(task)
        manifest = host.artifacts[(task_id, "manifest")].replace(b'"candidate_sha":"' + b'a'*40,
                                                                  b'"candidate_sha":"' + b'e'*40)
        host.artifacts[(task_id, "manifest")] = manifest
        evidence = host.evidence[task_id]["payload"]
        evidence["manifest_sha256"] = hashlib.sha256(manifest).hexdigest()
        host.evidence[task_id]["signature"] = host.sign_task(canonical(evidence))
        self.assert_refused("manifest_binding", lambda: read_evidence(task, C13, 101, host))

    def test_task_bus_readback_tampering_is_refused(self):
        class TamperedHost(MemoryHost):
            def read_task(self, task_id):
                item = super().read_task(task_id)
                item["signature"] = "wrong"
                return item
        self.assert_refused("task_readback", lambda: issue_task(C13, 100, TamperedHost()))


if __name__ == "__main__":
    unittest.main()
