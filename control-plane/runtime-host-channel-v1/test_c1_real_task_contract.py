"""Offline proof of the real C1 task contract, and that it did not disturb the smoke.

What is REAL here and what is a double, stated up front, because the value of this file
is entirely in that distinction:

  REAL      c1_execution_contract, c1_dispatch_outbox, c1_result_pull,
            c1_execution_loop, c1_worker's kind set, and the executor itself - the sealed
            result used by every acceptance assertion is produced by running
            `c1_ai_execution_backend.py run --stub` as a real subprocess with a real
            `--task-kind/--task-payload`, not by a mock.
  DOUBLE    the Runtime (`RuntimeDouble`, reproducing the fencing rules read out of the
            deployed kernel: claim only picks QUEUED and bumps attempts; complete only
            lands while RUNNING, owned by this worker, attempts == expected_attempt, lease
            unexpired) and the GitHub transport (`StubGitHub`).
  NOT PROVEN HERE
            that the deployed kernel behaves as its source says, that the workflow file
            runs, or that a dispatch reaches GitHub. Those need the credential on the
            Runtime Host and the first real dispatch - deliberately not part of this round.

What each class proves, mapped to the acceptance list:

  OldSmokeIsUnchanged            A  the deployed smoke's identity and acceptance rule
  TwoRealTasksAreDistinct        B  two payloads => two prompts => two identities
  IdempotencyIsTheRuntimes       C  same external task twice => one task, one dispatch
  AResultCannotCompleteAnother   D  identity binding, not text, ties a result to a task
  MalformedResultsAreRefused     E
  ResumeNeverDispatchesTwice     F  dispatch once, crash, resume, still one dispatch
  ProbeStaysIsolated             G
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import c1_dispatch_outbox as outbox_mod  # noqa: E402
import c1_execution_contract as contract  # noqa: E402
import c1_execution_loop as loop_mod  # noqa: E402
import c1_worker as worker_mod  # noqa: E402
from c1_result_pull import artifact_name, pull_result  # noqa: E402

BACKEND = HERE / "c1_ai_execution_backend.py"
STUB_MODEL = "c1-offline-stub"
WORKER = "c1-real-task-test"
LEASE_S = 120

# The deployed smoke's identity, pinned. These are the values the live Runtime Host
# already recorded (`rt_fed1d4626...` attempt 1 is the real paid smoke of 2026-10-02,
# whose `execution_request_id` is recorded in the project invariants). If a later change
# ever moves them, an already-answered execution would look like a brand new one and a
# second paid model call would become possible - which is exactly what this pins against.
SMOKE_TASK = "rt_fed1d462624d44d39e8ab9561ad429f7"
SMOKE_REQUEST_ID = "6e5208ddc76d73ddb4728fade382056891ce93941f5c299abe36871609760a75"
SMOKE_TASK_CCCC = "rt_" + "c" * 32
SMOKE_REQUEST_ID_CCCC = "a4201035f6e42e41128cbf5068dc1697fa4573373fd2f04a4de384b2e2b22b64"
SMOKE_BINDING_SAMPLE = (
    '{"attempt":1,"idempotency_key":"c1-real-ai-worker-v1:smoke:1",'
    '"kind":"c1-ai-execution-request","owner_c":"C1",'
    '"payload":{"schema_version":1,"smoke_id":"C1_REAL_AI_WORKER_V1"},'
    '"prompt_sha256":"a54ca080f86718734e6c5eddc6b1eb9f03f689bd9af745180da09519ceda0cf6",'
    '"provider":"OPENAI_RESPONSES_API","runtime_task_id":"%s","schema_version":1,'
    '"smoke_id":"C1_REAL_AI_WORKER_V1","task_kind":"AI_WORK_V1"}' % SMOKE_TASK_CCCC)


class RuntimeErrorInvariant(RuntimeError):
    """The deployed kernel's refusal type, carried here by name - see the loop module."""


