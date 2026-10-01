"""Offline end-to-end proof that the C1 loop closes: Runtime -> GitHub -> Runtime.

What is real here and what is a double - stated up front, because the value of this
file is entirely in that distinction:

  REAL      c1_execution_contract, c1_dispatch_outbox, c1_result_pull,
            c1_execution_loop, and the executor itself: the sealed result used by
            every assertion is produced by running `c1_ai_execution_backend.py run
            --stub` as a real subprocess, not by a mock.
  DOUBLE    the Runtime (`RuntimeDouble`, which reproduces the fencing rules read out
            of the deployed kernel at /opt/go/c1-c14-runtime/runtime.py - claim only
            picks QUEUED and bumps attempts; complete only lands while RUNNING, owned
            by this worker, attempts == expected_attempt, lease unexpired; renew_task
            has the same fencing; every state change appends a hash-chained Evidence
            row) and the GitHub transport (`StubGitHub`).
  NOT PROVEN HERE
            that the deployed kernel behaves as its source says, that the workflow
            file runs, or that a dispatch reaches GitHub. Those need the credential on
            the Runtime Host and the first real dispatch - deliberately not part of
            this round.

No network, no credential, no paid call: `--stub` is the executor's offline path.
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
from c1_result_pull import pull_result  # noqa: E402

BACKEND = HERE / "c1_ai_execution_backend.py"
TASK = "rt_" + "9" * 32
WORKER = "c1-loop-test"
LEASE_S = 120


class Clock:
    def __init__(self, now=1_700_000_000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds
        return self.now


class RuntimeErrorInvariant(RuntimeError):
    """The deployed kernel's own refusal type, carried here by name.

    `c1_execution_loop` decides "this execution identity can never be completed, stop
    retrying it" from that type name alone, so the double has to raise the real one: a
    double raising something else would quietly exercise the keep-retrying path and
    prove nothing about the abandon path.
    """


# The name the earlier tests in this file use for the same exception.
LeaseRejected = RuntimeErrorInvariant


class Task:
    def __init__(self, task_id, owner_c, kind, payload, max_attempts):
        self.task_id = task_id
        self.owner_c = owner_c
        self.kind = kind
        self.payload = payload
        self.max_attempts = max_attempts
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
    """Fencing-faithful double for the deployed C1-C14 Runtime."""

    def __init__(self, clock):
        self.clock = clock
        self.tasks = {}
        self.evidence = []
        self._seq = 0

    def _evidence_id(self):
        self._seq += 1
        return "ev_%06d" % self._seq

    def append_evidence(self, c_id, task_id, event_type, body):
        prev = self.evidence[-1]["event_hash"] if self.evidence else None
        row = {"evidence_id": self._evidence_id(), "c_id": c_id, "task_id": task_id,
               "event_type": event_type, "body": body, "prev_hash": prev,
               "created_at": self.clock()}
        canonical = json.dumps({
            "evidence_id": row["evidence_id"], "c_id": row["c_id"],
            "task_id": row["task_id"], "event_type": row["event_type"],
            "body": row["body"], "prev_hash": row["prev_hash"],
            "created_at": row["created_at"],
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        row["event_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        self.evidence.append(row)
        return row["evidence_id"]

    def verify_evidence_chain(self) -> bool:
        previous = None
        for row in self.evidence:
            if row["prev_hash"] != previous:
                return False
            canonical = json.dumps({
                "evidence_id": row["evidence_id"], "c_id": row["c_id"],
                "task_id": row["task_id"], "event_type": row["event_type"],
                "body": row["body"], "prev_hash": row["prev_hash"],
                "created_at": row["created_at"],
            }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != row["event_hash"]:
                return False
            previous = row["event_hash"]
        return True

    # ------------------------------------------------------------------ kernel API
    def enqueue(self, owner_c, kind, payload, *, idempotency_key=None, max_attempts=5):
        if idempotency_key is not None:
            for task in self.tasks.values():
                if getattr(task, "idempotency_key", None) == idempotency_key:
                    return task.task_id
        self._seq += 1
        task_id = "rt_%032x" % self._seq
        task = Task(task_id, owner_c, kind, payload, max_attempts)
        task.idempotency_key = idempotency_key
        self.tasks[task_id] = task
        self.append_evidence(owner_c, task_id, "TASK_ENQUEUED", {"kind": kind})
        return task_id

    def claim(self, c_id, *, worker_id, lease_s=LEASE_S, kinds=None):
        now = self.clock()
        for task in self.tasks.values():
            if task.owner_c != c_id or task.status != "QUEUED":
                continue
            if kinds is not None and task.kind not in kinds:
                continue
            task.status = "RUNNING"
            task.lease_owner = worker_id
            task.lease_until = now + lease_s
            task.attempts += 1
            self.append_evidence(c_id, task.task_id, "TASK_CLAIMED",
                                 {"worker_id": worker_id, "attempt": task.attempts})
            return Claimed(task)
        return None

    def renew_task(self, task_id, *, worker_id, expected_attempt, lease_s=LEASE_S):
        now = self.clock()
        task = self.tasks[task_id]
        if (task.status != "RUNNING" or task.lease_owner != worker_id
                or task.attempts != expected_attempt or not task.lease_until > now):
            raise RuntimeErrorInvariant("renewal rejected: stale, expired or unowned lease")
        task.lease_until = now + lease_s
        return task.lease_until

    def complete(self, c_id, task_id, *, worker_id, expected_attempt, success,
                 result=None, error=None):
        now = self.clock()
        task = self.tasks[task_id]
        if (task.status != "RUNNING" or task.lease_owner != worker_id
                or task.attempts != expected_attempt or not task.lease_until > now):
            raise RuntimeErrorInvariant("completion rejected: stale, expired or unowned lease")
        task.status = "SUCCEEDED" if success else "FAILED"
        task.lease_owner = None
        task.lease_until = None
        self.append_evidence(c_id, task_id, "TASK_COMPLETED", {
            "status": task.status, "result": result or {}, "error": error,
            "worker_id": worker_id, "attempt": expected_attempt})

    def recover_stale(self):
        """Mirrors the kernel: requeue while attempts remain, otherwise escalate.

        The branch matters here. A task with no attempts left becomes ESCALATED and is
        terminal, so it never returns to QUEUED, can never be claimed again, and can
        never be dispatched a second time. That is what bounds the blast radius of a
        lost lease when max_attempts is 1.
        """
        now = self.clock()
        requeued = escalated = 0
        for task in self.tasks.values():
            if task.status == "RUNNING" and (task.lease_until or 0) <= now:
                task.lease_owner = None
                task.lease_until = None
                if task.attempts < task.max_attempts:
                    task.status = "QUEUED"
                    requeued += 1
                    self.append_evidence(task.owner_c, task.task_id, "TASK_REQUEUED",
                                         {"attempts": task.attempts})
                else:
                    task.status = "ESCALATED"
                    escalated += 1
                    self.append_evidence(task.owner_c, task.task_id, "ESCALATION_OPENED",
                                         {"reason": "MAX_ATTEMPTS_EXHAUSTED",
                                          "attempts": task.attempts})
        return {"requeued": requeued, "escalated": escalated}

    # ------------------------------------------------------------------- helpers
    def status_of(self, task_id):
        return self.tasks[task_id].status


class StubGitHub:
    """Offline stand-in for GitHubActionsClient, same surface, no network.

    `send()` produces the sealed result by running the real executor with `--stub`, so
    the bytes the loop validates are the bytes the executor would publish.
    """

    def __init__(self, clock, *, run_id=424242, model="c1-offline-stub"):
        self.clock = clock
        self.model = model
        self.runs = {}
        self.artifacts = {}
        self.dispatch_calls = 0
        self.lookup_calls = 0
        self.hold_ticks = 0          # >0: the run reports in_progress this many polls
        self.fault = None            # "ambiguous" | "run_failure" | "no_artifact"
        # The real client speaks API version 2022-11-28, whose dispatch answers 204 with
        # no run id, so "sent, and the id is unknown" is the PRODUCTION shape and has to
        # be reachable here. Set False to model it.
        self.declare_run_id = True
        # An exception to raise from get_run, for the "failure that is not a refusal by
        # the Runtime's fence" case.
        self.transport_error = None
        self._next_run_id = run_id
        self._tmp = tempfile.mkdtemp(prefix="c1-loop-stub-")

    def close(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    # --------------------------------------------------------------- the wire
    def send(self, request):
        self.dispatch_calls += 1
        if self.fault == "ambiguous":
            return ("ambiguous", "timeout")
        run_id = self._next_run_id
        self._next_run_id += 1
        self._materialise_run(run_id, request)
        return ("sent", run_id if self.declare_run_id else None)

    def _materialise_run(self, run_id, request):
        out = Path(self._tmp) / ("run-%d.json" % run_id)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", OPENAI_API_KEY="")
        completed = subprocess.run(
            [sys.executable, str(BACKEND), "run",
             "--runtime-task-id", request["runtime_task_id"],
             "--attempt", str(request["attempt"]),
             "--execution-request-id", request["execution_request_id"],
             "--model", self.model,
             "--github-run-id", str(run_id),
             "--github-run-attempt", "1",
             "--stub", "--out", str(out)],
            capture_output=True, text=True, env=env)
        if completed.returncode != 0:
            raise AssertionError("the real executor refused the stub run: %s%s"
                                 % (completed.stdout, completed.stderr))
        payload = out.read_bytes()
        name = contract.run_identity_name(request["runtime_task_id"], request["attempt"],
                                          request["execution_request_id"])
        self.runs[run_id] = {"id": run_id, "run_attempt": 1, "name": name,
                             "status": "in_progress" if self.hold_ticks else "completed",
                             "conclusion": None if self.hold_ticks else (
                                 "failure" if self.fault == "run_failure" else "success"),
                             "head_sha": "0" * 40}
        self.artifacts[(run_id, "c1-ai-execution-result-" + request["execution_request_id"])] = {
            "bytes": payload, "digest": "sha256:" + hashlib.sha256(payload).hexdigest()}

    # ------------------------------------------------------- client interface
    def get_run(self, run_id):
        if self.transport_error is not None:
            raise self.transport_error
        run = self.runs.get(run_id)
        if run is None:
            return None
        if self.hold_ticks > 0:
            # Report "still running" for exactly this many polls, then finish.
            self.hold_ticks -= 1
            return dict(run, status="in_progress", conclusion=None)
        if self.fault == "run_failure":
            return dict(run, status="completed", conclusion="failure")
        return dict(run, status="completed", conclusion="success")

    def find_run_by_name(self, name):
        self.lookup_calls += 1
        for run in self.runs.values():
            if run["name"] == name:
                return dict(run)
        return None

    def find_run(self, run_name):
        found = self.find_run_by_name(run_name)
        return None if found is None else found["id"]

    def download_artifact(self, run_id, name):
        if self.fault == "no_artifact":
            return None
        blob = self.artifacts.get((run_id, name))
        if blob is None:
            return None
        return {"bytes": blob["bytes"], "digest": blob["digest"], "github_run_id": run_id}


class LoopCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="c1-loop-")
        self.clock = Clock()
        self.runtime = RuntimeDouble(self.clock)
        self.github = StubGitHub(self.clock)
        self.outbox = outbox_mod.DispatchOutbox(os.path.join(self.tmp, "outbox.db"),
                                                clock=self.outbox_clock)
        self.addCleanup(self.github.close)
        self.addCleanup(self.outbox.close)

    def outbox_clock(self):
        """`updated_at`, on the same fake clock the rest of the harness uses.

        The outbox defaults to the real wall clock, which would make the documented
        "oldest first" ordering of `unfinished()` depend on how fast the test machine
        happened to run - and unresolvable when two rows land in the same microsecond.
        """
        return "%020.6f" % self.clock.now

    def enqueue_c1(self, *, key=None, max_attempts=5):
        return self.enqueue("C1", contract.KIND, contract.PAYLOAD, key=key,
                            max_attempts=max_attempts)

    def enqueue(self, owner_c, kind, payload, *, key=None, max_attempts=5):
        # A distinct idempotency key per call, or two tasks in one test would be the same
        # task; the default is per-test-object so repeated calls are still idempotent.
        return self.runtime.enqueue(owner_c, kind, payload,
                                    idempotency_key=key or ("loop-test:%d" % id(self)),
                                    max_attempts=max_attempts)

    def claim(self, task_id):
        claimed = self.runtime.claim("C1", worker_id=WORKER, lease_s=LEASE_S,
                                     kinds=(contract.KIND,))
        self.assertIsNotNone(claimed, "the Runtime must hand out the queued C1 task")
        self.assertEqual(claimed.task_id, task_id)
        return claimed

    def tick(self, claimed):
        return loop_mod.advance(self.outbox, self.runtime, claimed, worker_id=WORKER,
                                client=self.github, lease_s=LEASE_S, clock=self.clock)

    def resume(self, task_id, attempt):
        """The entry point a later tick uses: an identity this outbox already owns."""
        return loop_mod.resume(self.outbox, self.runtime, task_id, attempt,
                               worker_id=WORKER, client=self.github, lease_s=LEASE_S,
                               clock=self.clock)

    def request_id(self, task_id, attempt):
        return contract.execution_request_id(task_id, attempt)

    def completed_events(self):
        return [row for row in self.runtime.evidence
                if row["event_type"] == "TASK_COMPLETED"]

    def event_types(self):
        return [row["event_type"] for row in self.runtime.evidence]


class TheLoopClosesStubE2E(LoopCase):
    """The headline: one C1 task, end to end, with no network and no credential."""

    def test_runtime_to_github_to_runtime_completes(self):
        task_id = self.enqueue_c1()
        claimed = self.claim(task_id)

        outcome = self.tick(claimed)

        request_id = self.request_id(task_id, 1)
        self.assertEqual(outcome["action"], "COMPLETED", outcome)
        self.assertEqual(self.runtime.status_of(task_id), "SUCCEEDED")
        self.assertEqual(self.github.dispatch_calls, 1, "exactly one dispatch")

        # The Runtime's own completion record, written by complete().
        completed = [row for row in self.runtime.evidence
                     if row["event_type"] == "TASK_COMPLETED"]
        self.assertEqual(len(completed), 1)
        body = completed[0]["body"]
        self.assertEqual(body["attempt"], 1)
        self.assertEqual(body["worker_id"], WORKER)
        self.assertEqual(body["status"], "SUCCEEDED")
        self.assertEqual(body["result"]["output"], contract.EXPECTED_OUTPUT)
        self.assertEqual(body["result"]["execution_request_id"], request_id)

        # The sealed result itself: produced by the real executor, bound to the task.
        result = body["result"]
        contract.validate_result(result, runtime_task_id=task_id, attempt=1,
                                 execution_request_id_=request_id)
        self.assertEqual(result["provider"], contract.PROVIDER)
        self.assertTrue(result["response_id"])
        self.assertTrue(result["accepted"])
        self.assertIs(result["authorizes_any_action"], False)

        self.assertTrue(self.runtime.verify_evidence_chain())
        self.assertEqual(self.outbox.dispatch_status(request_id), "COMPLETED")

        print("C1_LOOP_STUB_E2E_OK %s run=%d task=%s" % (request_id, result["github_run_id"], task_id))


class TheLeaseKeepsTheLoopAlive(LoopCase):
    def test_a_long_execution_renews_its_lease_and_still_completes(self):
        self.github.hold_ticks = 2
        task_id = self.enqueue_c1()
        claimed = self.claim(task_id)

        first = self.tick(claimed)
        self.assertEqual(first["action"], "AWAIT_RESULT", first)
        self.assertTrue(first["renewed"], "an unfinished tick must renew the lease")

        self.clock.advance(100)
        second = self.tick(claimed)
        self.assertEqual(second["action"], "AWAIT_RESULT", second)
        self.assertTrue(second["renewed"])

        self.clock.advance(100)
        third = self.tick(claimed)
        self.assertEqual(third["action"], "COMPLETED", third)
        self.assertEqual(self.runtime.status_of(task_id), "SUCCEEDED")
        self.assertEqual(self.github.dispatch_calls, 1, "polling must not re-dispatch")

    def test_without_the_renewal_the_completion_would_be_rejected(self):
        # The same timing as above, but the lease is never renewed: the fencing in
        # complete() must then refuse. This is what makes the renewal test meaningful.
        self.github.hold_ticks = 2
        task_id = self.enqueue_c1()
        self.claim(task_id)
        self.clock.advance(200)                       # past the 120 s lease
        with self.assertRaises(LeaseRejected):
            self.runtime.complete("C1", task_id, worker_id=WORKER, expected_attempt=1,
                                  success=True, result={"output": contract.EXPECTED_OUTPUT})
        self.assertEqual(self.runtime.status_of(task_id), "RUNNING")


class NoSecondDispatchEver(LoopCase):
    def test_an_ambiguous_dispatch_is_resolved_by_lookup_not_by_a_second_post(self):
        self.github.fault = "ambiguous"
        task_id = self.enqueue_c1()
        claimed = self.claim(task_id)
        request_id = self.request_id(task_id, 1)

        first = self.tick(claimed)
        # The ambiguous POST is recorded as such; it is NOT retried. The lookup happens
        # on the next tick, which is why this tick reports the ambiguity itself.
        self.assertEqual(first["action"], "DISPATCH_AMBIGUOUS", first)
        self.assertEqual(self.github.dispatch_calls, 1)
        self.assertEqual(self.outbox.dispatch_status(request_id), "DISPATCHED")

        # The run did land; a later tick finds it by its deterministic name.
        self.github.fault = None
        self.github._materialise_run(424242, contract.build_dispatch_request(task_id, 1))
        self.clock.advance(30)
        second = self.tick(claimed)
        self.assertEqual(second["action"], "COMPLETED", second)
        self.assertGreaterEqual(self.github.lookup_calls, 1, "resolved by lookup")
        self.assertEqual(self.github.dispatch_calls, 1, "the retry must never re-POST")
        self.assertEqual(self.runtime.status_of(task_id), "SUCCEEDED")

    def test_a_finished_tick_is_idempotent(self):
        task_id = self.enqueue_c1()
        claimed = self.claim(task_id)
        self.assertEqual(self.tick(claimed)["action"], "COMPLETED")
        second = self.tick(claimed)
        self.assertEqual(second["action"], "ALREADY_COMPLETED", second)
        self.assertEqual(self.github.dispatch_calls, 1)
        self.assertEqual(len([r for r in self.runtime.evidence
                              if r["event_type"] == "TASK_COMPLETED"]), 1)


class OneTaskNeverPaysTwice(LoopCase):
    def test_a_new_attempt_reuses_the_sealed_result_instead_of_dispatching_again(self):
        # attempt 1 runs and its result is sealed, then the worker dies BEFORE calling
        # complete(). The lease expires, the Runtime requeues the task as attempt 2, and
        # attempt 2 is a new execution identity - which would dispatch a second, paid
        # model call for a task that already has an answer. The reuse guard prevents it.
        task_id = self.enqueue_c1()
        self.claim(task_id)
        request_id = self.request_id(task_id, 1)

        # Drive to RESULT_SEALED without completing, exactly as a crash would leave it.
        outbox_mod.drive_once(self.outbox, task_id, 1, send=self.github.send,
                              find_run=self.github.find_run)
        sealed = pull_result(self.outbox, task_id, 1, client=self.github)
        self.assertEqual(sealed["action"], "RESULT_SEALED", sealed)
        self.assertEqual(self.github.dispatch_calls, 1)
        self.outbox.close()

        # A restart re-opens the same durable outbox; the sealed result survived.
        self.outbox = outbox_mod.DispatchOutbox(os.path.join(self.tmp, "outbox.db"))
        self.assertEqual(self.outbox.dispatch_status(request_id), "COMPLETED")

        self.clock.advance(1000)
        self.assertEqual(self.runtime.recover_stale()["requeued"], 1)
        second = self.runtime.claim("C1", worker_id=WORKER, lease_s=LEASE_S,
                                    kinds=(contract.KIND,))
        self.assertEqual(second.attempts, 2, "a lost lease comes back as a new attempt")

        outcome = self.tick(second)

        self.assertTrue(outcome["reused"], outcome)
        self.assertEqual(outcome["reused_from_attempt"], 1)
        self.assertEqual(outcome["reused_from_request_id"], request_id)
        self.assertEqual(self.github.dispatch_calls, 1, "the second attempt must not pay")
        self.assertEqual(self.runtime.status_of(task_id), "SUCCEEDED")
        self.assertTrue(self.runtime.verify_evidence_chain())

        adopted = self.outbox.snapshot(self.request_id(task_id, 2))
        self.assertEqual(adopted["reused_from"], request_id)
        self.assertEqual(adopted["result_sha256"],
                         self.outbox.snapshot(request_id)["result_sha256"])
        # The adopted bytes still say attempt 1: a result is never rewritten to claim
        # an attempt that did not produce it.
        self.assertEqual(json.loads(adopted["result_json"])["attempt"], 1)
        completed = [r for r in self.runtime.evidence if r["event_type"] == "TASK_COMPLETED"]
        self.assertEqual(completed[0]["body"]["attempt"], 2)
        self.assertEqual(completed[0]["body"]["result"]["attempt"], 1)


class TheResumeLegIsWhatClosesTheLoop(LoopCase):
    """The defect that stopped the first deployment, pinned as a test.

    `Runtime.claim()` hands out `QUEUED` tasks only. A task this worker has taken is
    RUNNING and owned by it, so claim() will never return it again - which means a tick
    that only ever advanced what it had just claimed advanced each task exactly once,
    and the result leg never ran at all. `resume()` is the fix, and these tests are the
    difference between "a dispatch was sent" and "the loop closed".
    """

    def test_the_next_tick_finishes_what_the_previous_tick_dispatched(self):
        # The production shape: API version 2022-11-28 answers a dispatch with 204 and no
        # run id, so "accepted, id unknown" is the normal outcome, not an edge case.
        self.github.declare_run_id = False
        task_id = self.enqueue_c1()
        claimed = self.claim(task_id)

        first = self.tick(claimed)

        # A POST went out and its outcome is unknown - the outward word for that is
        # DISPATCHED, and the identity is deliberately left resolvable by lookup rather
        # than by another POST.
        self.assertEqual(first["action"], "DISPATCHED", first)
        self.assertEqual(first["state"], "DISPATCHED", first)
        self.assertEqual(self.github.dispatch_calls, 1)
        self.assertEqual(self.runtime.status_of(task_id), "RUNNING")

        # This is the whole bug in one line: the next tick cannot claim it, because the
        # Runtime only hands out QUEUED tasks and this one is RUNNING and ours.
        self.assertIsNone(self.runtime.claim("C1", worker_id=WORKER, lease_s=LEASE_S,
                                             kinds=(contract.KIND,)))

        second = self.resume(task_id, 1)

        request_id = self.request_id(task_id, 1)
        self.assertEqual(second["action"], "COMPLETED", second)
        self.assertEqual(self.github.dispatch_calls, 1, "one POST for the whole task")
        self.assertGreaterEqual(self.github.lookup_calls, 1, "resolved by lookup")
        self.assertEqual(self.runtime.status_of(task_id), "SUCCEEDED")
        self.assertEqual(self.outbox.dispatch_status(request_id), "COMPLETED")

        completed = self.completed_events()
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["body"]["attempt"], 1)
        self.assertEqual(completed[0]["body"]["result"]["execution_request_id"], request_id)
        self.assertTrue(self.runtime.verify_evidence_chain())

    def test_resuming_keeps_the_identity_rather_than_minting_a_new_one(self):
        self.github.declare_run_id = False
        task_id = self.enqueue_c1()
        self.tick(self.claim(task_id))
        self.resume(task_id, 1)

        request_id = self.request_id(task_id, 1)
        snapshot = self.outbox.snapshot(request_id)
        self.assertEqual(snapshot["dispatches_sent"], 1)
        self.assertEqual(snapshot["attempt"], 1)
        self.assertEqual(self.outbox.unfinished(), [], "one identity, and it is finished")
        # ... and it is the only identity that ever held work for this task.
        self.assertIsNone(self.outbox.terminal_for_task(task_id,
                                                        exclude_request_id=request_id))

    def test_the_runtime_fence_is_what_rejects_a_wrong_attempt(self):
        # expected_attempt is taken from the outbox row, and the Runtime is the authority
        # on whether it is right: the same call with any other attempt is refused.
        task_id = self.enqueue_c1()
        self.claim(task_id)
        with self.assertRaises(RuntimeErrorInvariant):
            self.runtime.complete("C1", task_id, worker_id=WORKER, expected_attempt=2,
                                  success=True, result={"output": contract.EXPECTED_OUTPUT})
        self.assertEqual(self.runtime.status_of(task_id), "RUNNING")


class ARestartResumesFromTheOutbox(LoopCase):
    """A process that dies mid-execution must not need the Runtime to hand work back."""

    def test_a_sealed_result_is_completed_after_a_restart_with_no_network(self):
        task_id = self.enqueue_c1()
        self.claim(task_id)
        # Drive to a sealed result and stop - what a crash between the pull and the
        # completion leaves behind.
        outbox_mod.drive_once(self.outbox, task_id, 1, send=self.github.send,
                              find_run=self.github.find_run)
        self.assertEqual(pull_result(self.outbox, task_id, 1,
                                     client=self.github)["action"], "RESULT_SEALED")
        self.assertEqual(self.github.dispatch_calls, 1)
        self.outbox.close()

        # A restart re-opens the same durable outbox. The lease survived too, because
        # the worker id is a constant rather than a per-process id - which is the reason
        # a resume can complete a task at all.
        self.outbox = outbox_mod.DispatchOutbox(os.path.join(self.tmp, "outbox.db"))
        self.addCleanup(self.outbox.close)

        # No pull may be needed: the result is sealed already, so the restarted worker
        # must complete it without touching the network.
        self.github.transport_error = RuntimeError("the network is gone")
        outcome = self.resume(task_id, 1)

        self.assertEqual(outcome["action"], "COMPLETED", outcome)
        self.assertEqual(self.runtime.status_of(task_id), "SUCCEEDED")
        self.assertEqual(self.github.dispatch_calls, 1)
        self.assertEqual(len(self.completed_events()), 1)

    def test_the_interrupted_identity_is_still_listed_as_unfinished(self):
        task_id = self.enqueue_c1()
        self.claim(task_id)
        outbox_mod.drive_once(self.outbox, task_id, 1, send=self.github.send,
                              find_run=self.github.find_run)
        self.assertEqual(
            self.outbox.unfinished(),
            [{"execution_request_id": self.request_id(task_id, 1),
              "runtime_task_id": task_id, "attempt": 1, "state": outbox_mod.RUN_BOUND,
              "dispatches_sent": 1, "github_run_id": 424242}])


class NoSecondDispatchAfterARestart(LoopCase):
    def test_a_dispatch_that_may_have_landed_is_looked_up_forever_never_re_posted(self):
        # The POST timed out and no run ever appeared. A restart must not send a second
        # POST - that is a second paid model call - and the identity must stay in flight
        # rather than be dropped or re-sent.
        self.github.fault = "ambiguous"
        task_id = self.enqueue_c1()
        claimed = self.claim(task_id)
        self.assertEqual(self.tick(claimed)["action"], "DISPATCH_AMBIGUOUS")
        self.assertEqual(self.github.dispatch_calls, 1)
        request_id = self.request_id(task_id, 1)
        self.assertEqual(self.outbox.dispatch_status(request_id), "DISPATCHED")
        self.outbox.close()

        self.outbox = outbox_mod.DispatchOutbox(os.path.join(self.tmp, "outbox.db"))
        self.addCleanup(self.outbox.close)

        for _ in range(3):
            self.clock.advance(30)
            outcome = self.resume(task_id, 1)
            self.assertEqual(outcome["action"], "LOOKUP_RUN_NOT_FOUND", outcome)
            self.assertTrue(outcome["renewed"], "an unresolved dispatch renews its lease")

        self.assertEqual(self.github.dispatch_calls, 1, "no second POST, ever")
        self.assertEqual(self.github.lookup_calls, 3)
        self.assertEqual(self.runtime.status_of(task_id), "RUNNING")
        self.assertEqual([row["execution_request_id"] for row in self.outbox.unfinished()],
                         [request_id])


class AFencedRefusalIsSettledNotRetried(LoopCase):
    """The one unrecoverable state, and the proof that settling it cannot re-dispatch.

    `complete()` is fenced on `status='RUNNING' AND lease_owner=this worker AND
    attempts==expected_attempt AND lease_until>now`, and `renew_task()` carries the same
    fence. So when the Runtime refuses a completion, the lease is already in the past and
    can never be extended again - and the attempt can never come back either, because a
    requeued task is handed out as the NEXT attempt. Retrying is therefore pointless, and
    leaving the row in flight would stop the worker from ever claiming anything else.
    """

    def test_a_refused_completion_settles_the_identity_instead_of_retrying_forever(self):
        # max_attempts=1, exactly like the first smoke task on the Runtime Host: when the
        # lease expires the task is escalated, so there is no next attempt to run either.
        task_id = self.enqueue_c1(max_attempts=1)
        self.claim(task_id)
        request_id = self.request_id(task_id, 1)
        outbox_mod.drive_once(self.outbox, task_id, 1, send=self.github.send,
                              find_run=self.github.find_run)
        self.assertEqual(pull_result(self.outbox, task_id, 1,
                                     client=self.github)["action"], "RESULT_SEALED")
        self.clock.advance(1000)
        self.assertEqual(self.runtime.recover_stale(), {"requeued": 0, "escalated": 1})
        self.assertEqual(self.runtime.status_of(task_id), "ESCALATED")

        outcome = self.resume(task_id, 1)

        self.assertEqual(outcome["action"], "ABANDONED", outcome)
        self.assertEqual(outcome["reason"], "RuntimeErrorInvariant")
        snapshot = self.outbox.snapshot(request_id)
        self.assertEqual(snapshot["state"], outbox_mod.ABANDONED)
        self.assertEqual(snapshot["abandon_reason"], "RuntimeErrorInvariant")
        self.assertEqual(self.outbox.dispatch_status(request_id), "FAILED")
        # Settled, not completed: the Runtime was never told anything, and the task is
        # exactly as the Runtime left it.
        self.assertEqual(self.outbox.unfinished(), [])
        self.assertEqual(self.completed_events(), [])
        self.assertEqual(self.runtime.status_of(task_id), "ESCALATED")
        self.assertEqual(self.github.dispatch_calls, 1)

    def test_a_transport_failure_does_not_settle_a_live_identity(self):
        # The same shape, but the failure is a transport error rather than a refusal by
        # the Runtime's fence. Nothing here is permanent, so the identity must survive
        # and be raised - settling it would strand a task that is still completable.
        self.github.declare_run_id = False
        task_id = self.enqueue_c1()
        self.tick(self.claim(task_id))
        request_id = self.request_id(task_id, 1)

        self.github.transport_error = RuntimeError("connection reset")
        with self.assertRaises(RuntimeError):
            self.resume(task_id, 1)

        self.assertNotEqual(self.outbox.snapshot(request_id)["state"], outbox_mod.ABANDONED)
        self.assertEqual([row["execution_request_id"] for row in self.outbox.unfinished()],
                         [request_id])
        self.assertEqual(self.runtime.status_of(task_id), "RUNNING")

        # ... and it completes normally once the transport recovers.
        self.github.transport_error = None
        self.assertEqual(self.resume(task_id, 1)["action"], "COMPLETED")
        self.assertEqual(self.runtime.status_of(task_id), "SUCCEEDED")

    def test_a_settled_identity_can_never_be_dispatched_again(self):
        self.github.declare_run_id = False
        task_id = self.enqueue_c1(max_attempts=1)
        self.tick(self.claim(task_id))
        request_id = self.request_id(task_id, 1)
        self.clock.advance(1000)
        self.runtime.recover_stale()
        self.assertEqual(self.resume(task_id, 1)["action"], "ABANDONED")

        # Every route back to a POST is closed.
        self.assertEqual(self.outbox.next_action(request_id), outbox_mod.ABANDONED)
        with self.assertRaises(contract.Refused):
            self.outbox.record_dispatch_sent(request_id)
        stepped = outbox_mod.drive_once(self.outbox, task_id, 1, send=self.github.send,
                                        find_run=self.github.find_run)
        self.assertEqual(stepped["action"], outbox_mod.ABANDONED)
        self.assertEqual(self.resume(task_id, 1)["action"], outbox_mod.ABANDONED)
        self.assertEqual(self.github.dispatch_calls, 1)

    def test_a_sealed_result_survives_settlement_so_the_next_attempt_still_adopts_it(self):
        # Settling must not throw away an answer we already paid for: the result stays
        # visible to terminal_for_task, so a later attempt of the same Runtime task
        # adopts those bytes instead of buying a second model call.
        self.github.declare_run_id = False
        task_id = self.enqueue_c1(max_attempts=2)
        self.tick(self.claim(task_id))
        # Seal the result, then let the lease die so attempt 1 can never complete.
        self.clock.advance(1000)
        self.assertEqual(self.resume(task_id, 1)["action"], "ABANDONED")
        request_id = self.request_id(task_id, 1)
        self.assertIsNotNone(self.outbox.terminal_result(request_id))

        # The Runtime requeues it and hands it out as attempt 2 - a new identity.
        self.assertEqual(self.runtime.recover_stale(), {"requeued": 1, "escalated": 0})
        second = self.runtime.claim("C1", worker_id=WORKER, lease_s=LEASE_S,
                                    kinds=(contract.KIND,))
        self.assertEqual(second.attempts, 2)

        outcome = self.tick(second)

        self.assertTrue(outcome["reused"], outcome)
        self.assertEqual(outcome["action"], "COMPLETED")
        self.assertEqual(self.github.dispatch_calls, 1, "attempt 2 must not pay")
        self.assertEqual(self.runtime.status_of(task_id), "SUCCEEDED")
        # The adopted bytes still say attempt 1: a result is never rewritten to claim an
        # attempt that did not produce it.
        adopted = self.outbox.snapshot(self.request_id(task_id, 2))
        self.assertEqual(adopted["reused_from"], request_id)
        self.assertEqual(json.loads(adopted["result_json"])["attempt"], 1)


class TheUnfinishedSetIsWhatARestartResumes(LoopCase):
    def test_unfinished_excludes_finished_work_and_orders_oldest_first(self):
        done = self.enqueue_c1(key="done")
        self.assertEqual(self.tick(self.claim(done))["action"], "COMPLETED")
        first = self.enqueue_c1(key="first")
        second = self.enqueue_c1(key="second")
        outbox_mod.drive_once(self.outbox, first, 1, send=self.github.send,
                              find_run=self.github.find_run)
        self.clock.advance(60)
        outbox_mod.drive_once(self.outbox, second, 1, send=self.github.send,
                              find_run=self.github.find_run)

        self.assertEqual([row["runtime_task_id"] for row in self.outbox.unfinished()],
                         [first, second], "oldest first")

    def test_unfinished_stops_at_its_limit(self):
        ids = [self.enqueue_c1(key="k%d" % n) for n in range(3)]
        for task_id in ids:
            outbox_mod.drive_once(self.outbox, task_id, 1, send=self.github.send,
                                  find_run=self.github.find_run)
        self.assertEqual(len(self.outbox.unfinished(limit=2)), 2)
        limited = self.outbox.unfinished(limit=1)
        self.assertEqual(len(limited), 1)
        self.assertIn(limited[0]["runtime_task_id"], ids)

    def test_unfinished_does_not_include_finished_or_settled_work(self):
        done = self.enqueue_c1(key="done")
        self.assertEqual(self.tick(self.claim(done))["action"], "COMPLETED")

        self.github.declare_run_id = False          # so the next tick cannot finish it
        stuck = self.enqueue_c1(key="stuck", max_attempts=1)
        self.assertEqual(self.tick(self.claim(stuck))["action"], "DISPATCHED")
        self.clock.advance(1000)
        self.assertEqual(self.runtime.recover_stale(), {"requeued": 0, "escalated": 1})
        self.assertEqual(self.resume(stuck, 1)["action"], "ABANDONED")

        live = self.enqueue_c1(key="live")
        outbox_mod.drive_once(self.outbox, live, 1, send=self.github.send,
                              find_run=self.github.find_run)

        self.assertEqual([row["runtime_task_id"] for row in self.outbox.unfinished()],
                         [live], "only the work still in flight")

    def test_a_completed_execution_cannot_be_settled(self):
        task_id = self.enqueue_c1()
        request_id = self.request_id(task_id, 1)
        self.tick(self.claim(task_id))
        self.assertEqual(self.outbox.dispatch_status(request_id), "COMPLETED")
        with self.assertRaises(contract.Refused):
            self.outbox.abandon(request_id, "why not")


class TheLoopOnlyRunsItsOwnWork(LoopCase):
    def test_a_probe_task_is_never_dispatched(self):
        task_id = self.runtime.enqueue("C1", "RUNTIME_PROBE", {"probe": 1},
                                       idempotency_key="probe")
        claimed = self.runtime.claim("C1", worker_id=WORKER, lease_s=LEASE_S)
        outcome = self.tick(claimed)
        self.assertEqual(outcome["action"], "NOT_A_C1_TASK")
        self.assertEqual(outcome["reason"], "KIND_MISMATCH")
        self.assertEqual(self.github.dispatch_calls, 0)

    def test_a_wrong_payload_is_never_dispatched(self):
        task_id = self.runtime.enqueue("C1", contract.KIND, {"schema_version": 1,
                                                            "smoke_id": "SOMETHING_ELSE"},
                                       idempotency_key="wrong-payload")
        claimed = self.runtime.claim("C1", worker_id=WORKER, lease_s=LEASE_S,
                                     kinds=(contract.KIND,))
        outcome = self.tick(claimed)
        self.assertEqual(outcome["action"], "NOT_A_C1_TASK")
        self.assertEqual(outcome["reason"], "PAYLOAD_MISMATCH")
        self.assertEqual(self.github.dispatch_calls, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
