"""The C1 secret boundary, asserted rather than asserted-in-prose.

The claim this file exists to keep true:

    OPENAI_API_KEY never reaches the Runtime side - not the Runtime filesystem,
    not the Runtime database, not a sealed result, not a log line, not an artifact.

Each of those is checked against the real code path, with a credential-shaped value
present in the environment so that an accidental copy would be caught.
"""
import json
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

FAKE_KEY = "sk-test-SECRET-BOUNDARY-PROBE-0123456789"
TASK = "rt_" + "4" * 32
RUN_ID = 36874444444

# Every module that runs on the Runtime Host for this loop.
RUNTIME_SIDE = ("c1_execution_contract.py", "c1_dispatch_outbox.py",
                "c1_result_pull.py", "c1_github_actions_client.py",
                "c1_execution_loop.py")
# The one module that legitimately names the credential, and only ever inside a
# disposable GitHub-hosted runner.
GITHUB_SIDE = ("c1_ai_execution_backend.py",)


def sealed_result(task=TASK, attempt=1, run_id=RUN_ID):
    return {
        "version": 1, "kind": contract.RESULT_KIND, "runtime_task_id": task,
        "attempt": attempt,
        "execution_request_id": contract.execution_request_id(task, attempt),
        "github_run_id": run_id, "github_run_attempt": 1,
        "provider": contract.PROVIDER, "model": "gpt-5.6-sol", "response_id": "resp_1",
        "status": "SUCCEEDED",
        "output_sha256": contract.output_sha256(contract.EXPECTED_OUTPUT),
        "output": contract.EXPECTED_OUTPUT, "accepted": True,
        "reused_terminal_result": False, "authorizes_any_action": False,
    }


class RuntimeSideNeverNamesTheModelCredential(unittest.TestCase):
    def test_the_credential_name_appears_only_on_the_github_side(self):
        for name in RUNTIME_SIDE:
            self.assertFalse("OPENAI_API_KEY" in (HERE / name).read_text(encoding="utf-8"),
                             "the Runtime side must not name the model credential: %s" % name)
        self.assertTrue(
            "OPENAI_API_KEY" in (HERE / GITHUB_SIDE[0]).read_text(encoding="utf-8"))

    def test_only_the_shared_contract_knows_the_model_endpoint(self):
        # The fixed endpoint constant lives in the contract, which performs no I/O.
        # Neither the outbox, the puller nor the GitHub client may reach the model.
        for name in ("c1_dispatch_outbox.py", "c1_result_pull.py",
                     "c1_github_actions_client.py"):
            self.assertFalse("openai" in (HERE / name).read_text(encoding="utf-8").lower(),
                             "only the contract may name the model provider: %s" % name)

    def test_the_github_side_reads_the_key_from_the_environment_only(self):
        source = (HERE / GITHUB_SIDE[0]).read_text(encoding="utf-8")
        self.assertIn('os.environ.get(API_KEY_ENV, "")', source)
        self.assertNotIn("EnvironmentFile", source)
        self.assertNotIn("/etc/go-runtime-worker-c1.env", source)


class TheCredentialNeverLandsInRuntimeState(unittest.TestCase):
    def test_the_outbox_database_never_contains_a_credential(self):
        os.environ["OPENAI_API_KEY"] = FAKE_KEY
        try:
            with tempfile.TemporaryDirectory() as tmp:
                db = os.path.join(tmp, "outbox.db")
                box = outbox_mod.DispatchOutbox(db)
                request_id = contract.execution_request_id(TASK, 1)
                box.register(TASK, 1)
                box.record_dispatch_sent(request_id, github_run_id=RUN_ID)
                box.record_result(request_id, sealed_result(), runtime_task_id=TASK,
                                  attempt=1)
                box.mark_completed(request_id)
                box.close()
                stored = Path(db).read_bytes()
        finally:
            os.environ.pop("OPENAI_API_KEY", None)
        self.assertNotIn(FAKE_KEY.encode(), stored)
        self.assertNotIn(b"Bearer", stored)
        # The provider LABEL legitimately contains OPENAI (OPENAI_RESPONSES_API); the
        # credential NAME must not appear anywhere in Runtime state.
        self.assertNotIn(b"OPENAI_API_KEY", stored)
        self.assertNotIn(b"Authorization", stored)

    def test_a_sealed_result_never_contains_a_credential(self):
        os.environ["OPENAI_API_KEY"] = FAKE_KEY
        try:
            encoded = contract.canonical(sealed_result())
        finally:
            os.environ.pop("OPENAI_API_KEY", None)
        self.assertNotIn(FAKE_KEY, encoded)
        self.assertNotIn("Bearer", encoded)
        self.assertNotIn("Authorization", encoded)

    def test_the_result_document_has_no_field_that_could_carry_a_credential(self):
        document = sealed_result()
        self.assertEqual(set(document) & {"api_key", "token", "secret", "authorization",
                                          "credential"}, set())


class TheCredentialNeverLandsInLogs(unittest.TestCase):
    def test_the_runtime_side_modules_print_nothing(self):
        for name in RUNTIME_SIDE:
            source = (HERE / name).read_text(encoding="utf-8")
            self.assertFalse("print(" in source, "no stdout on the Runtime side: %s" % name)
            self.assertFalse("logging." in source, "no logging on the Runtime side: %s" % name)

    def test_the_one_line_the_executor_prints_is_an_explicit_allowlist(self):
        source = (HERE / GITHUB_SIDE[0]).read_text(encoding="utf-8")
        start = source.index("def _status_line")
        end = source.index("def main(")
        status_line = source[start:end]
        for field in ("status", "runtime_task_id", "attempt", "execution_request_id",
                      "github_run_id", "model", "response_id", "accepted",
                      "reused_terminal_result"):
            self.assertIn('"%s"' % field, status_line)
        for forbidden in ("OPENAI_API_KEY", "api_key", "token", "Authorization"):
            self.assertNotIn(forbidden, status_line)

    def test_the_executor_refuses_a_result_that_carries_the_credential(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "c1_ai_execution_backend", HERE / "c1_ai_execution_backend.py")
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)
        backend.assert_no_credential_material({"ok": True}, FAKE_KEY)
        with self.assertRaises(contract.Refused) as caught:
            backend.assert_no_credential_material({"leak": FAKE_KEY}, FAKE_KEY)
        self.assertEqual(caught.exception.reason, "CREDENTIAL_MATERIAL_IN_RESULT")


class TheArtifactCarriesOnlyTheResult(unittest.TestCase):
    def test_the_executor_writes_exactly_one_artifact_file(self):
        workflow = (HERE.parents[1] / ".github/workflows/c1-ai-execution-backend-v1.yml"
                    ).read_text(encoding="utf-8")
        publish = workflow.split("- name: Publish the sealed execution result")[1]
        self.assertIn("c1_result.json", publish)
        self.assertNotIn("c1-ai-execution-backend-v1.yml", publish.split("path:")[1][:200])

    def test_the_artifact_upload_step_has_no_credential(self):
        workflow = (HERE.parents[1] / ".github/workflows/c1-ai-execution-backend-v1.yml"
                    ).read_text(encoding="utf-8")
        publish = workflow.split("- name: Publish the sealed execution result")[1]
        self.assertNotIn("OPENAI_API_KEY", publish)


if __name__ == "__main__":
    unittest.main()