class Clock:
    def __init__(self, now=1_700_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


class Task:
    def __init__(self, task_id, owner_c, kind, payload, max_attempts, key):
        self.task_id = task_id
        self.owner_c = owner_c
        self.kind = kind
        self.payload = payload
        self.max_attempts = max_attempts
        self.idempotency_key = key
        self.status = "QUEUED"
        self.attempts = 0
        self.lease_owner = None
        self.lease_until = None


class Claimed:
    def __init__(self, task):
        self.task_id = task.task_id
        self.owner_c = task.owner_c
        self.kind = task.kind
        self.payload = task.payload
        self.attempts = task.attempts
        self.lease_until = task.lease_until


class RuntimeDouble:
    """Fencing-faithful double, reduced to what a real C1 task needs."""

    def __init__(self, clock):
        self.clock = clock
        self.tasks = {}
        self._seq = 0

    def enqueue(self, owner_c, kind, payload, *, idempotency_key=None, max_attempts=5):
        if idempotency_key is not None:
            for task in self.tasks.values():
                if task.idempotency_key == idempotency_key:
                    return task.task_id          # the Runtime's own de-duplication
        self._seq += 1
        task_id = "rt_%032x" % self._seq
        self.tasks[task_id] = Task(task_id, owner_c, kind, payload, max_attempts,
                                   idempotency_key)
        return task_id

    def claim(self, c_id, *, worker_id, lease_s=LEASE_S, kinds=None):
        for task in self.tasks.values():
            if task.owner_c != c_id or task.status != "QUEUED":
                continue
            if kinds is not None and task.kind not in kinds:
                continue
            task.status = "RUNNING"
            task.lease_owner = worker_id
            task.lease_until = self.clock() + lease_s
            task.attempts += 1
            return Claimed(task)
        return None

    def renew_task(self, task_id, *, worker_id, expected_attempt, lease_s=LEASE_S):
        task = self.tasks[task_id]
        if (task.status != "RUNNING" or task.lease_owner != worker_id
                or task.attempts != expected_attempt or not task.lease_until > self.clock()):
            raise RuntimeErrorInvariant("renewal rejected: stale, expired or unowned lease")
        task.lease_until = self.clock() + lease_s
        return task.lease_until

    def complete(self, c_id, task_id, *, worker_id, expected_attempt, success,
                 result=None, error=None):
        task = self.tasks[task_id]
        if (task.status != "RUNNING" or task.lease_owner != worker_id
                or task.attempts != expected_attempt or not task.lease_until > self.clock()):
            raise RuntimeErrorInvariant("completion rejected: stale, expired or unowned lease")
        task.status = "SUCCEEDED" if success else "FAILED"
        task.result = result
        task.lease_owner = None
        task.lease_until = None

    def status_of(self, task_id):
        return self.tasks[task_id].status


class StubGitHub:
    """Offline stand-in for GitHubActionsClient. Produces results with the REAL executor.

    It runs `c1_ai_execution_backend.py run --stub` as a subprocess and passes the task's
    kind and payload, so the bytes the loop validates are the bytes a real dispatch of a
    real task would publish - derived prompt, derived identity and all.
    """

    def __init__(self, *, run_id=525252, hold_ticks=0, declare_run_id=True):
        self.runs = {}
        self.artifacts = {}
        self.dispatch_calls = 0
        self.hold_ticks = hold_ticks
        self.declare_run_id = declare_run_id
        self.payload_seen = []
        self._next_run_id = run_id
        self._tmp = tempfile.mkdtemp(prefix="c1-real-task-")

    def close(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def send(self, request):
        self.dispatch_calls += 1
        run_id = self._next_run_id
        self._next_run_id += 1
        self._materialise(run_id, request)
        return ("sent", run_id if self.declare_run_id else None)

    def _materialise(self, run_id, request):
        out = Path(self._tmp) / ("run-%d.json" % run_id)
        argv = [sys.executable, str(BACKEND), "run",
                "--runtime-task-id", request["runtime_task_id"],
                "--attempt", str(request["attempt"]),
                "--execution-request-id", request["execution_request_id"],
                "--model", STUB_MODEL,
                "--github-run-id", str(run_id),
                "--github-run-attempt", "1",
                "--stub", "--out", str(out)]
        if request.get("task_kind") == contract.REAL_TASK_KIND:
            argv += ["--task-kind", contract.REAL_TASK_KIND,
                     "--task-payload", contract.canonical(request["payload"])]
            self.payload_seen.append(request["payload"])
        completed = subprocess.run(argv, capture_output=True, text=True,
                                   env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
                                            OPENAI_API_KEY=""))
        if completed.returncode != 0:
            raise AssertionError("the real executor refused the stub run: %s%s"
                                 % (completed.stdout, completed.stderr))
        blob = out.read_bytes()
        self.runs[run_id] = {"id": run_id, "run_attempt": 1, "head_sha": "0" * 40,
                             "name": contract.run_identity_name(
                                 request["runtime_task_id"], request["attempt"],
                                 request["execution_request_id"])}
        self.artifacts[(run_id, artifact_name(request["runtime_task_id"],
                                             request["attempt"], request=request))] = {
            "bytes": blob, "digest": "sha256:" + hashlib.sha256(blob).hexdigest()}

    def find_run(self, run_name):
        for run in self.runs.values():
            if run["name"] == run_name:
                return run["id"]
        return None

    def find_run_by_name(self, name):
        found = self.find_run(name)
        return None if found is None else dict(self.runs[found])

    def get_run(self, run_id):
        run = self.runs.get(run_id)
        if run is None:
            return None
        if self.hold_ticks > 0:
            self.hold_ticks -= 1
            return dict(run, status="in_progress", conclusion=None)
        return dict(run, status="completed", conclusion="success")

    def download_artifact(self, run_id, name):
        blob = self.artifacts.get((run_id, name))
        if blob is None:
            return None
        return {"bytes": blob["bytes"], "digest": blob["digest"], "github_run_id": run_id}


def payload_a(**overrides):
    base = {"cell_id": "C01", "external_task_id": "C01-TEST-A",
            "objective": "Read-only diagnosis of mixed hotel funds for one stay.",
            "scope": "Only the two settlement paths named in the objective. No repair."}
    base.update(overrides)
    return contract.build_task_payload(**base)


def payload_b(**overrides):
    base = {"cell_id": "C1", "external_task_id": "C01-TEST-B",
            "objective": "Enumerate the executable C01 gaps that remain after A.",
            "scope": "Read-only enumeration. Produce a list, change nothing."}
    base.update(overrides)
    return contract.build_task_payload(**base)


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="c1-real-task-case-")
        self.clock = Clock()
        self.runtime = RuntimeDouble(self.clock)
        self.github = StubGitHub()
        self.addCleanup(self.github.close)
        self.outbox_path = os.path.join(self.tmp, "outbox.db")
        self.outbox = outbox_mod.DispatchOutbox(self.outbox_path,
                                               clock=lambda: "%020.6f" % self.clock.now)
        self.addCleanup(self.outbox.close)

    # ------------------------------------------------------------------ helpers
    def enqueue_real(self, payload, *, max_attempts=5):
        return self.runtime.enqueue(
            "C1", contract.REAL_TASK_KIND, payload,
            idempotency_key=contract.real_idempotency_key(payload["cell_id"],
                                                         payload["external_task_id"]),
            max_attempts=max_attempts)

    def claim_real(self, task_id):
        claimed = self.runtime.claim("C1", worker_id=WORKER, lease_s=LEASE_S,
                                     kinds=worker_mod.CLAIM_KINDS)
        self.assertIsNotNone(claimed, "the Runtime must hand out the queued real task")
        self.assertEqual(claimed.task_id, task_id)
        return claimed

    def tick(self, claimed):
        return loop_mod.advance(self.outbox, self.runtime, claimed, worker_id=WORKER,
                                client=self.github, lease_s=LEASE_S, clock=self.clock)

    def resume(self, task_id, attempt, *, outbox=None):
        return loop_mod.resume(outbox or self.outbox, self.runtime, task_id, attempt,
                               worker_id=WORKER, client=self.github, lease_s=LEASE_S,
                               clock=self.clock)


