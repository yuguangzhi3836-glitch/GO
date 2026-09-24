import unittest

from acceptance_gate import (
    C13_ACTION, C14_ACTION, C13_ENVIRONMENT, C14_ENVIRONMENT,
    Refusal, c13_admission, c14_admission,
)

SHA, TREE, SCOPE = "a" * 40, "b" * 40, "c" * 64
C13 = {"candidate_sha": SHA, "application_tree": TREE, "test_scope_sha256": SCOPE}
C14 = {**C13, "c13_evidence_reference": "host-evidence://c13/1"}


class Host:
    def __init__(self):
        self.allowed = True
        self.evidence = {**C13, "verdict": "PASS_SCOPED", "actor_id": "c13-runner",
                         "verified": True, "evidence_sha256": "d" * 64}
        self.runners = {
            "C13": {"id": "c13-runner", "role": "C13", "environment": C13_ENVIRONMENT,
                    "independent_of": ["implementation"], "registered": True},
            "C14": {"id": "hk-c14-runner", "role": "C14", "environment": C14_ENVIRONMENT,
                    "independent_of": ["implementation", "c13"], "registered": True},
        }

    def authorize_candidate(self, candidate_sha, application_tree):
        return self.allowed and (candidate_sha, application_tree) == (SHA, TREE)

    def qualify_actor(self, role, candidate_sha):
        return self.runners[role]

    def verify_c13_evidence(self, reference):
        return self.evidence


class GateTests(unittest.TestCase):
    def assert_refusal(self, reason, fn, request, host):
        with self.assertRaises(Refusal) as caught:
            fn(request, host)
        self.assertEqual(str(caught.exception), reason)

    def test_first_test_has_no_c14_dependency_or_release_authority(self):
        result = c13_admission(C13, Host())
        self.assertEqual(result["action_id"], C13_ACTION)
        self.assertEqual(result["environment"], C13_ENVIRONMENT)
        for permission in ("network", "providers", "payments", "deployment", "production"):
            self.assertEqual(result[permission], "disabled")
        self.assert_refusal("request_fields", c13_admission, {**C13, "c14_receipt_reference": "old"}, Host())

    def test_c14_uses_same_bound_source_and_remains_test_only(self):
        result = c14_admission(C14, Host())
        self.assertEqual((result["action_id"], result["environment"]), (C14_ACTION, C14_ENVIRONMENT))
        self.assertEqual(result["c13_evidence_sha256"], "d" * 64)
        for permission in ("network", "providers", "payments", "deployment", "production"):
            self.assertEqual(result[permission], "disabled")
        self.assert_refusal("request_fields", c14_admission, {**C14, "command": "deploy"}, Host())

    def test_refuse_mismatched_or_unverified_first_test(self):
        for field, bad, reason in (
            ("verified", False, "c13_not_passed"),
            ("verdict", "BLOCKED", "c13_not_passed"),
            ("candidate_sha", "e" * 40, "c13_binding"),
            ("application_tree", "e" * 40, "c13_binding"),
            ("test_scope_sha256", "e" * 64, "c13_binding"),
            ("evidence_sha256", "bad", "c13_evidence_digest"),
        ):
            with self.subTest(field=field):
                host = Host()
                host.evidence[field] = bad
                self.assert_refusal(reason, c14_admission, C14, host)

    def test_refuse_cross_role_or_unregistered_runner(self):
        host = Host()
        host.runners["C14"]["environment"] = "HK-STAGING-01"
        self.assert_refusal("actor_not_qualified", c14_admission, C14, host)
        host = Host()
        host.runners["C14"]["registered"] = False
        self.assert_refusal("actor_not_qualified", c14_admission, C14, host)
        host = Host()
        host.runners["C14"]["id"] = "c13-runner"
        self.assert_refusal("same_acceptance_actor", c14_admission, C14, host)

    def test_refuse_unapproved_source_and_missing_scope(self):
        host = Host()
        host.allowed = False
        self.assert_refusal("source_not_authorized", c13_admission, C13, host)
        self.assert_refusal("source_not_authorized", c14_admission, C14, host)
        self.assert_refusal("test_scope_digest", c13_admission, {**C13, "test_scope_sha256": "bad"}, Host())


if __name__ == "__main__":
    unittest.main()
