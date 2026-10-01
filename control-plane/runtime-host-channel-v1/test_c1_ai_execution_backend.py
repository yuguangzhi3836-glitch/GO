"""Offline tests for the C1 GitHub-hosted execution backend (V1).

No network, no credential, no Runtime host and no Runtime database.
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import c1_execution_contract as contract  # noqa: E402

BACKEND_PATH = HERE / "c1_ai_execution_backend.py"
BACKEND_WORKFLOW = REPO_ROOT / ".github/workflows/c1-ai-execution-backend-v1.yml"
OFFLINE_WORKFLOW = REPO_ROOT / ".github/workflows/runtime-host-c1-offline-tests.yml"

spec = importlib.util.spec_from_file_location("c1_ai_execution_backend", BACKEND_PATH)
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)

TASK_ID = "rt_" + "a" * 32
REQUEST_ID = contract.execution_request_id(TASK_ID, 1)
RUN_ID = 36870000000


def backend_argv(tmp, *, task_id=TASK_ID, attempt=1, request_id=REQUEST_ID,
                 model="gpt-5.6-sol", run_id=RUN_ID, stub=True, existing_result=None):
    argv = ["run", "--runtime-task-id", task_id, "--attempt", str(attempt),
            "--execution-request-id", request_id, "--model", model,
            "--github-run-id", str(run_id), "--github-run-attempt", "1",
            "--out", os.path.join(tmp, "result.json")]
    if stub:
        argv.append("--stub")
    if existing_result:
        argv += ["--existing-result", existing_result]
    return argv


def load_workflow(path):
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    triggers = document.get("on") or document.get(True)  # YAML 1.1: bare `on` -> True
    return document, triggers


class StubExecutionTests(unittest.TestCase):
    def test_stub_run_seals_a_result_bound_to_the_dispatch_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(backend.main(backend_argv(tmp)), 0)
            document = json.loads(Path(tmp, "result.json").read_text())
            contract.validate_result(document, runtime_task_id=TASK_ID, attempt=1,
                                     execution_request_id_=REQUEST_ID)
            self.assertEqual(document["status"], "SUCCEEDED")
            self.assertEqual(document["output"], contract.EXPECTED_OUTPUT)
            self.assertEqual(document["github_run_id"], RUN_ID)
            self.assertEqual(document["github_run_attempt"], 1)
            self.assertIs(document["authorizes_any_action"], False)
            self.assertIs(document["reused_terminal_result"], False)

    def test_stub_run_needs_no_credential(self):
        previous = os.environ.pop("OPENAI_API_KEY", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                self.assertEqual(backend.main(backend_argv(tmp)), 0)
        finally:
            if previous is not None:
                os.environ["OPENAI_API_KEY"] = previous

    def test_a_dispatch_cannot_ask_for_an_identity_it_does_not_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            wrong = contract.execution_request_id("rt_" + "b" * 32, 1)
            self.assertEqual(backend.main(backend_argv(tmp, request_id=wrong)), 3)

    def test_a_different_attempt_is_a_different_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = backend_argv(tmp, attempt=2,
                                request_id=contract.execution_request_id(TASK_ID, 2))
            self.assertEqual(backend.main(argv), 0)
            document = json.loads(Path(tmp, "result.json").read_text())
            self.assertEqual(document["attempt"], 2)
            self.assertNotEqual(document["execution_request_id"], REQUEST_ID)


class CredentialHygieneTests(unittest.TestCase):
    FAKE_KEY = "sk-test-CREDENTIAL-MUST-NOT-ESCAPE"

    def test_sealed_result_never_contains_the_credential(self):
        os.environ["OPENAI_API_KEY"] = self.FAKE_KEY
        try:
            with tempfile.TemporaryDirectory() as tmp:
                self.assertEqual(backend.main(backend_argv(tmp)), 0)
                written = Path(tmp, "result.json").read_text()
        finally:
            os.environ.pop("OPENAI_API_KEY", None)
        self.assertNotIn(self.FAKE_KEY, written)
        self.assertNotIn("Bearer", written)

    def test_credential_guard_refuses_a_contaminated_document(self):
        backend.assert_no_credential_material({"ok": True}, "")
        backend.assert_no_credential_material({"ok": True}, None)
        with self.assertRaises(contract.Refused):
            backend.assert_no_credential_material({"leak": self.FAKE_KEY}, self.FAKE_KEY)

    def test_a_live_call_without_a_credential_fails_closed(self):
        with self.assertRaises(contract.Refused) as caught:
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

    def test_a_completed_response_is_accepted_on_the_fixed_endpoint(self):
        payload = {
            "id": "resp_123", "model": "m-live", "status": "completed",
            "output": [{"type": "message",
                        "content": [{"type": "output_text",
                                     "text": contract.EXPECTED_OUTPUT}]}],
        }
        captured = []
        reply = backend.call_responses_api(api_key="sk-live", model="m",
                                           opener=self._opener(payload, captured))
        self.assertEqual(reply["output"], contract.EXPECTED_OUTPUT)
        self.assertEqual(captured[0].full_url, "https://api.openai.com/v1/responses")
        body = json.loads(captured[0].data.decode("utf-8"))
        self.assertEqual(body["input"], contract.PROMPT)
        self.assertIs(body["store"], False)

    def test_http_error_fails_closed_without_echoing_the_body(self):
        def opener(request, timeout=None):  # noqa: ARG001
            raise urllib.error.HTTPError(request.full_url, 401, "unauthorized", {}, None)

        with self.assertRaises(contract.Refused) as caught:
            backend.call_responses_api(api_key="sk-live", model="m", opener=opener)
        self.assertEqual(caught.exception.reason, "MODEL_HTTP_401")

    def test_unexpected_smoke_text_is_sealed_but_not_accepted(self):
        payload = {
            "id": "resp_x", "model": "m", "status": "completed",
            "output": [{"type": "message",
                        "content": [{"type": "output_text", "text": "something else"}]}],
        }
        document = backend.run_execution(
            runtime_task_id=TASK_ID, attempt=1, model="m", github_run_id=RUN_ID,
            github_run_attempt=1, execution_request_id_given=REQUEST_ID,
            api_key="sk-live", opener=self._opener(payload, []))
        self.assertFalse(document["accepted"])
        self.assertEqual(document["status"], "FAILED")
        self.assertEqual(document["failure_reason"],
                         "MODEL_OUTPUT_DID_NOT_MATCH_SMOKE_STRING")
        contract.validate_result(document, runtime_task_id=TASK_ID, attempt=1,
                                 execution_request_id_=REQUEST_ID)


class TerminalReuseTests(unittest.TestCase):
    def test_a_terminal_result_for_the_same_identity_is_reused_without_a_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(backend.main(backend_argv(tmp)), 0)
            first = os.path.join(tmp, "first.json")
            os.replace(os.path.join(tmp, "result.json"), first)

            def exploding_opener(*_args, **_kwargs):
                raise AssertionError("a second model call was made for the same identity")

            document = backend.run_execution(
                runtime_task_id=TASK_ID, attempt=1, model="m", github_run_id=RUN_ID,
                github_run_attempt=1, execution_request_id_given=REQUEST_ID,
                existing_result=first, stub=False, api_key="sk-live",
                opener=exploding_opener)
            self.assertTrue(document["reused_terminal_result"])
            self.assertTrue(document["accepted"])

    def test_a_terminal_result_for_a_different_identity_is_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(backend.main(backend_argv(tmp)), 0)
            other = contract.execution_request_id(TASK_ID, 2)
            self.assertIsNone(backend.reuse_terminal_result(
                os.path.join(tmp, "result.json"), other))

    def test_unreadable_or_foreign_existing_result_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "other.json")
            Path(path).write_text(json.dumps({"kind": "something-else"}), encoding="utf-8")
            self.assertIsNone(backend.reuse_terminal_result(path, REQUEST_ID))
            self.assertIsNone(backend.reuse_terminal_result(
                os.path.join(tmp, "nope.json"), REQUEST_ID))


class WorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.document, self.triggers = load_workflow(BACKEND_WORKFLOW)
        self.text = BACKEND_WORKFLOW.read_text(encoding="utf-8")
        self.job = self.document["jobs"]["c1-ai-execution"]
        self.steps = self.job["steps"]

    def test_it_is_a_dispatchable_backend_on_a_github_hosted_runner(self):
        self.assertIn("workflow_dispatch", self.triggers)
        self.assertEqual(self.job["runs-on"], "ubuntu-24.04")

    def test_it_never_fires_on_its_own(self):
        for trigger in ("push", "pull_request", "schedule"):
            self.assertNotIn(trigger, self.triggers)

    def test_the_dispatch_inputs_are_the_identity_triple_and_nothing_else(self):
        inputs = set(self.triggers["workflow_dispatch"]["inputs"])
        self.assertEqual(inputs, {"runtime_task_id", "attempt", "execution_request_id"})
        for forbidden in ("payload", "prompt", "model", "url", "endpoint", "repo", "ref",
                          "c_id", "owner_c", "kind", "workflow", "shell", "command",
                          "live_call", "mode"):
            self.assertNotIn(forbidden, inputs)

    def test_the_model_is_a_repo_side_controlled_value_not_an_input(self):
        self.assertIn("C1_AI_MODEL", self.document["env"])
        self.assertNotIn("ai_model", self.triggers["workflow_dispatch"]["inputs"])
        execution = self._execution_step()
        self.assertIn('--model "$C1_AI_MODEL"', execution["run"])

    def _execution_step(self):
        found = [s for s in self.steps
                 if "c1_ai_execution_backend.py run" in str(s.get("run", ""))]
        self.assertEqual(len(found), 1)
        return found[0]

    def test_the_run_and_attempt_identity_come_from_this_run(self):
        run = self._execution_step()["run"]
        self.assertIn('--github-run-id "${{ github.run_id }}"', run)
        self.assertIn('--github-run-attempt "${{ github.run_attempt }}"', run)
        self.assertIn('--execution-request-id "${{ inputs.execution_request_id }}"', run)

    def test_the_run_name_carries_the_execution_identity(self):
        self.assertEqual(
            self.document["run-name"],
            "C1 ${{ inputs.runtime_task_id }} ${{ inputs.attempt }} "
            "${{ inputs.execution_request_id }}")
        self.assertEqual(
            contract.run_identity_name("rt_x", 1, "abc"),
            "C1 rt_x 1 abc")

    def test_the_credential_is_the_existing_repository_secret(self):
        self.assertIn("secrets.OPENAI_API_KEY", self.text)
        self.assertEqual(self.text.count("secrets."), 1)

    def test_the_credential_is_injected_only_for_a_repo_side_live_switch(self):
        self.assertIn("vars.C1_AI_LIVE_ENABLED == 'true' && secrets.OPENAI_API_KEY || ''",
                      self._execution_step()["env"]["OPENAI_API_KEY"])
        self.assertEqual(self.job["timeout-minutes"], 15)

    def test_the_same_runtime_task_cannot_run_twice_at_once(self):
        self.assertEqual(self.document["concurrency"]["group"],
                         "c1-ai-execution-${{ inputs.runtime_task_id }}")
        self.assertIs(self.document["concurrency"]["cancel-in-progress"], False)

    def test_the_artifact_name_is_the_execution_identity(self):
        publish = [s for s in self.steps
                   if "actions/upload-artifact" in str(s.get("uses", ""))]
        self.assertEqual(len(publish), 1)
        self.assertEqual(publish[0]["with"]["name"],
                         "c1-ai-execution-result-${{ inputs.execution_request_id }}")

    def test_it_never_reaches_back_into_the_runtime_host(self):
        for forbidden in ("go-runtime-test-01", "i-j6cg7euc4ggol8gkijog", "47.242.131.254",
                          "ProxyJump", "ssh ", "rt01", "systemctl", "EnvironmentFile"):
            self.assertNotIn(forbidden, self.text, forbidden)

    def test_the_backend_defaults_to_the_offline_stub(self):
        self.assertIn('MODE="--stub"', self.text)
        self.assertIn('if [ "${C1_AI_LIVE_ENABLED:-}" = "true" ]; then MODE=""; fi', self.text)
        self.assertNotIn("inputs.live_call", self.text)

    def test_the_live_switch_is_not_a_dispatch_input(self):
        # Repo-controlled, not task-controlled: a Runtime dispatch cannot turn it on.
        self.assertIn("vars.C1_AI_LIVE_ENABLED", self.text)
        self.assertEqual(self._execution_step()["env"]["C1_AI_LIVE_ENABLED"],
                         "${{ vars.C1_AI_LIVE_ENABLED }}")
        self.assertNotIn("live_call", self.triggers["workflow_dispatch"]["inputs"])

    def test_offline_regression_job_carries_no_credential(self):
        document, triggers = load_workflow(OFFLINE_WORKFLOW)
        self.assertIn("pull_request", triggers)
        text = OFFLINE_WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("secrets.", text)
        self.assertIn('OPENAI_API_KEY: ""', text)

    def test_the_regression_runs_as_the_principal_the_agent_runs_as(self):
        # The channel's protected-path tests assert root-only semantics; the Management
        # Agent itself runs as root (User=root). Without this the six registration-sync
        # cases fail on an unprivileged runner for the wrong reason.
        text = OFFLINE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('sudo "$(command -v python)" -m unittest discover', text)

    def test_the_regression_installs_the_dependencies_its_tests_import(self):
        text = OFFLINE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("cryptography==46.0.0", text)
        self.assertIn("PyYAML==6.0.3", text)


class ESCCredentialRemovalTests(unittest.TestCase):
    """The superseded 'persistent C1 worker on the Runtime Host' design must stay gone."""

    FORBIDDEN = ("/etc/go-runtime-worker-c1.env", "GO_C1_OPENAI_MODEL",
                 "go-runtime-worker-c1.service")

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
            for forbidden in self.FORBIDDEN:
                self.assertNotIn(forbidden, text, "%s in %s" % (forbidden, path.name))

    def test_the_runtime_side_never_reads_a_model_credential(self):
        text = (HERE / "c1_dispatch_outbox.py").read_text(encoding="utf-8")
        self.assertNotIn("OPENAI_API_KEY", text)
        self.assertNotIn("api.openai.com", text)


if __name__ == "__main__":
    unittest.main()