class OldSmokeIsUnchanged(Case):
    """A - the deployed smoke's identity and acceptance rule are untouched."""

    def test_the_smoke_binding_is_byte_for_byte_what_it_was(self):
        self.assertEqual(contract.canonical(contract.task_binding(SMOKE_TASK_CCCC, 1)),
                         SMOKE_BINDING_SAMPLE)
        self.assertEqual(contract.execution_request_id(SMOKE_TASK_CCCC, 1),
                         SMOKE_REQUEST_ID_CCCC)

    def test_the_deployed_smokes_identity_is_unchanged(self):
        # The paid smoke of 2026-10-02. Its answer already exists; its identity must not
        # move, or a re-dispatch would look like new work and pay a second time.
        self.assertEqual(contract.execution_request_id(SMOKE_TASK, 1), SMOKE_REQUEST_ID)

    def test_the_smoke_prompt_and_expected_output_are_unchanged(self):
        self.assertEqual(contract.prompt_sha256(),
                         "a54ca080f86718734e6c5eddc6b1eb9f03f689bd9af745180da09519ceda0cf6")
        self.assertEqual(contract.EXPECTED_OUTPUT, "GO_C1_REAL_AI_WORKER_V1_OK")

    def test_a_smoke_dispatch_still_carries_only_the_identity_triple(self):
        request = contract.build_dispatch_request(SMOKE_TASK_CCCC, 1)
        self.assertEqual(set(contract.dispatch_inputs(request)),
                         {"runtime_task_id", "attempt", "execution_request_id"})

    def test_the_smoke_still_runs_end_to_end_through_the_real_executor(self):
        task_id = self.runtime.enqueue("C1", contract.KIND, contract.PAYLOAD,
                                       idempotency_key="smoke")
        claimed = self.runtime.claim("C1", worker_id=WORKER, lease_s=LEASE_S,
                                     kinds=worker_mod.CLAIM_KINDS)
        outcome = self.tick(claimed)
        self.assertEqual(outcome["action"], "COMPLETED", outcome)
        self.assertEqual(self.github.dispatch_calls, 1)
        request = contract.build_dispatch_request(task_id, 1)
        document = self.outbox.terminal_result(request["execution_request_id"])
        self.assertEqual(document["output"], contract.EXPECTED_OUTPUT)
        self.assertIs(document["accepted"], True)
        self.assertEqual(self.runtime.status_of(task_id), "SUCCEEDED")

    def test_a_real_task_can_never_produce_the_smoke_identity(self):
        # Different binding key sets, so the two classes cannot collide: a smoke result
        # and a real result are not interchangeable.
        for one, two in ((SMOKE_TASK_CCCC, 1), (SMOKE_TASK, 2)):
            smoke = contract.execution_request_id(one, two)
            real = contract.execution_request_id(
                one, two, contract.task_spec(contract.REAL_TASK_KIND, payload_a()))
            self.assertNotEqual(smoke, real)
        self.assertNotEqual(set(contract.task_binding(SMOKE_TASK_CCCC, 1)),
                            set(contract.task_binding(
                                SMOKE_TASK_CCCC, 1,
                                contract.task_spec(contract.REAL_TASK_KIND, payload_a()))))


