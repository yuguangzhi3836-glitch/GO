"""Offline contract tests for the C1 GitHub-hosted AI execution backend (V1).

These tests must never reach the model endpoint, never need a credential, and never
touch a Runtime host or the Runtime database.
"""
import importlib.util
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
BACKEND_PATH = HERE / "c1_ai_execution_backend.py"
BACKEND_WORKFLOW = REPO_ROOT / ".github/workflows/c1-ai-execution-backend-v1.yml"
OFFLINE_WORKFLOW = REPO_ROOT / ".github/workflows/runtime-host-c1-offline-tests.yml"

spec = importlib.util.spec_from_file_location("c1_ai_execution_backend", BACKEND_PATH)
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)

SMOKE = {"schema_version": 1, "smoke_id": "C1_REAL_AI_WORKER_V1"}
TASK_ID = "rt_" + "a" * 32


def load_workflow(path):
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    # YAML 1.1 parses a bare `on:` key as boolean True.
    triggers = document.get("on") or document.get(True)
    return document, triggers


class FixedPayloadTests(unittest.TestCase):
    def test_only_the_fixed_smoke_payload_is_accepted(self):
        self.assertEqual(backend.require_smoke_payload(dict(SMOKE)), SMOKE)
        for bad in ({"schema_version": 1, "smoke_id": "other"},
                    {"prompt": "do something"},
                    {"schema_version": 1, "smoke_id": "C1_REAL_AI_WORKER_V1", "extra": 1},
                    None, "smoke", [1]):
            with self.assertRaises(backend.Refused, msg=repr(bad)):
                backend.require_smoke_payload(bad)

    def test_binding_requires_the_runtime_facts_and_an_explicit_model(self):
        with self.assertRaises(backend.Refused):
            backend.request_binding(runtime_task_id="", attempt=1, model="m")
        with self.assertRaises(backend.Refused):
            backend.request_binding(runtime_task_id=TASK_ID, attempt=0, model="m")
        with self.assertRaises(backend.Refused):
            backend.request_binding(runtime_task_id=TASK_ID, attempt=True, model="m")
        with self.assertRaises(backend.Refused):
            backend.request_binding(runtime_task_id=TASK_ID, attempt=1, model="")

    def test_model_is_never_defaulted_by_the_backend(self):
        # The model must travel with the dispatch; the backend must not invent one.
        source = BACKEND_PATH.read_text(encoding="utf-8")
        self.assertNotIn("DEFAULT_MODEL", source)
        self.assertNotIn("gpt-5", source)


class ExecutionIdentityTests(unittest.TestCase):
    def test_execution_request_id_is_deterministic(self):
        first = backend.build_execution_request(runtime_task_id=TASK_ID, attempt=1, model="m")
        second = backend.build_execution_request(runtime_task_id=TASK_ID, attempt=1, model="m")
        self.assertEqual(first, second)
        self.assertEqual(len(first["execution_request_id"]), 64)

    def test_identity_is_bound_to_task_attempt_and_model(self):
        base = backend.build_execution_request(runtime_task_id=TASK_ID, attempt=1, model="m")
        variants = [
            backend.build_execution_request(runtime_task_id="rt_" + "b" * 32, attempt=1, model="m"),
            backend.build_execution_request(runtime_task_id=TASK_ID, attempt=2, model="m"),
            backend.build_execution_request(runtime_task_id=TASK_ID, attempt=1, model="m2"),
        ]
        for variant in variants:
            self.assertNotEqual(variant["execution_request_id"], base["execution_request_id"])

    def test_canonical_json_is_stable(self):
        self.assertEqual(backend.canonical({"b": 1, "a": [2, 3]}), '{"a":[2,3],"b":1}')


class StubExecutionTests(unittest.TestCase):
    def test_stub_run_seals_an_accepted_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "result.json")
            code = backend.main([
                "run", "--runtime-task-id", TASK_ID, "--attempt", "1", "--model", "gpt-5.6-sol",
                "--payload-json", json.dumps(SMOKE), "--stub", "--out", out,
            ])
            self.assertEqual(code, 0)
            document = json.loads(Path(out).read_text())
            self.assertEqual(document["kind"], "c1-ai-execution-result")
            self.assertEqual(document["owner_c"], "C1")
            self.assertEqual(document["task_kind"], "AI_WORK_V1")
            self.assertEqual(document["output"], backend.EXPECTED_OUTPUT)
            self.assertTrue(document["accepted"])
            self.assertIs(document["authorizes_any_action"], False)
            self.assertIs(document["reused_terminal_result"], False)
            self.assertEqual(document["runtime_task_id"], TASK_ID)
            self.assertEqual(document["attempt"], 1)

    def test_stub_run_needs_no_credential(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "result.json")
            previous = os.environ.pop("OPENAI_API_KEY", None)
            try:
                self.assertEqual(backend.main([
                    "run", "--runtime-task-id", TASK_ID, "--attempt", "1", "--model", "m",
                    "--payload-json", json.dumps(SMOKE), "--stub", "--out", out,
                ]), 0)
            finally:
                if previous is not None:
                    os.environ["OPENAI_API_KEY"] = previous

    def test_emit_request_prints_only_the_canonical_request(self):
        document = backend.build_execution_request(runtime_task_id=TASK_ID, attempt=3, model="m")
        self.assertEqual(document["kind"], "c1-ai-execution-request")
        self.assertEqual(document["idempotency_key"], backend.SMOKE_IDEMPOTENCY_KEY)
        self.assertEqual(document["payload"], SMOKE)
        self.assertEqual(document["attempt"], 3)


