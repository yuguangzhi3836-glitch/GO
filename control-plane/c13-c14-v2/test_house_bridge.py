import base64
import copy
import hashlib
import json
import unittest
from pathlib import Path

from acceptance_gate import C13_ACTION, C14_ACTION, C13_ENVIRONMENT, C14_ENVIRONMENT, Refusal
from house_bridge import canonical, digest, issue, read_evidence

SHA, TREE, SCOPE = "a" * 40, "b" * 40, "c" * 64


class Host:
    """Memory only. No Task bus, HK Runner or real signing key."""
    def __init__(self):
        self.tasks = {}
        self.results = {}
        self.artifacts = {}
        self.c13_verified = True
        self.evidence = {"candidate_sha": SHA, "application_tree": TREE,
                         "test_scope_sha256": SCOPE, "verdict": "PASS_SCOPED",
                         "actor_id": "independent-c13", "verified": True,
                         "evidence_sha256": "d" * 64}

    def authorize_candidate(self, sha, tree):
        return (sha, tree) == (SHA, TREE)

    def qualify_actor(self, role, sha):
        return {"id": "independent-c13" if role == "C13" else "hk-c14",
                "role": role, "environment": C13_ENVIRONMENT if role == "C13" else C14_ENVIRONMENT,
                "independent_of": ["implementation"] if role == "C13" else ["implementation", "c13"],
                "registered": True}

    def verify_c13_evidence(self, reference):
        return copy.deepcopy(self.evidence)

    def verify_c13_prerequisite(self, admission):
        return self.c13_verified and admission["c13_evidence_sha256"] == self.evidence["evidence_sha256"]

    def fresh_nonce(self):
        return "host-generated-unique-nonce"

    def sign_house_task(self, raw):
        return hashlib.sha512(b"house-key:" + raw).hexdigest()

    def verify_house_task(self, raw, signature):
        return self.sign_house_task(raw) == signature

    def publish_house_task(self, task_id, raw):
        if task_id in self.tasks:
            raise Refusal("duplicate_task")
        self.tasks[task_id] = raw

    def read_house_task(self, task_id):
        return self.tasks[task_id]

    def verify_acceptance_runner(self, runner_id, raw, signature):
        expected = base64.b64encode(hashlib.sha256(runner_id.encode() + raw).digest()).decode()
        return signature == expected

    def read_house_evidence(self, task_id, nonce):
        return self.results[(task_id, nonce)]

    def read_house_artifact(self, task_id, nonce, name):
        return self.artifacts[(task_id, nonce, name)]

    def complete(self, task):
        task_id, nonce = task["task_id"], task["nonce"]
        junit = b"<testsuite tests='1' failures='0' errors='0' skipped='0'/>"
        stdout = b"1 passed\n"
        manifest = {"task_id": task_id, "nonce": nonce, **task["parameters"],
                    "junit_sha256": digest(junit), "stdout_sha256": digest(stdout),
                    "command": "registered frozen suite"}
        if "c13_evidence_sha256" in manifest:
            del manifest["c13_evidence_sha256"]
        blobs = {"junit": junit, "stdout": stdout, "manifest": canonical(manifest)}
        for name, raw in blobs.items():
            self.artifacts[(task_id, nonce, name)] = raw
        result = {**task["parameters"], "verdict": "PASS_SCOPED", "test_count": 1,
                  "failure_count": 0, "error_count": 0, "skipped_count": 0,
                  **{name + "_sha256": digest(raw) for name, raw in blobs.items()}}
        evidence = {"schema_version": "1", "task_id": task_id, "nonce": nonce,
                    "action_id": task["action_id"], "environment": task["environment"],
                    "status": "SUCCESS", "started_at": task["issued_at"],
                    "completed_at": task["issued_at"], "agent_version": "test-only",
                    "executor_version": "test-only", "executor_result": result,
                    "gate_results": {"isolated_acceptance": "PASS_SCOPED"},
                    "retry_permitted": False, "replay_authorized": False,
                    "authorizes_any_action": False}
        evidence["signature"] = base64.b64encode(hashlib.sha256(
            task["parameters"]["runner_id"].encode() + canonical(evidence)).digest()).decode()
        self.results[(task_id, nonce)] = canonical(evidence) + b"\n"