class TwoRealTasksAreDistinct(Case):
    """B - two payloads produce two prompts and two execution identities."""

    def test_two_payloads_produce_two_different_requests(self):
        spec_a = contract.task_spec(contract.REAL_TASK_KIND, payload_a())
        spec_b = contract.task_spec(contract.REAL_TASK_KIND, payload_b())
        prompt_a = contract.prompt_for_spec(spec_a)
        prompt_b = contract.prompt_for_spec(spec_b)
        self.assertNotEqual(prompt_a, prompt_b)
        self.assertIn("C01-TEST-A", prompt_a)
        self.assertIn("C01-TEST-B", prompt_b)

        request_a = contract.build_dispatch_request("rt_a", 1, spec_a)
        request_b = contract.build_dispatch_request("rt_a", 1, spec_b)
        self.assertNotEqual(request_a["execution_request_id"],
                            request_b["execution_request_id"])
        # The payload the executor would receive is the task's own, canonicalised.
        self.assertEqual(json.loads(contract.dispatch_inputs(request_a)["task_payload"]),
                         spec_a["payload"])
        self.assertEqual(set(contract.dispatch_inputs(request_a)),
                         {"runtime_task_id", "attempt", "execution_request_id",
                          "task_kind", "task_payload"})

    def test_the_prompt_is_a_pure_function_of_the_payload(self):
        spec = contract.task_spec(contract.REAL_TASK_KIND, payload_a())
        self.assertEqual(contract.prompt_for_spec(spec), contract.prompt_for_spec(spec))
        # Trace-only fields are recorded but never reach the model.
        traced = payload_a(source_anchor="9950bde1def11b27ed137d7db02a3047befda4fa",
                           issue_number=79)
        self.assertEqual(contract.prompt_for_spec(
            contract.task_spec(contract.REAL_TASK_KIND, traced)), contract.prompt_for_spec(spec))
        self.assertIn("9950bde1def11b27ed137d7db02a3047befda4fa",
                      contract.canonical(contract.task_binding(
                          "rt_a", 1, contract.task_spec(contract.REAL_TASK_KIND, traced))))

    def test_two_real_tasks_are_executed_and_sealed_separately(self):
        first = self.enqueue_real(payload_a())
        self.assertEqual(self.tick(self.claim_real(first))["action"], "COMPLETED")
        second = self.enqueue_real(payload_b())
        self.assertEqual(self.tick(self.claim_real(second))["action"], "COMPLETED")

        self.assertEqual(self.github.dispatch_calls, 2)
        self.assertEqual(len(self.github.payload_seen), 2)
        self.assertNotEqual(self.github.payload_seen[0]["external_task_id"],
                            self.github.payload_seen[1]["external_task_id"])

        request_a = contract.build_dispatch_request(
            first, 1, contract.task_spec(contract.REAL_TASK_KIND, payload_a()))
        request_b = contract.build_dispatch_request(
            second, 1, contract.task_spec(contract.REAL_TASK_KIND, payload_b()))
        document_a = self.outbox.terminal_result(request_a["execution_request_id"])
        document_b = self.outbox.terminal_result(request_b["execution_request_id"])

        # Neither result is the fixed smoke string, and neither is the other's.
        self.assertNotEqual(document_a["output"], contract.EXPECTED_OUTPUT)
        self.assertNotEqual(document_a["output"], document_b["output"])
        self.assertIs(document_a["accepted"], True)
        self.assertTrue(document_a["output"].strip())
        self.assertEqual(self.runtime.status_of(first), "SUCCEEDED")
        self.assertEqual(self.runtime.status_of(second), "SUCCEEDED")


