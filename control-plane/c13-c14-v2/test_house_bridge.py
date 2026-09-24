import base64
import copy
import hashlib
import json
import unittest
import xml.etree.ElementTree as ET
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from pathlib import Path

from acceptance_gate import C13_ACTION, C14_ACTION, C13_ENVIRONMENT, C14_ENVIRONMENT, Refusal
from house_bridge import canonical, digest, issue, read_evidence, receive_evidence

SHA, TREE, SCOPE = "a" * 40, "b" * 40, "c" * 64
REQUEST = {"candidate_sha": SHA, "application_tree": TREE, "test_scope_sha256": SCOPE,
           "c13_evidence_reference": "host-evidence://c13/1"}


class Host:
    """Memory only. No Task bus, HK Runner or real signing key."""
    def __init__(self):
        self.test_receipt_key = ec.generate_private_key(ec.SECP256R1())
        self.tasks = {}
        self.results = {}
        self.artifacts = {}
        self.receipts = {}
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

    def sign_control_receipt(self, raw):
        signature = self.test_receipt_key.sign(raw, ec.ECDSA(hashes.SHA256()))
        return base64.b64encode(signature).decode("ascii")

    def verify_control_receipt(self, raw, signature):
        try:
            self.test_receipt_key.public_key().verify(base64.b64decode(signature, validate=True),
                                                      raw, ec.ECDSA(hashes.SHA256()))
            return True
        except (InvalidSignature, ValueError):
            return False

    def publish_control_receipt(self, task_id, nonce, raw):
        key = (task_id, nonce)
        previous = self.receipts.get(key)
        if previous is not None and previous != raw:
            raise Refusal("duplicate_receipt")
        self.receipts[key] = raw

    def read_control_receipt(self, task_id, nonce):
        return self.receipts.get((task_id, nonce))

    def complete(self, task, verdict="PASS_SCOPED"):
        task_id, nonce = task["task_id"], task["nonce"]
        inventory = json.loads((Path(__file__).parent / "c14_frozen_test_inventory.json").read_text())
        root = ET.Element("testsuites")
        for suite_name in ("pytest", "isolated_postgres"):
            cases = inventory[suite_name]
            suite = ET.SubElement(root, "testsuite", name=suite_name, tests=str(len(cases)),
                                  failures="1" if verdict == "FAIL" and suite_name == "pytest" else "0",
                                  errors="0", skipped="0")
            for index, case in enumerate(cases):
                child = ET.SubElement(suite, "testcase", **case)
                if verdict == "FAIL" and suite_name == "pytest" and index == 0:
                    ET.SubElement(child, "failure")
        junit = ET.tostring(root)
        if verdict == "PASS_SCOPED":
            stdout, failures, status, gate = b"1 passed\n", 0, "SUCCESS", "PASS_SCOPED"
        elif verdict == "FAIL":
            stdout, failures, status, gate = b"1 failed\n", 1, "FAILED", "FAIL"
        else:
            raise ValueError("unsupported test verdict")
        manifest = {"task_id": task_id, "nonce": nonce, **task["parameters"],
                    "junit_sha256": digest(junit), "stdout_sha256": digest(stdout),
                    "command": "registered frozen suite"}
        if "c13_evidence_sha256" in manifest:
            del manifest["c13_evidence_sha256"]
        blobs = {"junit": junit, "stdout": stdout, "manifest": canonical(manifest)}
        for name, raw in blobs.items():
            self.artifacts[(task_id, nonce, name)] = raw
        result = {**task["parameters"], "verdict": verdict, "test_count": 71,
                  "failure_count": failures, "error_count": 0, "skipped_count": 0,
                  **{name + "_sha256": digest(raw) for name, raw in blobs.items()}}
        evidence = {"schema_version": "1", "task_id": task_id, "nonce": nonce,
                    "action_id": task["action_id"], "environment": task["environment"],
                    "status": status, "started_at": task["issued_at"],
                    "completed_at": task["issued_at"], "agent_version": "test-only",
                    "executor_version": "test-only", "executor_result": result,
                    "gate_results": {"isolated_acceptance": gate},
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

    def test_c13_never_enters_house_bus(self):
        host = Host()
        request = {"candidate_sha": SHA, "application_tree": TREE, "test_scope_sha256": SCOPE}
        self.refuse("c13_developer_side_only", lambda: issue(request, "C13", 100, host))
        self.assertFalse(host.tasks)

    def test_c14_house_task_and_signed_artifacts(self):
        host = Host()
        task = issue(REQUEST, "C14", 100, host)
        self.assertEqual(set(task), {"schema_version", "task_id", "nonce", "issued_at",
                                     "expires_at", "authority", "environment", "action_id",
                                     "parameters", "signature"})
        self.assertEqual(task["action_id"], C14_ACTION)
        host.complete(task)
        returned = receive_evidence(task, 101, host)
        self.assertEqual(returned["result"]["verdict"], "PASS_SCOPED")
        receipt = returned["receipt"]
        self.assertEqual(receipt["contract"], "GO_C14_EVIDENCE_RECEIPT_V1")
        self.assertEqual(receipt["verification_state"], "EVIDENCE_VERIFIED")
        self.assertEqual(receipt["terminal_state"], "COMPLETE")
        self.assertFalse(receipt["authorizes_any_action"])
        self.assertEqual(receipt["candidate_sha"], SHA)
        self.assertEqual(receipt["evidence_sha256"],
                         digest(host.read_house_evidence(task["task_id"], task["nonce"])))
        self.assertEqual(host.read_control_receipt(task["task_id"], task["nonce"]),
                         canonical(receipt) + b"\n")
        self.assertEqual(read_evidence(task, 10_000, host)["verdict"], "PASS_SCOPED")

    def test_c14_requires_verified_c13_at_issuance(self):
        host = Host()
        request = REQUEST
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
        request = REQUEST
        task = issue(request, "C14", 100, host)
        host.complete(task)
        host.tasks[task["task_id"]] = b"altered"
        self.refuse("task_readback", lambda: read_evidence(task, 101, host))
        class BadSigner(Host):
            def verify_house_task(self, raw, signature):
                return False
        bad = BadSigner()
        self.refuse("task_signature", lambda: issue(request, "C14", 100, bad))
        self.assertFalse(bad.tasks)

    def test_evidence_and_raw_artifact_tamper_refuse(self):
        host = Host()
        task = issue(REQUEST, "C14", 100, host)
        host.complete(task)
        key = (task["task_id"], task["nonce"])
        host.artifacts[(*key, "junit")] = b"<testsuite tests='0'/>"
        self.refuse("artifact_integrity", lambda: read_evidence(task, 101, host))
        host.complete(task)
        evidence = __import__("json").loads(host.results[key])
        evidence["executor_result"]["candidate_sha"] = "e" * 40
        host.results[key] = canonical(evidence) + b"\n"
        self.refuse("evidence_signature", lambda: read_evidence(task, 101, host))

    def test_receipt_readback_tamper_refuses(self):
        class BadReceiptHost(Host):
            def publish_control_receipt(self, task_id, nonce, raw):
                self.receipts[(task_id, nonce)] = b"altered"

        host = BadReceiptHost()
        task = issue(REQUEST, "C14", 100, host)
        host.complete(task)
        self.refuse("receipt_readback", lambda: receive_evidence(task, 101, host))

    def test_missing_receipt_route_refuses_after_hk_evidence_verification(self):
        class MissingReceiptHost(Host):
            def read_control_receipt(self, task_id, nonce):
                raise AttributeError("not installed")

        host = MissingReceiptHost()
        task = issue(REQUEST, "C14", 100, host)
        host.complete(task)
        self.refuse("receipt_route", lambda: receive_evidence(task, 101, host))

    def test_failed_evidence_is_receipted_but_never_authorizes_release(self):
        host = Host()
        task = issue(REQUEST, "C14", 100, host)
        host.complete(task, "FAIL")
        receipt = receive_evidence(task, 101, host)["receipt"]
        self.assertEqual(receipt["verdict"], "FAIL")
        self.assertEqual(receipt["verification_state"], "EVIDENCE_VERIFIED")
        self.assertEqual(receipt["terminal_state"], "COMPLETE")
        self.assertFalse(receipt["authorizes_any_action"])
        self.assertEqual(read_evidence(task, 10_000, host)["verdict"], "FAIL")

    def test_no_deploy_action_or_caller_command(self):
        host = Host()
        request = {"candidate_sha": SHA, "application_tree": TREE, "test_scope_sha256": SCOPE}
        self.refuse("request_fields", lambda: issue({**REQUEST, "command": "deploy"}, "C14", 100, host))
        self.refuse("c13_developer_side_only", lambda: issue(request, "HK_STAGING_DEPLOY", 100, host))
        self.assertFalse(host.tasks)

    def test_proposed_house_contract_preserves_legacy_environment(self):
        root = Path(__file__).parent
        task = json.loads((root / "task_v1.acceptance.proposed.json").read_text())
        evidence = json.loads((root / "evidence_v1.acceptance.proposed.json").read_text())
        legacy = {"CONTROL_PLANE_HEALTH", "HK_STAGING_CANARY", "HK_STAGING_DEPLOY",
                  "HK_STAGING_VERIFY", "HK_STAGING_ROLLBACK", "HK_STAGING_TEST_PR"}
        self.assertEqual(set(task["properties"]["action_id"]["enum"]), legacy | {C14_ACTION})
        self.assertEqual(set(evidence["properties"]["action_id"]["enum"]), legacy | {C14_ACTION})
        self.assertEqual(task["properties"]["signature"]["pattern"], "^[0-9a-f]{128}$")
        for schema in (task, evidence):
            conditions = schema["allOf"]
            for action, environment in ((C14_ACTION, C14_ENVIRONMENT),):
                rule = next(r for r in conditions if
                            r["if"]["properties"]["action_id"].get("const") == action)
                self.assertEqual(rule["then"]["properties"]["environment"]["const"], environment)
            legacy_rule = next(r for r in conditions if
                               set(r["if"]["properties"]["action_id"].get("enum", [])) == legacy)
            self.assertEqual(legacy_rule["then"]["properties"]["environment"]["const"], "HK-STAGING-01")


    def test_receipt_schema_forbids_release_authorization(self):
        schema = json.loads((Path(__file__).parent / "receipt_v1.acceptance.proposed.json").read_text())
        self.assertFalse(schema["properties"]["authorizes_any_action"]["const"])
        self.assertEqual(schema["properties"]["verification_state"]["const"], "EVIDENCE_VERIFIED")
        self.assertEqual(schema["properties"]["terminal_state"]["const"], "COMPLETE")
        self.assertEqual(schema["properties"]["verdict"]["enum"], ["PASS_SCOPED", "FAIL", "BLOCKED"])
        self.assertFalse(schema["additionalProperties"])

if __name__ == "__main__":
    unittest.main()