class HouseBridgeTests(unittest.TestCase):
    def refuse(self, reason, fn):
        with self.assertRaises(Refusal) as got:
            fn()
        self.assertEqual(str(got.exception), reason)

    def test_c13_house_task_and_signed_artifacts(self):
        host = Host()
        request = {"candidate_sha": SHA, "application_tree": TREE, "test_scope_sha256": SCOPE}
        task = issue(request, "C13", 100, host)
        self.assertEqual(set(task), {"schema_version", "task_id", "nonce", "issued_at",
                                     "expires_at", "authority", "environment", "action_id",
                                     "parameters", "signature"})
        self.assertEqual(task["action_id"], C13_ACTION)
        host.complete(task)
        self.assertEqual(read_evidence(task, 101, host)["verdict"], "PASS_SCOPED")
        self.assertEqual(read_evidence(task, 10_000, host)["verdict"], "PASS_SCOPED")

    def test_c14_requires_verified_c13_at_issuance(self):
        host = Host()
        request = {"candidate_sha": SHA, "application_tree": TREE, "test_scope_sha256": SCOPE,
                   "c13_evidence_reference": "host-evidence://c13/1"}
        host.c13_verified = False
        self.refuse("c13_prerequisite", lambda: issue(request, "C14", 100, host))
        self.assertFalse(host.tasks)
        host.c13_verified = True
        task = issue(request, "C14", 100, host)
        self.assertEqual(task["action_id"], C14_ACTION)
        self.assertEqual(task["parameters"]["c13_evidence_sha256"], "d" * 64)
        host.complete(task)
        self.assertEqual(read_evidence(task, 101, host)["verdict"], "PASS_SCOPED")

    def test_task_signature_and_readback_refuse_before_acceptance(self):
        host = Host()
        request = {"candidate_sha": SHA, "application_tree": TREE, "test_scope_sha256": SCOPE}
        task = issue(request, "C13", 100, host)
        host.complete(task)
        host.tasks[task["task_id"]] = b"altered"
        self.refuse("task_readback", lambda: read_evidence(task, 101, host))
        class BadSigner(Host):
            def verify_house_task(self, raw, signature):
                return False
        bad = BadSigner()
        self.refuse("task_signature", lambda: issue(request, "C13", 100, bad))
        self.assertFalse(bad.tasks)

    def test_evidence_and_raw_artifact_tamper_refuse(self):
        host = Host()
        task = issue({"candidate_sha": SHA, "application_tree": TREE,
                      "test_scope_sha256": SCOPE}, "C13", 100, host)
        host.complete(task)
        key = (task["task_id"], task["nonce"])
        host.artifacts[(*key, "junit")] = b"<testsuite tests='0'/>"
        self.refuse("artifact_integrity", lambda: read_evidence(task, 101, host))
        host.complete(task)
        evidence = __import__("json").loads(host.results[key])
        evidence["executor_result"]["candidate_sha"] = "e" * 40
        host.results[key] = canonical(evidence)
        self.refuse("evidence_signature", lambda: read_evidence(task, 101, host))

    def test_no_deploy_action_or_caller_command(self):
        host = Host()
        request = {"candidate_sha": SHA, "application_tree": TREE, "test_scope_sha256": SCOPE}
        self.refuse("request_fields", lambda: issue({**request, "command": "deploy"}, "C13", 100, host))
        self.refuse("role", lambda: issue(request, "HK_STAGING_DEPLOY", 100, host))
        self.assertFalse(host.tasks)

    def test_proposed_house_contract_preserves_legacy_environment(self):
        root = Path(__file__).parent
        task = json.loads((root / "task_v1.acceptance.proposed.json").read_text())
        evidence = json.loads((root / "evidence_v1.acceptance.proposed.json").read_text())
        legacy = {"CONTROL_PLANE_HEALTH", "HK_STAGING_CANARY", "HK_STAGING_DEPLOY",
                  "HK_STAGING_VERIFY", "HK_STAGING_ROLLBACK", "HK_STAGING_TEST_PR"}
        self.assertEqual(set(task["properties"]["action_id"]["enum"]), legacy | {C13_ACTION, C14_ACTION})
        self.assertEqual(task["properties"]["signature"]["pattern"], "^[0-9a-f]{128}$")
        for schema in (task, evidence):
            conditions = schema["allOf"]
            for action, environment in ((C13_ACTION, C13_ENVIRONMENT),
                                        (C14_ACTION, C14_ENVIRONMENT)):
                rule = next(r for r in conditions if
                            r["if"]["properties"]["action_id"].get("const") == action)
                self.assertEqual(rule["then"]["properties"]["environment"]["const"], environment)
            legacy_rule = next(r for r in conditions if
                               set(r["if"]["properties"]["action_id"].get("enum", [])) == legacy)
            self.assertEqual(legacy_rule["then"]["properties"]["environment"]["const"], "HK-STAGING-01")


if __name__ == "__main__":
    unittest.main()