class IdempotencyIsTheRuntimes(Case):
    """C - the same external task, presented twice, is one task and one dispatch."""

    def test_two_enqueues_of_one_external_task_are_one_runtime_task(self):
        key = contract.real_idempotency_key("C01", "C01-TEST-A")
        self.assertEqual(key, contract.real_idempotency_key("C1", "C01-TEST-A"))
        first = self.runtime.enqueue("C1", contract.REAL_TASK_KIND, payload_a(),
                                     idempotency_key=key)
        second = self.runtime.enqueue("C1", contract.REAL_TASK_KIND, payload_a(),
                                      idempotency_key=key)
        self.assertEqual(first, second)
        self.assertEqual(len(self.runtime.tasks), 1)

    def test_a_repeated_register_does_not_dispatch_twice(self):
        spec = contract.task_spec(contract.REAL_TASK_KIND, payload_a())
        request = contract.build_dispatch_request("rt_c", 1, spec)
        request_id = request["execution_request_id"]
        self.assertEqual(self.outbox.register("rt_c", 1, request=request)["action"],
                         "DISPATCH")
        self.outbox.record_dispatch_sent(request_id, github_run_id=1)
        self.assertEqual(self.outbox.register("rt_c", 1, request=request)["action"],
                         "AWAIT_RESULT")
        with self.assertRaises(contract.Refused) as caught:
            self.outbox.record_dispatch_sent(request_id, github_run_id=2)
        self.assertEqual(caught.exception.reason, "SECOND_DISPATCH_FORBIDDEN")

    def test_a_stored_request_that_contradicts_its_identity_is_refused(self):
        spec = contract.task_spec(contract.REAL_TASK_KIND, payload_a())
        request = contract.build_dispatch_request("rt_d", 1, spec)
        self.outbox.register("rt_d", 1, request=request)
        tampered = dict(request, payload=payload_b())
        with self.assertRaises(contract.Refused) as caught:
            self.outbox.register("rt_d", 1, request=tampered)
        self.assertEqual(caught.exception.reason, "STORED_REQUEST_DOES_NOT_MATCH")

    def test_the_outbox_remembers_the_request_so_resume_can_rebuild_identity(self):
        spec = contract.task_spec(contract.REAL_TASK_KIND, payload_a())
        request = contract.build_dispatch_request("rt_e", 1, spec)
        self.outbox.register("rt_e", 1, request=request)
        self.assertEqual(self.outbox.stored_request("rt_e", 1), request)
        # A pre-contract row has none, and the smoke fallback reproduces its identity.
        self.assertIsNone(self.outbox.stored_request("rt_unknown", 1))

    def test_one_external_task_end_to_end_dispatches_exactly_once(self):
        payload = payload_a()
        first = self.enqueue_real(payload)
        second = self.enqueue_real(payload)
        self.assertEqual(first, second)
        self.assertEqual(self.tick(self.claim_real(first))["action"], "COMPLETED")
        self.assertEqual(self.github.dispatch_calls, 1)
        self.assertEqual(len(self.runtime.tasks), 1)


class AResultCannotCompleteAnother(Case):
    """D - identity, not text, is what ties a result to its task."""

    def setUp(self):
        super().setUp()
        self.spec_a = contract.task_spec(contract.REAL_TASK_KIND, payload_a())
        self.spec_b = contract.task_spec(contract.REAL_TASK_KIND, payload_b())
        self.task_a = self.enqueue_real(payload_a())
        self.assertEqual(self.tick(self.claim_real(self.task_a))["action"], "COMPLETED")
        self.request_a = contract.build_dispatch_request(self.task_a, 1, self.spec_a)
        # B's identity exists but was never dispatched: it is the thing a result must be
        # refused against.
        self.request_b = contract.build_dispatch_request("rt_never_dispatched", 1, self.spec_b)
        self.document_a = self.outbox.terminal_result(self.request_a["execution_request_id"])
        self.assertIsNotNone(self.document_a)

    def test_one_tasks_result_is_refused_for_another(self):
        # The document itself is well formed - it simply belongs to another task.
        contract.validate_result(self.document_a, runtime_task_id=self.task_a, attempt=1,
                                 execution_request_id_=self.request_a["execution_request_id"],
                                 task_kind=contract.REAL_TASK_KIND)
        with self.assertRaises(contract.Refused) as caught:
            contract.validate_result(
                self.document_a, runtime_task_id="rt_never_dispatched", attempt=1,
                execution_request_id_=self.request_b["execution_request_id"],
                task_kind=contract.REAL_TASK_KIND)
        self.assertEqual(caught.exception.reason, "RESULT_TASK_MISMATCH")

    def test_the_outbox_refuses_to_seal_a_result_from_another_identity(self):
        self.outbox.register("rt_never_dispatched", 1, request=self.request_b)
        with self.assertRaises(contract.Refused) as caught:
            self.outbox.record_result(self.request_b["execution_request_id"], self.document_a,
                                      runtime_task_id="rt_never_dispatched", attempt=1)
        self.assertEqual(caught.exception.reason, "RESULT_TASK_MISMATCH")

    def test_a_pull_that_is_handed_another_executions_artifact_is_refused(self):
        """Even a transport that returns the wrong bytes cannot seal them.

        The artifact name is the execution identity, so the interesting failure is not
        "the artifact is missing" - it is a transport (or a stale listing) handing back a
        different execution's result under this name. The bytes are then refused by their
        own binding, not by the name they arrived under.
        """
        run_id = self.outbox.snapshot(self.request_a["execution_request_id"])["github_run_id"]
        self.assertIsInstance(run_id, int)
        blob = self.github.artifacts[(run_id, artifact_name(self.task_a, 1,
                                                           request=self.request_a))]

        class WrongArtifact:
            def __init__(self, inner, blob):
                self._inner = inner
                self._blob = blob

            def find_run_by_name(self, name):
                return self._inner.find_run_by_name(name)

            def find_run(self, name):
                return self._inner.find_run(name)

            def get_run(self, run_id):
                return self._inner.get_run(run_id)

            def download_artifact(self, run_id, name):
                return dict(self._blob)

        self.outbox.register("rt_never_dispatched", 1, request=self.request_b)
        self.outbox.record_dispatch_sent(self.request_b["execution_request_id"],
                                        github_run_id=run_id)
        with self.assertRaises(contract.Refused) as caught:
            pull_result(self.outbox, "rt_never_dispatched", 1,
                        client=WrongArtifact(self.github, blob), request=self.request_b)
        # The identity checks fire in order, so the task mismatch is the one reported;
        # either way the bytes were refused for belonging to a different execution.
        self.assertEqual(caught.exception.reason, "RESULT_TASK_MISMATCH")


