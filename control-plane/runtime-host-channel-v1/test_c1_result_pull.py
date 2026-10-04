"""Offline tests for the Runtime-side result puller.

No network, no credential, no GitHub, no Runtime database. The GitHub client is faked,
so every failure path the design claims to handle is actually exercised.
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
import c1_result_pull as pull_mod  # noqa: E402

TASK = "rt_" + "7" * 32
RUN_ID = 36872222222


def sealed_result(task=TASK, attempt=1, run_id=RUN_ID):
    return {
        "version": 1,
        "kind": contract.RESULT_KIND,
        "runtime_task_id": task,
        "attempt": attempt,
        "execution_request_id": contract.execution_request_id(task, attempt),
        "github_run_id": run_id,
        "github_run_attempt": 1,
        "provider": contract.PROVIDER,
        "model": "gpt-5.6-sol",
        "response_id": "resp_1",
        "status": "SUCCEEDED",
        "output_sha256": contract.output_sha256(contract.EXPECTED_OUTPUT),
        "output": contract.EXPECTED_OUTPUT,
        "accepted": True,
        "reused_terminal_result": False,
        "authorizes_any_action": False,
    }


class FakeGitHub:
    def __init__(self, document=None, *, run_conclusion="success", run_status="completed",
                 artifact=True, run_id=RUN_ID, artifact_for=None, body=None):
        self.document = sealed_result() if document is None else document
        self.run_status = run_status
        self.run_conclusion = run_conclusion
        self.artifact_present = artifact
        self.run_id = run_id
        self.artifact_for = artifact_for
        self.body = body
        self.lookups = []
        self.downloads = []

    def find_run_by_name(self, name):
        self.lookups.append(name)
        return {"id": self.run_id, "run_attempt": 1, "status": self.run_status,
                "conclusion": self.run_conclusion, "head_sha": "a" * 40}

    def get_run(self, run_id):
        return {"id": run_id, "run_attempt": 1, "status": self.run_status,
                "conclusion": self.run_conclusion, "head_sha": "a" * 40}

    def download_artifact(self, run_id, name):
        self.downloads.append((run_id, name))
        if not self.artifact_present:
            return None
        document = self.artifact_for if self.artifact_for is not None else self.document
        raw = self.body if self.body is not None else json.dumps(document).encode("utf-8")
        return {"bytes": raw, "digest": "sha256:" + contract.sha256_hex(raw.decode("utf-8"))}


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def complete(self, c_id, task_id, **kwargs):
        self.calls.append((c_id, task_id, kwargs))


class PullCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.outbox = outbox_mod.DispatchOutbox(os.path.join(self._tmp.name, "outbox.db"))

    def tearDown(self):
        self.outbox.close()
        self._tmp.cleanup()

    def _bound(self, attempt=1, run_id=RUN_ID):
        self.outbox.register(TASK, attempt)
        self.outbox.record_dispatch_sent(contract.execution_request_id(TASK, attempt),
                                         github_run_id=run_id)


class PullTests(PullCase):
    def test_a_pull_requires_a_dispatch_first(self):
        result = pull_mod.pull_result(self.outbox, TASK, 1, client=FakeGitHub())
        self.assertEqual(result["action"], "DISPATCH_REQUIRED")

    def test_a_completed_run_yields_a_sealed_bound_result(self):
        self._bound()
        client = FakeGitHub()
        result = pull_mod.pull_result(self.outbox, TASK, 1, client=client)
        self.assertEqual(result["action"], "RESULT_SEALED")
        self.assertEqual(result["completion"],
                         {"owner_c": "C1", "runtime_task_id": TASK,
                          "expected_attempt": 1})
        self.assertEqual(client.downloads, [(RUN_ID, pull_mod.artifact_name(TASK, 1))])
        self.assertEqual(self.outbox.snapshot(
            contract.execution_request_id(TASK, 1))["state"], outbox_mod.RESULT_SEALED)

    def test_the_artifact_name_is_the_execution_identity(self):
        request_id = contract.execution_request_id(TASK, 1)
        self.assertEqual(pull_mod.artifact_name(TASK, 1),
                         "c1-ai-execution-result-" + request_id)

    def test_an_unknown_run_is_resolved_by_the_deterministic_name(self):
        self.outbox.register(TASK, 1)
        self.outbox.record_dispatch_sent(contract.execution_request_id(TASK, 1))
        client = FakeGitHub()
        result = pull_mod.pull_result(self.outbox, TASK, 1, client=client)
        self.assertEqual(result["action"], "RESULT_SEALED")
        self.assertEqual(client.lookups,
                         [contract.run_identity_name(TASK, 1,
                                                     contract.execution_request_id(TASK, 1))])

    def test_a_run_that_is_still_running_waits_rather_than_completing(self):
        self._bound()
        client = FakeGitHub(run_status="in_progress")
        result = pull_mod.pull_result(self.outbox, TASK, 1, client=client)
        self.assertEqual(result["action"], "AWAIT_RESULT")
        self.assertEqual(client.downloads, [])

    def test_a_run_that_did_not_succeed_never_completes(self):
        self._bound()
        client = FakeGitHub(run_conclusion="failure")
        result = pull_mod.pull_result(self.outbox, TASK, 1, client=client)
        self.assertEqual(result["action"], "RUN_DID_NOT_SUCCEED")
        self.assertEqual(client.downloads, [])
        self.assertIsNone(self.outbox.terminal_result(contract.execution_request_id(TASK, 1)))

    def test_a_missing_artifact_is_reported_not_invented(self):
        self._bound()
        result = pull_mod.pull_result(self.outbox, TASK, 1,
                                      client=FakeGitHub(artifact=False))
        self.assertEqual(result["action"], "ARTIFACT_MISSING")

    def test_a_malformed_body_is_refused(self):
        self._bound()
        client = FakeGitHub(body=b"{not json")
        with self.assertRaises(contract.Refused) as caught:
            pull_mod.pull_result(self.outbox, TASK, 1, client=client)
        self.assertEqual(caught.exception.reason, "ARTIFACT_NOT_VALID_JSON")

    def test_a_result_from_another_run_is_refused(self):
        self._bound()
        client = FakeGitHub(document=sealed_result(run_id=RUN_ID + 1))
        with self.assertRaises(contract.Refused) as caught:
            pull_mod.pull_result(self.outbox, TASK, 1, client=client)
        self.assertEqual(caught.exception.reason, "RESULT_BELONGS_TO_ANOTHER_RUN")

    def test_a_result_for_another_task_is_refused(self):
        self._bound()
        client = FakeGitHub(document=sealed_result(task="rt_" + "8" * 32))
        with self.assertRaises(contract.Refused) as caught:
            pull_mod.pull_result(self.outbox, TASK, 1, client=client)
        self.assertEqual(caught.exception.reason, "RESULT_TASK_MISMATCH")

    def test_a_tampered_artifact_digest_is_refused(self):
        self._bound()
        client = FakeGitHub()
        original = client.download_artifact

        def tampered(run_id, name):
            payload = original(run_id, name)
            payload["digest"] = "sha256:" + "0" * 64
            return payload

        client.download_artifact = tampered
        with self.assertRaises(contract.Refused) as caught:
            pull_mod.pull_result(self.outbox, TASK, 1, client=client)
        self.assertEqual(caught.exception.reason, "ARTIFACT_DIGEST_MISMATCH")

    def test_pulling_twice_reuses_the_terminal_result_without_network(self):
        self._bound()
        self.assertEqual(pull_mod.pull_result(self.outbox, TASK, 1,
                                              client=FakeGitHub())["action"], "RESULT_SEALED")
        quiet = FakeGitHub()
        result = pull_mod.pull_result(self.outbox, TASK, 1, client=quiet)
        self.assertEqual(result["action"], "REUSE_TERMINAL")
        self.assertEqual(quiet.lookups, [])
        self.assertEqual(quiet.downloads, [])

    def test_a_bound_run_id_is_not_re_looked_up(self):
        self._bound()
        client = FakeGitHub()
        pull_mod.pull_result(self.outbox, TASK, 1, client=client)
        self.assertEqual(client.lookups, [])

    def test_an_explicit_run_id_mismatch_is_refused(self):
        self._bound(run_id=RUN_ID)
        with self.assertRaises(contract.Refused) as caught:
            pull_mod.pull_result(self.outbox, TASK, 1, client=FakeGitHub(),
                                 expected_run_id=RUN_ID + 5)
        self.assertEqual(caught.exception.reason, "RUN_ID_DOES_NOT_MATCH_THE_BOUND_RUN")


class CompletionTests(PullCase):
    def test_completion_goes_through_runtime_complete_with_the_exact_attempt(self):
        self._bound(attempt=4, run_id=RUN_ID)
        runtime = FakeRuntime()
        result = pull_mod.complete_after_pull(
            self.outbox, runtime, TASK, 4,
            client=FakeGitHub(document=sealed_result(attempt=4)), worker_id="w1")
        self.assertEqual(result["action"], "COMPLETED")
        self.assertEqual(len(runtime.calls), 1)
        c_id, task_id, kwargs = runtime.calls[0]
        self.assertEqual((c_id, task_id), ("C1", TASK))
        self.assertEqual(kwargs["expected_attempt"], 4)
        self.assertTrue(kwargs["success"])
        self.assertEqual(kwargs["result"]["output"], contract.EXPECTED_OUTPUT)
        self.assertEqual(self.outbox.snapshot(
            contract.execution_request_id(TASK, 4))["state"], outbox_mod.COMPLETED)

    def test_completion_is_not_attempted_while_the_result_is_only_pending(self):
        self._bound()
        runtime = FakeRuntime()
        result = pull_mod.complete_after_pull(
            self.outbox, runtime, TASK, 1,
            client=FakeGitHub(run_status="in_progress"), worker_id="w1")
        self.assertEqual(result["action"], "AWAIT_RESULT")
        self.assertEqual(runtime.calls, [])

    def test_completion_never_happens_twice(self):
        self._bound()
        runtime = FakeRuntime()
        for _ in range(2):
            pull_mod.complete_after_pull(self.outbox, runtime, TASK, 1,
                                         client=FakeGitHub(), worker_id="w1")
        self.assertEqual(len(runtime.calls), 1)

    def test_a_failed_execution_is_completed_as_a_failure_not_retried(self):
        output = "not the smoke string"
        failed = sealed_result()
        failed.update({"status": "FAILED", "accepted": False, "output": output,
                       "output_sha256": contract.output_sha256(output),
                       "failure_reason": "MODEL_OUTPUT_DID_NOT_MATCH_SMOKE_STRING"})
        self._bound()
        runtime = FakeRuntime()
        result = pull_mod.complete_after_pull(
            self.outbox, runtime, TASK, 1,
            client=FakeGitHub(document=failed), worker_id="w1")
        self.assertEqual(result["action"], "COMPLETED")
        self.assertFalse(runtime.calls[0][2]["success"])


class BoundaryTests(PullCase):
    def test_the_puller_opens_no_listener_and_holds_no_model_credential(self):
        text = (HERE / "c1_result_pull.py").read_text(encoding="utf-8")
        for forbidden in ("OPENAI_API_KEY", "api.openai.com", "socket", "listen(",
                          "sqlite3", "Runtime("):
            self.assertNotIn(forbidden, text, forbidden)

    def test_it_never_touches_the_runtime_database_itself(self):
        source = (HERE / "c1_result_pull.py").read_text(encoding="utf-8")
        self.assertNotIn("runtime.db", source)
        self.assertIn("runtime.complete(", source)


if __name__ == "__main__":
    unittest.main()
