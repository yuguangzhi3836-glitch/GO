import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE = Path(__file__).with_name("c1_real_ai_worker.py")
spec = importlib.util.spec_from_file_location("c1_real_ai_worker", MODULE)
worker_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker_mod)


class FakeTask:
    def __init__(self, payload=None, attempts=1):
        self.task_id = "rt_" + "1" * 32
        self.payload = dict(worker_mod.SMOKE_PAYLOAD if payload is None else payload)
        self.attempts = attempts


class FakeRuntime:
    def __init__(self, task=None):
        self.task = task
        self.claim_calls = []
        self.completed = []
        self.escalated = []
        self.recovered = 0

    def recover_stale(self):
        self.recovered += 1
        return {}

    def claim(self, c_id, *, worker_id, lease_s, kinds):
        self.claim_calls.append((c_id, worker_id, lease_s, kinds))
        task, self.task = self.task, None
        return task

    def complete(self, c_id, task_id, **kwargs):
        self.completed.append((c_id, task_id, kwargs))

    def escalate(self, c_id, reason, **kwargs):
        self.escalated.append((c_id, reason, kwargs))


class FakeClient:
    def __init__(self, output=worker_mod.EXPECTED_TEXT):
        self.output = output
        self.calls = 0

    def invoke_smoke(self):
        self.calls += 1
        return {
            "response_id": "resp_test",
            "model": "test-model",
            "output": self.output,
        }


class WorkerContractTests(unittest.TestCase):
    def test_fixed_payload_only(self):
        self.assertEqual(
            worker_mod.require_smoke_payload(dict(worker_mod.SMOKE_PAYLOAD)),
            worker_mod.SMOKE_PAYLOAD,
        )
        with self.assertRaises(ValueError):
            worker_mod.require_smoke_payload({"schema_version": 1, "smoke_id": "other"})

    def test_claim_is_c1_ai_work_only(self):
        runtime = FakeRuntime()
        worker = worker_mod.C1RealAIWorker(runtime, FakeClient(), worker_id="worker:test")
        self.assertEqual(worker.tick(), {"status": "IDLE"})
        self.assertEqual(runtime.claim_calls[0][0], "C1")
        self.assertEqual(runtime.claim_calls[0][3], ("AI_WORK_V1",))

    def test_success_completes_exact_task(self):
        runtime = FakeRuntime(FakeTask())
        worker = worker_mod.C1RealAIWorker(runtime, FakeClient(), worker_id="worker:test")
        result = worker.tick()
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(len(runtime.completed), 1)
        c_id, task_id, kwargs = runtime.completed[0]
        self.assertEqual((c_id, task_id), ("C1", "rt_" + "1" * 32))
        self.assertTrue(kwargs["success"])
        self.assertEqual(kwargs["expected_attempt"], 1)
        self.assertEqual(kwargs["result"]["adapter"], "openai-responses")
        self.assertEqual(kwargs["result"]["output"], worker_mod.EXPECTED_TEXT)
        self.assertEqual(runtime.escalated, [])

    def test_wrong_model_text_fails_closed(self):
        runtime = FakeRuntime(FakeTask())
        worker = worker_mod.C1RealAIWorker(runtime, FakeClient("wrong"), worker_id="worker:test")
        result = worker.tick()
        self.assertEqual(result["status"], "ESCALATED")
        self.assertEqual(len(runtime.completed), 1)
        self.assertFalse(runtime.completed[0][2]["success"])
        self.assertEqual(runtime.completed[0][2]["error"], "ValueError")
        self.assertEqual(runtime.escalated[0][1], "REAL_AI_WORKER_FAILED")
        self.assertTrue(runtime.escalated[0][2]["requires_human"])

    def test_arbitrary_payload_never_reaches_model(self):
        runtime = FakeRuntime(FakeTask({"prompt": "do something"}))
        client = FakeClient()
        worker = worker_mod.C1RealAIWorker(runtime, client, worker_id="worker:test")
        result = worker.tick()
        self.assertEqual(result["status"], "ESCALATED")
        self.assertEqual(client.calls, 0)

    def test_extract_output_text(self):
        doc = {
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": worker_mod.EXPECTED_TEXT}],
            }]
        }
        self.assertEqual(worker_mod.extract_output_text(doc), worker_mod.EXPECTED_TEXT)

    def test_enqueue_smoke_is_fixed_and_idempotent_contract(self):
        calls = []
        class Runtime:
            def enqueue(self, *args, **kwargs):
                calls.append((args, kwargs))
                return "rt_" + "2" * 32
        task_id = worker_mod.enqueue_smoke(Runtime())
        self.assertEqual(task_id, "rt_" + "2" * 32)
        args, kwargs = calls[0]
        self.assertEqual(args[0:2], ("C1", "AI_WORK_V1"))
        self.assertEqual(args[2], worker_mod.SMOKE_PAYLOAD)
        self.assertEqual(kwargs["max_attempts"], 1)
        self.assertEqual(kwargs["idempotency_key"], worker_mod.SMOKE_IDEMPOTENCY_KEY)


if __name__ == "__main__":
    unittest.main()