class MalformedResultsAreRefused(Case):
    """E - a result must be structurally legal and bound to this exact execution."""

    def setUp(self):
        super().setUp()
        self.task_id = "rt_malformed"
        self.spec = contract.task_spec(contract.REAL_TASK_KIND, payload_a())
        self.request = contract.build_dispatch_request(self.task_id, 1, self.spec)
        self.request_id = self.request["execution_request_id"]

    def sealed(self, **overrides):
        output = overrides.get("output", "a real answer")
        document = {
            "version": 1, "kind": contract.RESULT_KIND,
            "runtime_task_id": self.task_id, "attempt": 1,
            "execution_request_id": self.request_id,
            "github_run_id": 1, "github_run_attempt": 1,
            "provider": contract.PROVIDER, "model": STUB_MODEL, "response_id": "resp_1",
            "status": "SUCCEEDED",
            "output_sha256": (contract.output_sha256(output)
                              if isinstance(output, str) else "0" * 64),
            "output": output, "accepted": True, "reused_terminal_result": False,
            "authorizes_any_action": False,
        }
        document.update(overrides)
        return document

    def check(self, document, *, task_kind=contract.REAL_TASK_KIND):
        return contract.validate_result(document, runtime_task_id=self.task_id, attempt=1,
                                        execution_request_id_=self.request_id,
                                        task_kind=task_kind)

    def test_a_legal_real_result_is_accepted_without_matching_any_fixed_literal(self):
        document = self.sealed(output="anything at all, as long as it is an answer")
        self.check(document)
        self.assertNotEqual(document["output"], contract.EXPECTED_OUTPUT)

    def test_an_empty_answer_is_not_an_execution(self):
        document = self.sealed(output="   ", output_sha256=contract.output_sha256("   "))
        with self.assertRaises(contract.Refused) as caught:
            self.check(document)
        self.assertEqual(caught.exception.reason, "RESULT_ACCEPTED_WITH_AN_EMPTY_OUTPUT")

    def test_the_real_rule_does_not_leak_into_the_smoke_rule(self):
        document = self.sealed()
        with self.assertRaises(contract.Refused) as caught:
            self.check(document, task_kind=contract.KIND)
        self.assertEqual(caught.exception.reason,
                         "RESULT_ACCEPTED_WITHOUT_THE_EXPECTED_OUTPUT")

    def test_unbound_and_malformed_documents_are_refused(self):
        cases = [
            ("RESULT_NOT_AN_OBJECT", None),
            ("RESULT_NOT_AN_OBJECT", []),
            ("RESULT_MISSING_FIELDS", {}),
            ("RESULT_ATTEMPT_MISMATCH", self.sealed(attempt=2)),
            ("RESULT_EXECUTION_REQUEST_ID_MISMATCH", self.sealed(execution_request_id="0" * 64)),
            ("RESULT_OUTPUT_HASH_MISMATCH", self.sealed(output_sha256="0" * 64)),
            ("RESULT_MUST_NOT_AUTHORIZE_ANY_ACTION", self.sealed(authorizes_any_action=True)),
            ("RESULT_STATUS_INCONSISTENT_WITH_ACCEPTED", self.sealed(status="FAILED")),
            ("RESULT_PROVIDER_MISMATCH", self.sealed(provider="ANOTHER_PROVIDER")),
            ("RESULT_GITHUB_RUN_ID_INVALID", self.sealed(github_run_id=0)),
            ("RESULT_MISSING_RESPONSE_ID", self.sealed(response_id="")),
            ("RESULT_UNEXPECTED_FIELDS", self.sealed(prompt="do something else")),
            ("RESULT_OUTPUT_NOT_A_STRING", self.sealed(output=7, output_sha256="0" * 64)),
        ]
        for reason, document in cases:
            with self.assertRaises(contract.Refused, msg=reason) as caught:
                self.check(document)
            self.assertEqual(caught.exception.reason, reason, reason)

    def test_a_failed_real_result_is_legal_but_must_carry_a_reason(self):
        failed = self.sealed(status="FAILED", accepted=False,
                             failure_reason="MODEL_RETURNED_NO_USABLE_OUTPUT")
        self.check(failed)
        without = dict(failed)
        without.pop("failure_reason")
        with self.assertRaises(contract.Refused) as caught:
            self.check(without)
        self.assertEqual(caught.exception.reason, "RESULT_FAILED_WITHOUT_A_REASON")

    def test_a_result_from_an_older_contract_shape_is_refused(self):
        # A1 real semantics: dropping the payload must not silently degrade to the smoke
        # contract - an identity that is not derivable is refused, not executed.
        with self.assertRaises(contract.Refused):
            contract.task_spec(contract.REAL_TASK_KIND, None)
        with self.assertRaises(contract.Refused):
            contract.task_spec(contract.REAL_TASK_KIND, contract.PAYLOAD)

    def test_the_executor_refuses_a_dispatch_whose_payload_is_not_the_bound_one(self):
        other = contract.build_dispatch_request(
            self.task_id, 1, contract.task_spec(contract.REAL_TASK_KIND, payload_b()))
        completed = subprocess.run(
            [sys.executable, str(BACKEND), "run",
             "--runtime-task-id", self.task_id, "--attempt", "1",
             "--execution-request-id", other["execution_request_id"],
             "--task-kind", contract.REAL_TASK_KIND,
             "--task-payload", contract.canonical(self.spec["payload"]),
             "--model", STUB_MODEL, "--github-run-id", "1", "--github-run-attempt", "1",
             "--stub", "--out", str(Path(self.tmp) / "never.json")],
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", OPENAI_API_KEY=""))
        self.assertEqual(completed.returncode, 3, completed.stdout + completed.stderr)
        self.assertIn("EXECUTION_REQUEST_ID_DOES_NOT_MATCH_RUNTIME_FACTS", completed.stdout)


class ResumeNeverDispatchesTwice(Case):
    """F - dispatch once, crash, restart, resume: still exactly one dispatch."""

    def test_a_restart_resumes_the_real_task_without_a_second_dispatch(self):
        self.github.hold_ticks = 1            # the run is still in progress on the first poll
        task_id = self.enqueue_real(payload_a())
        spec = contract.task_spec(contract.REAL_TASK_KIND, payload_a())
        request = contract.build_dispatch_request(task_id, 1, spec)
        request_id = request["execution_request_id"]

        first = self.tick(self.claim_real(task_id))
        self.assertEqual(first["action"], "AWAIT_RESULT", first)
        self.assertEqual(self.github.dispatch_calls, 1)
        self.assertEqual(self.outbox.snapshot(request_id)["dispatches_sent"], 1)

        # Crash: the process dies, taking the in-memory outbox handle with it. A fresh
        # handle over the same file is what a restart actually looks like.
        self.outbox.close()
        restarted = outbox_mod.DispatchOutbox(self.outbox_path,
                                             clock=lambda: "%020.6f" % self.clock.now)
        self.addCleanup(restarted.close)
        self.assertEqual(restarted.stored_request(task_id, 1), request)

        second = self.resume(task_id, 1, outbox=restarted)
        self.assertEqual(second["action"], "COMPLETED", second)
        self.assertEqual(self.github.dispatch_calls, 1, "a resume must not re-dispatch")
        self.assertEqual(self.runtime.status_of(task_id), "SUCCEEDED")
        self.assertEqual(restarted.snapshot(request_id)["state"], "COMPLETED")

        third = self.resume(task_id, 1, outbox=restarted)
        self.assertEqual(third["action"], "ALREADY_COMPLETED", third)
        self.assertEqual(self.github.dispatch_calls, 1, "still exactly one dispatch")

        document = restarted.terminal_result(request_id)
        self.assertIs(document["accepted"], True)
        self.assertTrue(document["output"].strip())

    def test_a_resume_after_an_ambiguous_post_resolves_by_lookup_not_by_resending(self):
        self.github.declare_run_id = False      # API 2022-11-28 answers 204 with no run id
        self.github.hold_ticks = 1
        task_id = self.enqueue_real(payload_a())

        first = self.tick(self.claim_real(task_id))
        # Sent, and the run id is unknown: the documented production shape. The next tick
        # must resolve it by looking the deterministic run name up.
        self.assertEqual(first["action"], "DISPATCHED", first)
        self.assertEqual(self.github.dispatch_calls, 1)

        outcome = first
        for _ in range(4):
            outcome = self.resume(task_id, 1)
            if outcome["action"] == "COMPLETED":
                break
        self.assertEqual(outcome["action"], "COMPLETED", outcome)
        self.assertEqual(self.github.dispatch_calls, 1, "lookup, never a second POST")
        self.assertEqual(self.runtime.status_of(task_id), "SUCCEEDED")


class ProbeStaysIsolated(Case):
    """G - the probe path and every non-C1 task keep their previous behaviour."""

    def test_the_worker_claims_neither_probe_kind(self):
        for probe in ("RUNTIME_PROBE", "RUNTIME_C1_PROBE_V1", "RUNTIME_HOST_PROBE_V1"):
            self.assertNotIn(probe, worker_mod.CLAIM_KINDS)
            self.assertNotIn(probe, contract.CLAIMABLE_KINDS)
        self.assertEqual(worker_mod.CLAIM_KINDS,
                         (contract.KIND, contract.REAL_TASK_KIND))

    def test_a_probe_task_is_never_dispatched_and_never_registered(self):
        probe = self.runtime.enqueue("C1", "RUNTIME_PROBE", {"probe": 1},
                                     idempotency_key="probe")
        claimed = self.runtime.claim("C1", worker_id=WORKER, lease_s=LEASE_S)
        outcome = self.tick(claimed)
        self.assertEqual(outcome["action"], "NOT_A_C1_TASK")
        self.assertEqual(outcome["reason"], "KIND_MISMATCH")
        self.assertEqual(self.github.dispatch_calls, 0)
        self.assertEqual(self.runtime.status_of(probe), "RUNNING")   # untouched by us
        rows = self.outbox._db.execute("SELECT COUNT(*) AS n FROM c1_dispatch").fetchone()
        self.assertEqual(rows["n"], 0, "a refused task must never reach the outbox")

    def test_a_real_task_with_an_invalid_payload_is_never_registered(self):
        invalid = {"schema_version": 1, "cell_id": "C01", "external_task_id": "X",
                   "objective": "", "scope": "s"}       # no objective
        task_id = self.runtime.enqueue("C1", contract.REAL_TASK_KIND, invalid,
                                       idempotency_key="invalid")
        claimed = self.runtime.claim("C1", worker_id=WORKER, lease_s=LEASE_S,
                                     kinds=worker_mod.CLAIM_KINDS)
        outcome = self.tick(claimed)
        self.assertEqual(outcome["action"], "NOT_A_C1_TASK")
        self.assertEqual(outcome["reason"], "TASK_PAYLOAD_REFUSED")
        self.assertEqual(self.github.dispatch_calls, 0)
        rows = self.outbox._db.execute("SELECT COUNT(*) AS n FROM c1_dispatch").fetchone()
        self.assertEqual(rows["n"], 0)

    def test_a_real_task_for_another_cell_is_refused(self):
        with self.assertRaises(contract.Refused) as caught:
            payload_a(cell_id="C02")
        self.assertEqual(caught.exception.reason, "TASK_PAYLOAD_CELL_IS_NOT_C1")

    def test_post_execution_facts_are_refused_as_task_input(self):
        for field in ("candidate_sha", "artifact_id", "pr_number", "c14_verdict",
                      "c13_verdict", "github_run_id", "execution_request_id"):
            base = {"schema_version": 1, "cell_id": "C01", "external_task_id": "X",
                    "objective": "o", "scope": "s", field: "anything"}
            with self.assertRaises(contract.Refused, msg=field) as caught:
                contract.validate_task_payload(base)
            self.assertTrue(caught.exception.reason.startswith("TASK_PAYLOAD_REFUSED_FIELD"),
                            caught.exception.reason)

    def test_the_unknown_field_rule_is_explicit(self):
        base = {"schema_version": 1, "cell_id": "C01", "external_task_id": "X",
                "objective": "o", "scope": "s", "surprise": 1}
        with self.assertRaises(contract.Refused) as caught:
            contract.validate_task_payload(base)
        self.assertEqual(caught.exception.reason, "TASK_PAYLOAD_UNKNOWN_FIELD:surprise")


class CellIdentityIsCanonical(Case):
    """The Owner writes `C01`; the kernel only knows `C1`. Exactly one of them is internal."""

    def test_external_spellings_fold_onto_the_kernels_own(self):
        self.assertEqual(contract.canonical_cell_id("C1"), "C1")
        self.assertEqual(contract.canonical_cell_id("C01"), "C1")
        self.assertEqual(contract.canonical_cell_id("C09"), "C9")
        self.assertEqual(contract.canonical_cell_id("C14"), "C14")
        self.assertEqual(contract.canonical_cell_id(" c01 "), "C1")

    def test_normalisation_is_idempotent_so_no_second_key_can_appear(self):
        for external in ("C1", "C01", "C02", "C09", "C14"):
            once = contract.canonical_cell_id(external)
            self.assertEqual(contract.canonical_cell_id(once), once)

    def test_an_external_spelling_is_never_internal(self):
        with self.assertRaises(contract.Refused):
            contract.assert_canonical_cell_id("C01")
        with self.assertRaises(contract.Refused):
            contract.assert_canonical_cell_id("c1")
        self.assertEqual(contract.assert_canonical_cell_id("C1"), "C1")

    def test_a_payload_is_bound_with_the_canonical_cell_only(self):
        self.assertEqual(payload_a(cell_id="C01")["cell_id"], "C1")
        self.assertEqual(payload_a(cell_id="C1")["cell_id"], "C1")
        # Both spellings are the same task, byte for byte - not two tasks.
        self.assertEqual(contract.canonical(payload_a(cell_id="C01")),
                         contract.canonical(payload_a(cell_id="C1")))

    def test_unknown_responsibility_domains_are_refused_not_coerced(self):
        for bad in ("C0", "C00", "C010", "C15", "C99", "X1", "", None, 7):
            with self.assertRaises(contract.Refused, msg=repr(bad)):
                contract.canonical_cell_id(bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)
