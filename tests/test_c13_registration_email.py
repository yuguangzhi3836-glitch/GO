"""Development-side, exact-source regression for PR #228's restricted action.

No Hong Kong service, mailbox or credential is contacted.
"""
import importlib.util
import json
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


actions = load("c13_actions", "hk-staging/source/agent/hk_agent/deployment_actions.py")
runtime = load("c13_email_probe", "hk-staging/source/executor/go-hk-deployctl-runtime/registration_email_verify_runtime.py")
sys.path.insert(0, str(ROOT / "hk-staging/source/agent"))
from hk_agent import transport
ACTION = "HK_STAGING_REGISTRATION_EMAIL_CONFIG_VERIFY"


class Contract(unittest.TestCase):
    def test_fixed_action_accepts_only_empty_parameters(self):
        self.assertEqual(actions.validate(ACTION, {}), {})
        for params in (None, [], {"recipient": "someone@example.com"}, {"command": "id"}, {"provider": "x"}):
            with self.subTest(params=params), self.assertRaises(actions.Reject):
                actions.validate(ACTION, params)

    def test_dispatch_cannot_pass_user_supplied_arguments(self):
        fake = actions.FakeExecutor()
        result = actions.dispatch({"action_id": ACTION, "parameters": {}}, fake)
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(fake.calls, [[actions.EXECUTOR_PATH, "registration-email-config-verify"]])
        for key in ("recipient", "otp", "url", "secret", "path", "executor_path"):
            with self.subTest(key=key), self.assertRaises(actions.Reject):
                actions.dispatch({"action_id": ACTION, "parameters": {key: "x"}}, fake)
        self.assertEqual(len(fake.calls), 1)

    def test_response_fails_closed_on_missing_or_extra_gates(self):
        base = json.loads(actions.FakeExecutor().run([actions.EXECUTOR_PATH, "registration-email-config-verify"])["stdout"])
        def parse(document):
            return actions.parse_executor_output(json.dumps(document), ACTION, {})
        self.assertEqual(parse(base)["status"], "SUCCESS")
        variants = []
        for key in base["gate_results"]:
            bad = json.loads(json.dumps(base)); bad["gate_results"][key] = "FAIL"; variants.append(bad)
        bad = json.loads(json.dumps(base)); bad["gate_results"].pop("audit"); variants.append(bad)
        bad = json.loads(json.dumps(base)); bad["gate_results"]["extra"] = "PASS"; variants.append(bad)
        bad = json.loads(json.dumps(base)); bad["status"] = "REJECTED"; variants.append(bad)
        bad = json.loads(json.dumps(base)); bad["action_id"] = "HK_STAGING_DEPLOY"; variants.append(bad)
        for bad in variants:
            with self.subTest(bad=bad), self.assertRaises(actions.Reject): parse(bad)

    def test_probe_rejects_missing_config_without_socket_connection(self):
        with patch.object(runtime.os, "lstat", side_effect=FileNotFoundError):
            with self.assertRaises(FileNotFoundError): runtime.run_probe()

    def test_failed_probe_never_persists_unrecognized_sensitive_text(self):
        task = {"task_id":"isolated1", "nonce":"nonce1", "action_id":ACTION}
        secret = "recipient@example.com code 283914 provider_body private-value"
        failures = (
            actions.Reject("parser", stdout=secret, stderr=secret, stage="parser"),
            actions.Reject("subprocess", stdout=secret, stderr=secret,
                           returncode=2, stage="subprocess_nonzero"),
        )
        for exc in failures:
            with self.subTest(stage=exc.stage):
                serialized = json.dumps(transport.failure_diagnostic(task, exc))
                for fragment in ("recipient@example.com", "283914", "provider_body", "private-value"):
                    self.assertNotIn(fragment, serialized)
                self.assertEqual(transport.failure_diagnostic(task, exc)["stdout"], None)
                self.assertEqual(transport.failure_diagnostic(task, exc)["stderr"], None)


if __name__ == "__main__": unittest.main()