class CredentialHygieneTests(unittest.TestCase):
    FAKE_KEY = "sk-test-CREDENTIAL-MUST-NOT-ESCAPE"

    def test_sealed_result_never_contains_the_credential(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "result.json")
            os.environ["OPENAI_API_KEY"] = self.FAKE_KEY
            try:
                self.assertEqual(backend.main([
                    "run", "--runtime-task-id", TASK_ID, "--attempt", "1", "--model", "m",
                    "--payload-json", json.dumps(SMOKE), "--stub", "--out", out,
                ]), 0)
            finally:
                os.environ.pop("OPENAI_API_KEY", None)
            written = Path(out).read_text()
            self.assertNotIn(self.FAKE_KEY, written)
            self.assertNotIn("Bearer", written)

    def test_credential_guard_refuses_a_contaminated_document(self):
        backend.assert_no_credential_material({"ok": True}, "")
        backend.assert_no_credential_material({"ok": True}, None)
        with self.assertRaises(backend.Refused):
            backend.assert_no_credential_material({"leak": self.FAKE_KEY}, self.FAKE_KEY)

    def test_no_credential_is_required_for_a_stub_and_live_refuses_without_one(self):
        with self.assertRaises(backend.Refused) as caught:
            backend.call_responses_api(api_key="", model="m")
        self.assertEqual(caught.exception.reason, "MISSING_OPENAI_API_KEY")


class LivePathTests(unittest.TestCase):
    def _opener(self, payload, captured):
        class _Response:
            def __init__(self, body):
                self._body = body

            def read(self, _n=-1):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

        def opener(request, timeout=None):  # noqa: ARG001
            captured.append(request)
            return _Response(json.dumps(payload).encode("utf-8"))

        return opener

    def test_completed_response_is_accepted_and_key_never_leaves_the_request(self):
        payload = {
            "id": "resp_123",
            "model": "m-live",
            "status": "completed",
            "output": [{"type": "message",
                        "content": [{"type": "output_text", "text": backend.EXPECTED_OUTPUT}]}],
        }
        captured = []
        reply = backend.call_responses_api(api_key="sk-live", model="m",
                                           opener=self._opener(payload, captured))
        self.assertEqual(reply["output"], backend.EXPECTED_OUTPUT)
        self.assertEqual(reply["response_id"], "resp_123")
        self.assertEqual(captured[0].full_url, "https://api.openai.com/v1/responses")
        body = json.loads(captured[0].data.decode("utf-8"))
        self.assertEqual(body["input"], backend.FIXED_PROMPT)
        self.assertIs(body["store"], False)

    def test_http_error_fails_closed_without_echoing_the_body(self):
        def opener(request, timeout=None):  # noqa: ARG001
            raise urllib.error.HTTPError(request.full_url, 401, "unauthorized", {}, None)

        with self.assertRaises(backend.Refused) as caught:
            backend.call_responses_api(api_key="sk-live", model="m", opener=opener)
        self.assertEqual(caught.exception.reason, "MODEL_HTTP_401")

    def test_unexpected_smoke_text_is_sealed_but_not_accepted(self):
        payload = {
            "id": "resp_x", "model": "m", "status": "completed",
            "output": [{"type": "message",
                        "content": [{"type": "output_text", "text": "something else"}]}],
        }
        captured = []
        reply = backend.call_responses_api(api_key="sk-live", model="m",
                                           opener=self._opener(payload, captured))
        document = backend.sealed_result(
            binding=backend.request_binding(runtime_task_id=TASK_ID, attempt=1, model="m"),
            request_id="0" * 64, reply=reply, reused=False)
        self.assertFalse(document["accepted"])
        self.assertEqual(document["failure_reason"], "MODEL_OUTPUT_DID_NOT_MATCH_SMOKE_STRING")


