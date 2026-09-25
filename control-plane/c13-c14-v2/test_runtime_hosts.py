import tempfile
import unittest
from pathlib import Path

from acceptance_gate import Refusal
from ai_acceptance_host import AIAdmissionHost
from control_receipt_route import ControlReceiptRoute
from docker_sandbox import DockerSandbox
from durable_claims import DurableClaims
from git_acceptance_bus import GitAcceptanceBus
from runtime_hosts import CommandCenterAcceptanceHost, HongKongAcceptanceHost


class DummyOpinions(AIAdmissionHost):
    def __init__(self):
        self.runner = type("Runner", (), {"actor_id": "hk-c14", "principal_id": "exec-c14"})()

    def authorize_candidate(self, sha, tree):
        return True

    def qualify_actor(self, role, sha):
        return {"id": "c13" if role == "C13" else "hk-c14", "role": role,
                "registered": True, "environment": "GO-ISOLATED-ACCEPTANCE-01" if role == "C13" else "HK-ISOLATED-ACCEPTANCE-01",
                "independent_of": ["implementation"] if role == "C13" else ["implementation", "c13"]}

    def verify_c13_evidence(self, reference):
        return {"candidate_sha": "a" * 40, "application_tree": "b" * 40,
                "test_scope_sha256": "c" * 64, "verdict": "PASS_SCOPED",
                "actor_id": "c13", "verified": True, "evidence_sha256": "d" * 64}

    def c14_review_identity(self):
        return "hk-c14", "exec-c14"

    def read_review_opinion(self, reference):
        return b"opinion"


class DummyReceipts(ControlReceiptRoute):
    def __init__(self):
        pass


class DummyClaims(DurableClaims):
    def __init__(self, runner_id):
        self.runner_id = runner_id
        self.claimed = set()

    def claim_task_once(self, task_id, nonce):
        key = task_id, nonce
        if key in self.claimed:
            return False
        self.claimed.add(key)
        return True


class DummySandbox(DockerSandbox):
    def __init__(self):
        pass


def bus(kind, write):
    return GitAcceptanceBus(Path("/tmp") / (kind + ("-w" if write else "-r")), kind,
                            write_enabled=write)


class RuntimeHostTests(unittest.TestCase):
    def test_wrong_bus_roles_and_claim_identity_fail_closed(self):
        common = dict(task_verifier=lambda raw, sig: True,
                      evidence_signer=lambda raw: "signature",
                      evidence_verifier=lambda runner, raw, sig: True,
                      agent_version="agent-v1", runner_version="runner-v1")
        with self.assertRaisesRegex(Refusal, "runtime_bus_role"):
            HongKongAcceptanceHost(runner_id="hk-c14", task_bus=bus("tasks", True),
                                   evidence_bus=bus("evidence", True), claims=DummyClaims("hk-c14"),
                                   sandbox=DummySandbox(), **common)
        with self.assertRaisesRegex(Refusal, "runtime_component"):
            HongKongAcceptanceHost(runner_id="hk-c14", task_bus=bus("tasks", False),
                                   evidence_bus=bus("evidence", True), claims=DummyClaims("other"),
                                   sandbox=DummySandbox(), **common)

    def test_cc_c13_digest_is_not_trusted_until_real_verification(self):
        host = CommandCenterAcceptanceHost(
            opinions=DummyOpinions(), task_bus=bus("tasks", True),
            evidence_bus=bus("evidence", False), receipts=DummyReceipts(),
            task_signer=lambda raw: "a" * 128,
            task_verifier=lambda raw, sig: sig == "a" * 128,
            runner_verifier=lambda runner, raw, sig: True,
            nonce_source=lambda: "fixed-nonce")
        admission = {"action_id": "HK_ISOLATED_C14_RETEST",
                     "environment": "HK-ISOLATED-ACCEPTANCE-01",
                     "c13_evidence_sha256": "d" * 64}
        self.assertFalse(host.verify_c13_prerequisite(admission))
        record = host.verify_c13_evidence("sha256:" + "e" * 64)
        self.assertTrue(record["verified"])
        self.assertTrue(host.verify_c13_prerequisite(admission))
        self.assertFalse(host.verify_c13_prerequisite({**admission, "c13_evidence_sha256": "e" * 64}))
        self.assertEqual(host.fresh_nonce(), "fixed-nonce")

    def test_hk_clock_claim_and_signature_are_bound_to_one_runner(self):
        host = HongKongAcceptanceHost(
            runner_id="hk-c14", task_bus=bus("tasks", False), evidence_bus=bus("evidence", True),
            claims=DummyClaims("hk-c14"), sandbox=DummySandbox(),
            task_verifier=lambda raw, sig: sig == "task",
            evidence_signer=lambda raw: "machine-signature",
            evidence_verifier=lambda runner, raw, sig: sig == "machine-signature",
            agent_version="agent-v1", runner_version="runner-v1", clock=lambda: 200)
        task = {"issued_at": "1970-01-01T00:01:40Z", "expires_at": "1970-01-01T00:04:10Z"}
        self.assertTrue(host.task_is_fresh(task, 200))
        self.assertFalse(host.task_is_fresh(task, 99))
        self.assertEqual(host.now_epoch(), 200)
        self.assertTrue(host.claim_task_once("go-c14-acceptance-" + "a" * 32, "nonce"))
        self.assertFalse(host.claim_task_once("go-c14-acceptance-" + "a" * 32, "nonce"))
        self.assertTrue(host.verify_acceptance_runner("hk-c14", b"x", "machine-signature"))
        self.assertFalse(host.verify_acceptance_runner("other", b"x", "machine-signature"))


if __name__ == "__main__":
    unittest.main()