class ExactlyOnceTests(unittest.TestCase):
    def test_a_terminal_result_for_the_same_identity_is_reused_without_a_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            first_out = os.path.join(tmp, "first.json")
            self.assertEqual(backend.main([
                "run", "--runtime-task-id", TASK_ID, "--attempt", "1", "--model", "m",
                "--payload-json", json.dumps(SMOKE), "--stub", "--out", first_out,
            ]), 0)

            def exploding_opener(*_args, **_kwargs):
                raise AssertionError("a second model call was made for the same identity")

            document = backend.run_execution(
                runtime_task_id=TASK_ID, attempt=1, payload=dict(SMOKE), model="m",
                api_key="sk-live", existing_result=first_out, stub=False,
                opener=exploding_opener)
            self.assertTrue(document["reused_terminal_result"])
            self.assertTrue(document["accepted"])

    def test_a_terminal_result_for_a_different_identity_is_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            first_out = os.path.join(tmp, "first.json")
            self.assertEqual(backend.main([
                "run", "--runtime-task-id", TASK_ID, "--attempt", "1", "--model", "m",
                "--payload-json", json.dumps(SMOKE), "--stub", "--out", first_out,
            ]), 0)
            # attempt 2 is a different execution identity: reuse must not happen here.
            self.assertIsNone(backend.reuse_terminal_result(
                first_out,
                backend.build_execution_request(
                    runtime_task_id=TASK_ID, attempt=2, model="m")["execution_request_id"]))

    def test_unreadable_or_foreign_existing_result_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "other.json")
            Path(path).write_text(json.dumps({"kind": "something-else"}), encoding="utf-8")
            self.assertIsNone(backend.reuse_terminal_result(path, "0" * 64))
            self.assertIsNone(backend.reuse_terminal_result(os.path.join(tmp, "nope.json"), "0" * 64))


class WorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.document, self.triggers = load_workflow(BACKEND_WORKFLOW)
        self.text = BACKEND_WORKFLOW.read_text(encoding="utf-8")
        self.steps = self.document["jobs"]["c1-ai-execution"]["steps"]

    def test_it_is_a_dispatchable_backend_on_a_github_hosted_runner(self):
        self.assertIn("workflow_dispatch", self.triggers)
        self.assertEqual(self.document["jobs"]["c1-ai-execution"]["runs-on"], "ubuntu-24.04")

    def test_it_is_not_a_trigger_for_push_or_pull_request(self):
        # A paid execution backend must never fire on its own.
        self.assertNotIn("push", self.triggers)
        self.assertNotIn("pull_request", self.triggers)
        self.assertNotIn("schedule", self.triggers)

    def test_the_payload_is_a_literal_and_not_a_dispatch_input(self):
        inputs = set(self.triggers["workflow_dispatch"]["inputs"])
        self.assertEqual(inputs, {"runtime_task_id", "attempt", "ai_model", "live_call"})
        for forbidden in ("payload", "prompt", "url", "endpoint", "c_id", "owner_c", "kind"):
            self.assertNotIn(forbidden, inputs)

    def test_the_credential_is_the_existing_repository_secret(self):
        self.assertIn("secrets.OPENAI_API_KEY", self.text)
        self.assertEqual(self.text.count("secrets."), 1)

    def test_the_credential_is_injected_only_for_a_live_call(self):
        execution = [s for s in self.steps if "c1_ai_execution_backend.py run" in str(s.get("run", ""))]
        self.assertEqual(len(execution), 1)
        self.assertIn("inputs.live_call == 'true' && secrets.OPENAI_API_KEY || ''",
                      execution[0]["env"]["OPENAI_API_KEY"])
        self.assertEqual(self.document["jobs"]["c1-ai-execution"]["timeout-minutes"], 15)

    def test_the_same_runtime_task_cannot_run_twice_at_once(self):
        self.assertEqual(self.document["concurrency"]["group"],
                         "c1-ai-execution-${{ inputs.runtime_task_id }}")
        self.assertIs(self.document["concurrency"]["cancel-in-progress"], False)

    def test_it_never_reaches_back_into_the_runtime_host(self):
        for forbidden in ("go-runtime-test-01", "i-j6cg7euc4ggol8gkijog", "47.242.131.254",
                          "ProxyJump", "ssh ", "rt01", "systemctl", "EnvironmentFile"):
            self.assertNotIn(forbidden, self.text, forbidden)

    def test_offline_regression_job_carries_no_credential(self):
        document, triggers = load_workflow(OFFLINE_WORKFLOW)
        self.assertIn("pull_request", triggers)
        text = OFFLINE_WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("secrets.", text)
        self.assertIn('OPENAI_API_KEY: ""', text)


class ESCCredentialRemovalTests(unittest.TestCase):
    """The superseded 'persistent C1 worker on the Runtime Host' design must be gone."""

    def test_the_persistent_worker_artifacts_no_longer_exist(self):
        for relative in ("control-plane/runtime-host-channel-v1/c1_real_ai_worker.py",
                         "control-plane/runtime-host-channel-v1/systemd/go-runtime-worker-c1.service",
                         "control-plane/runtime-host-channel-v1/test_c1_real_ai_worker.py",
                         "docs/runtime/GO_RUNTIME_C1_REAL_AI_WORKER_V1_20261001.md"):
            self.assertFalse((REPO_ROOT / relative).exists(), relative)

    def test_nothing_in_this_directory_asks_a_host_for_a_model_credential(self):
        # Test modules are skipped: several of them legitimately name the removed
        # artifacts in order to assert their absence.
        for path in sorted(HERE.rglob("*")):
            if not path.is_file() or path.name.startswith("test_"):
                continue
            if path.suffix not in (".py", ".service", ".conf", ".json"):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for forbidden in ("/etc/go-runtime-worker-c1.env", "GO_C1_OPENAI_MODEL",
                              "go-runtime-worker-c1.service"):
                self.assertNotIn(forbidden, text, "%s in %s" % (forbidden, path.name))


if __name__ == "__main__":
    unittest.main()
