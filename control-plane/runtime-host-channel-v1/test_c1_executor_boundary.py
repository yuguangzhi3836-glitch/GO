"""The executor boundary: which executor owns which task kind, and which owns which outbox.

What this file is for
---------------------
The Persistent Runtime proofs (exactly-once dispatch, restart recovery, attempt fencing)
were all established with a single executor and a single outbox. The moment a second
executor exists, three questions that had one obvious answer stop having one:

  * which task kind does each executor claim?
  * which durable outbox does each executor resume from?
  * where does an execution identity come from - the claim, or something a caller passed?

Each of those has a measured failure behind it, and this file tests the answers rather than
the intentions:

  A  `claim(kinds=...)` is a queue read, not a lookup. It returns the oldest QUEUED task
     matching the filter, so "the task I just enqueued" is not something a caller may
     assume. Round 3 measured what happens when a driver assumed it: it built an identity
     out of `enqueue()`'s task id and `claim()`'s attempt - two different tasks - and the
     Runtime's fence rejected the completion after the dispatch had already been paid for.
  B  a kind is the routing. Two executors claiming one kind is a race whose loser is
     whichever executor restarted last, so the two sets must be disjoint - in both
     directions, including at the cheap second gate inside the loop.
  C  the outbox is what remembers work in progress, so one executor must never resume
     another's unfinished execution. Isolating the outbox by path is not enough on its own:
     the loop re-checks the kind of the identity it is asked to resume.
  D  none of the above may cost the properties the single-executor proofs established:
     after a restart the same execution is resumed, its identity is unchanged, and a second
     dispatch is still forbidden.

What is real and what is a double
---------------------------------
  REAL      `c1_execution_contract`, `c1_dispatch_outbox`, `c1_execution_loop`,
            `c1_worker` and `c1_ghaw_builder_worker`, and the Runtime
            (`RuntimeDouble`, reused from `test_c1_execution_loop` - the same
            fencing-faithful double the single-executor proofs used).
  DOUBLE    the GitHub transport, in two shapes: one that holds every run open forever
            (so a tick can only ever reach AWAIT_RESULT) and one that seals a
            gh-aw-shaped result offline.
  NOT PROVEN HERE
            that a gh-aw workflow exists, that it is registered on `main`, or that a
            dispatch reaches it. There is no gh-aw executor to run yet - registration is
            U1, tracked separately - which is why the gh-aw transport synthesises the
            result document instead of running one. What that synthesised document proves
            is that the class's identity, sealing and acceptance rules are wired, not that
            the Builder works.

No network, no credential, no paid call, and no dispatch to GitHub.
"""
import ast
import contextlib
import io
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
import c1_execution_loop as loop_mod  # noqa: E402
import c1_ghaw_builder_worker as ghaw  # noqa: E402
import c1_issue_ingress as ingress  # noqa: E402
import c1_worker as worker  # noqa: E402
import test_c1_execution_loop as harness  # noqa: E402

GH = contract.GHAW_BUILDER_KIND
WORKER = "gh-aw-builder-boundary-test"
LEASE_S = 120


def payload(external_task_id):
    """One real-task payload, built through the shared contract, for either real class."""
    return contract.build_task_payload(
        cell_id="C01",
        external_task_id=external_task_id,
        objective="Boundary test: derive the prompt from this payload.",
        scope="No real execution. Answer with one short line.")


def spec_of(task_kind, task_payload):
    return contract.task_spec(task_kind, task_payload)


class HoldingTransport:
    """Offline GitHub that records dispatches and never finishes a run.

    A tick driven through this can only ever reach AWAIT_RESULT, which is what makes it
    useful for the outbox-isolation case: the point there is *which* identity was driven,
    never the bytes of a result.
    """

    def __init__(self, *, run_id=700000):
        self.dispatches = []
        self._next = run_id

    def send(self, request):
        self.dispatches.append(request)
        self._next += 1
        return ("sent", self._next)

    def find_run(self, run_name):
        return None

    def find_run_by_name(self, name):
        return None

    def get_run(self, run_id):
        return {"id": run_id, "status": "in_progress", "conclusion": None,
                "run_attempt": 1, "head_sha": "0" * 40}

    def download_artifact(self, run_id, name):
        return None


class GhawSealingTransport:
    """Offline GitHub that seals a gh-aw-shaped result for the class it belongs to.

    It is stateful on purpose and must NOT be recreated across a simulated restart: the
    GitHub side persists, only the worker dies. `get_run` answers from what `send` bound,
    exactly as the real service would, and the run may be held open for a few polls.
    """

    def __init__(self, *, run_id=515151, hold_ticks=0):
        self.dispatch_calls = 0
        self.hold_ticks = hold_ticks
        self.runs = {}
        self.artifacts = {}
        self._next = run_id

    def send(self, request):
        self.dispatch_calls += 1
        run_id = self._next
        self._next += 1
        document = self._seal(run_id, request)
        raw = contract.canonical(document).encode("utf-8")
        self.runs[run_id] = {"id": run_id, "run_attempt": 1, "status": "completed",
                             "conclusion": "success", "head_sha": "0" * 40,
                             "name": contract.run_identity_name(
                                 request["runtime_task_id"], request["attempt"],
                                 request["execution_request_id"])}
        self.artifacts[(run_id, "c1-ai-execution-result-"
                        + request["execution_request_id"])] = {
            "bytes": raw,
            "digest": "sha256:" + contract.sha256_hex(raw.decode("utf-8"))}
        return ("sent", run_id)

    def _seal(self, run_id, request):
        output = "gh-aw Builder answer for %s" % request["runtime_task_id"]
        return {
            "version": contract.SCHEMA_VERSION,
            "kind": contract.RESULT_KIND,
            "runtime_task_id": request["runtime_task_id"],
            "attempt": request["attempt"],
            "execution_request_id": request["execution_request_id"],
            "github_run_id": run_id,
            "github_run_attempt": 1,
            "provider": contract.PROVIDER_GHAW_BUILDER,
            "model": "gh-aw-offline-double",
            "response_id": "stub:gh-aw-no-model-call",
            "status": "SUCCEEDED",
            "output_sha256": contract.output_sha256(output),
            "output": output,
            "accepted": True,
            "reused_terminal_result": False,
            "authorizes_any_action": False,
        }

    def get_run(self, run_id):
        run = self.runs.get(run_id)
        if run is None:
            return None
        if self.hold_ticks > 0:
            self.hold_ticks -= 1
            return dict(run, status="in_progress", conclusion=None)
        return dict(run)

    def find_run(self, run_name):
        for run in self.runs.values():
            if run["name"] == run_name:
                return run["id"]
        return None

    def find_run_by_name(self, name):
        for run in self.runs.values():
            if run["name"] == name:
                return dict(run)
        return None

    def download_artifact(self, run_id, name):
        return self.artifacts.get((run_id, name))


class BoundaryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="c1-boundary-")
        self.clock = harness.Clock()
        self.runtime = harness.RuntimeDouble(self.clock)
        self.outbox = outbox_mod.DispatchOutbox(
            os.path.join(self.tmp, "outbox-ghaw-builder.db"), clock=self.outbox_clock)
        self.addCleanup(self.outbox.close)

    def outbox_clock(self):
        return "%020.6f" % self.clock.now

    def enqueue(self, kind, task_payload, *, key, max_attempts=2):
        return self.runtime.enqueue("C1", kind, task_payload, idempotency_key=key,
                                    max_attempts=max_attempts)

    def claim_ghaw(self, worker_id=WORKER):
        return self.runtime.claim("C1", worker_id=worker_id, lease_s=LEASE_S, kinds=(GH,))


class ClaimIsAQueueReadNotALookup(BoundaryCase):
    """A - the identity comes from the claim, and from nowhere else."""

    def test_the_execution_uses_the_claimed_task_even_when_it_is_not_the_newest(self):
        # A is already in the queue and has been taken once; B is enqueued right after.
        task_a = self.enqueue(GH, payload("BOUNDARY-A"), key="k-a")
        self.assertEqual(self.claim_ghaw().task_id, task_a)
        self.clock.advance(LEASE_S + 10)
        self.runtime.recover_stale()
        self.assertEqual(self.runtime.status_of(task_a), "QUEUED")

        task_b = self.enqueue(GH, payload("BOUNDARY-B"), key="k-b")
        self.assertNotEqual(task_a, task_b)

        claimed = self.claim_ghaw()
        # The oldest QUEUED task wins, so the claim is A - not the task just enqueued.
        self.assertEqual(claimed.task_id, task_a)
        self.assertEqual(claimed.attempts, 2)
        self.assertNotEqual(claimed.task_id, task_b)

        identity = loop_mod.claimed_identity(claimed)
        self.assertEqual(identity["task_id"], task_a)
        self.assertEqual(identity["attempt"], claimed.attempts)
        self.assertEqual(identity["kind"], GH)
        self.assertEqual(identity["payload"], payload("BOUNDARY-A"))

        honest_id = contract.execution_request_id(
            identity["task_id"], identity["attempt"], spec_of(GH, identity["payload"]))
        # The Round-3 shape: B's task id with A's attempt. Same attempt, wrong task -
        # which is exactly why the Runtime's fence can only catch it after the fact.
        mixed_id = contract.execution_request_id(
            task_b, claimed.attempts, spec_of(GH, payload("BOUNDARY-B")))
        self.assertNotEqual(honest_id, mixed_id)

        transport = HoldingTransport()
        outcome = loop_mod.advance(self.outbox, self.runtime, claimed, worker_id=WORKER,
                                   client=transport, lease_s=LEASE_S, clock=self.clock,
                                   claimable_kinds=ghaw.CLAIM_KINDS)
        self.assertEqual(outcome["runtime_task_id"], task_a)
        self.assertEqual(outcome["attempt"], 2)
        self.assertEqual(outcome["execution_request_id"], honest_id)

        dispatched = transport.dispatches[0]
        self.assertEqual(dispatched["runtime_task_id"], task_a)
        self.assertEqual(dispatched["attempt"], 2)
        self.assertEqual(dispatched["payload"]["external_task_id"], "BOUNDARY-A")
        self.assertEqual(dispatched["execution_request_id"], honest_id)
        self.assertNotEqual(dispatched["execution_request_id"], mixed_id)

    def test_the_mixed_identity_the_round_three_driver_built_is_refused(self):
        task_a = self.enqueue(GH, payload("BOUNDARY-A"), key="k-a")
        self.claim_ghaw()
        self.clock.advance(LEASE_S + 10)
        self.runtime.recover_stale()
        task_b = self.enqueue(GH, payload("BOUNDARY-B"), key="k-b")
        claimed = self.claim_ghaw()
        self.assertEqual(claimed.task_id, task_a)
        self.assertEqual(claimed.attempts, 2)

        # B was never claimed, so it is QUEUED and the Runtime's fence refuses anything
        # that tries to settle it - which is the fail-closed half of the Round-3 story.
        with self.assertRaises(harness.RuntimeErrorInvariant):
            self.runtime.complete("C1", task_b, worker_id=WORKER, expected_attempt=2,
                                  success=True, result={})

    def test_a_claim_missing_a_fact_is_refused_rather_than_repaired(self):
        class Partial:
            task_id = "rt_" + "1" * 32
            attempts = 1
            kind = GH

        with self.assertRaises(contract.Refused) as raised:
            loop_mod.claimed_identity(Partial())
        self.assertEqual(raised.exception.reason, "CLAIMED_OBJECT_INCOMPLETE:payload")

        class Unusable:
            task_id = "rt_" + "2" * 32
            attempts = 0
            kind = GH
            payload = payload("BOUNDARY-A")

        with self.assertRaises(contract.Refused) as raised:
            loop_mod.claimed_identity(Unusable())
        self.assertEqual(raised.exception.reason,
                         "CLAIMED_IDENTITY_INVALID:ATTEMPT_NOT_POSITIVE_INT")


class TheTwoKindSetsAreDisjoint(BoundaryCase):
    """B - a kind is the routing, so a kind belongs to exactly one executor."""

    def test_the_gh_aw_executor_owns_one_kind_and_the_responses_executor_none_of_it(self):
        self.assertEqual(ghaw.CLAIM_KINDS, ("GHAW_BUILDER_V1",))
        self.assertEqual(worker.CLAIM_KINDS, ("AI_WORK_V1", "AI_TASK_V1"))
        self.assertEqual(set(ghaw.CLAIM_KINDS) & set(worker.CLAIM_KINDS), set())
        self.assertNotIn(contract.REAL_TASK_KIND, ghaw.CLAIM_KINDS)
        self.assertNotIn(GH, worker.CLAIM_KINDS)
        for probe in ("RUNTIME_PROBE", "RUNTIME_C1_PROBE_V1"):
            self.assertNotIn(probe, ghaw.CLAIM_KINDS)
            self.assertNotIn(probe, worker.CLAIM_KINDS)

    def test_the_c01_ingress_produces_the_kind_only_the_gh_aw_executor_claims(self):
        self.assertEqual(ingress.INGRESS_KIND, GH)
        self.assertEqual(ingress.INGRESS_KIND, "GHAW_BUILDER_V1")
        self.assertIn(ingress.INGRESS_KIND, ghaw.CLAIM_KINDS)
        self.assertNotIn(ingress.INGRESS_KIND, worker.CLAIM_KINDS)

    def test_the_gh_aw_worker_claims_only_its_own_kind_and_leaves_the_rest_queued(self):
        smoke = self.enqueue("AI_WORK_V1", contract.PAYLOAD, key="k-smoke")
        real = self.enqueue(contract.REAL_TASK_KIND, payload("BOUNDARY-REAL"), key="k-real")
        probe = self.enqueue("RUNTIME_PROBE", {"probe": "fixture"}, key="k-probe")
        mine = self.enqueue(GH, payload("BOUNDARY-GH"), key="k-gh")

        transport = HoldingTransport()
        result = ghaw.tick(self.runtime, self.outbox, transport, worker_id=WORKER,
                           clock=self.clock)
        self.assertEqual(result["status"], "ADVANCED")
        self.assertEqual(result["kind"], GH)
        self.assertEqual(result["runtime_task_id"], mine)

        # The other executor's kinds were never even looked at: still QUEUED, attempts 0.
        for task_id in (smoke, real, probe):
            self.assertEqual(self.runtime.status_of(task_id), "QUEUED")
            self.assertEqual(self.runtime.tasks[task_id].attempts, 0)
        self.assertEqual(self.runtime.status_of(mine), "RUNNING")
        self.assertEqual(len(transport.dispatches), 1)

    def test_the_responses_worker_cannot_claim_the_gh_aw_kind(self):
        mine = self.enqueue(GH, payload("BOUNDARY-GH"), key="k-gh")
        transport = HoldingTransport()
        result = worker.tick(self.runtime, self.outbox, transport, worker_id="responses",
                             clock=self.clock)
        self.assertEqual(result["status"], "IDLE")
        self.assertEqual(result["claimed"], False)
        self.assertEqual(self.runtime.status_of(mine), "QUEUED")
        self.assertEqual(self.runtime.tasks[mine].attempts, 0)
        self.assertEqual(transport.dispatches, [])

    def test_the_loop_refuses_a_kind_the_executor_does_not_own(self):
        for claimed_kind, kinds in ((GH, worker.CLAIM_KINDS),
                                    ("AI_WORK_V1", ghaw.CLAIM_KINDS),
                                    (contract.REAL_TASK_KIND, ghaw.CLAIM_KINDS)):
            with self.subTest(kind=claimed_kind):
                self.enqueue(claimed_kind, contract.PAYLOAD if claimed_kind == "AI_WORK_V1"
                             else payload("BOUNDARY-X"), key="k-" + claimed_kind)
                claimed = self.runtime.claim("C1", worker_id="cross", lease_s=LEASE_S,
                                             kinds=(claimed_kind,))
                transport = HoldingTransport()
                outcome = loop_mod.advance(self.outbox, self.runtime, claimed,
                                           worker_id="cross", client=transport,
                                           lease_s=LEASE_S, clock=self.clock,
                                           claimable_kinds=kinds)
                self.assertEqual(outcome["action"], "NOT_A_C1_TASK")
                self.assertEqual(outcome["reason"], "KIND_MISMATCH")
                self.assertEqual(transport.dispatches, [])

    def test_each_executor_reports_its_own_boundary_and_not_the_others(self):
        reported = {}
        for module, name in ((worker, "responses"), (ghaw, "gh-aw")):
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = module.main(["--check"], token_loader=lambda: "present")
            self.assertEqual(code, 0)
            reported[name] = json.loads(buffer.getvalue().strip())
        self.assertEqual(reported["responses"]["claimed_kinds"],
                         ["AI_WORK_V1", "AI_TASK_V1"])
        self.assertEqual(reported["gh-aw"]["claimed_kinds"], ["GHAW_BUILDER_V1"])
        self.assertNotEqual(reported["responses"]["outbox_db"],
                            reported["gh-aw"]["outbox_db"])
        # One Runtime, two workers: the two executors must not disagree about the kernel.
        self.assertEqual(reported["responses"]["runtime_db"],
                         reported["gh-aw"]["runtime_db"])
        self.assertEqual(ghaw.OUTBOX_DB, "/var/lib/go-runtime-c1/outbox-ghaw-builder.db")
        self.assertEqual(worker.OUTBOX_DB, "/var/lib/go-runtime-c1/outbox.db")
        self.assertNotEqual(ghaw.WORKER_ID, worker.WORKER_ID)


class TheOutboxesAreIsolated(BoundaryCase):
    """C - one executor / one execution loop owns one durable outbox."""

    def _in_flight(self, outbox, kind, task_payload, key, client):
        task_id = self.enqueue(kind, task_payload, key=key)
        claimed = self.runtime.claim("C1", worker_id="boundary", lease_s=LEASE_S,
                                     kinds=(kind,))
        self.assertEqual(claimed.task_id, task_id)
        outcome = loop_mod.advance(outbox, self.runtime, claimed, worker_id="boundary",
                                   client=client, lease_s=LEASE_S, clock=self.clock,
                                   claimable_kinds=(kind,))
        # The run is bound and the tick is waiting on it, so the identity is in flight.
        self.assertEqual(outcome["state"], "RUNNING")
        self.assertEqual(outbox.snapshot(outcome["execution_request_id"])["state"],
                         "RUN_BOUND")
        return task_id, claimed.attempts, outcome["execution_request_id"]

    def test_a_restart_resumes_only_the_identity_of_its_own_outbox(self):
        responses_outbox = outbox_mod.DispatchOutbox(
            os.path.join(self.tmp, "outbox.db"), clock=self.outbox_clock)
        self.addCleanup(responses_outbox.close)
        self.assertNotEqual(responses_outbox.db_path, self.outbox.db_path)

        responses_task, _, responses_id = self._in_flight(
            responses_outbox, "AI_WORK_V1", contract.PAYLOAD, "k-smoke", HoldingTransport())
        ghaw_task, _, ghaw_id = self._in_flight(
            self.outbox, GH, payload("BOUNDARY-GH"), "k-gh", HoldingTransport())
        self.assertNotEqual(responses_id, ghaw_id)

        # A restart is a fresh read of the same durable file, and nothing else.
        self.outbox.close()
        self.outbox = outbox_mod.DispatchOutbox(self.outbox.db_path, clock=self.outbox_clock)
        self.addCleanup(self.outbox.close)

        self.assertEqual([row["runtime_task_id"] for row in self.outbox.unfinished()],
                         [ghaw_task])
        self.assertEqual([row["runtime_task_id"] for row in responses_outbox.unfinished()],
                         [responses_task])

        transport = HoldingTransport()
        result = ghaw.tick(self.runtime, self.outbox, transport, worker_id=WORKER,
                           clock=self.clock)
        self.assertEqual(result["status"], "RESUMED")
        self.assertEqual(result["runtime_task_id"], ghaw_task)
        self.assertEqual(transport.dispatches, [], "a resume must never dispatch again")

    def test_resuming_a_row_of_a_foreign_kind_in_your_own_outbox_is_refused(self):
        ghaw_task, ghaw_attempt, ghaw_id = self._in_flight(
            self.outbox, GH, payload("BOUNDARY-GH"), "k-gh", HoldingTransport())

        # The Responses executor is pointed at the gh-aw outbox. The row is right there and
        # its kind is the only thing standing between it and being resumed by an executor
        # that does not own it - which is exactly why the isolation has to be a contract
        # and not a convention about file paths.
        with self.assertRaises(contract.Refused) as raised:
            loop_mod.resume(self.outbox, self.runtime, ghaw_task, ghaw_attempt,
                            worker_id="responses", client=HoldingTransport(),
                            lease_s=LEASE_S, clock=self.clock,
                            claimable_kinds=worker.CLAIM_KINDS)
        self.assertEqual(raised.exception.reason,
                         "RESUME_KIND_NOT_OWNED_BY_THIS_EXECUTOR:" + GH)
        # Refused, not settled, not dispatched: the owning executor's state is intact.
        self.assertEqual(self.outbox.snapshot(ghaw_id)["state"], "RUN_BOUND")
        self.assertEqual(self.outbox.snapshot(ghaw_id)["dispatches_sent"], 1)

    def test_resuming_an_identity_of_a_kind_the_executor_does_not_own_is_refused(self):
        responses_outbox = outbox_mod.DispatchOutbox(
            os.path.join(self.tmp, "outbox.db"), clock=self.outbox_clock)
        self.addCleanup(responses_outbox.close)
        responses_task, responses_attempt, _ = self._in_flight(
            responses_outbox, "AI_WORK_V1", contract.PAYLOAD, "k-smoke", HoldingTransport())

        # The gh-aw executor is handed the Responses executor's identity. Both the kind
        # check and the "not in this outbox at all" check refuse it, and neither settles
        # or dispatches anything.
        with self.assertRaises(contract.Refused) as raised:
            loop_mod.resume(self.outbox, self.runtime, responses_task, responses_attempt,
                            worker_id=WORKER, client=HoldingTransport(),
                            lease_s=LEASE_S, clock=self.clock,
                            claimable_kinds=ghaw.CLAIM_KINDS)
        self.assertEqual(raised.exception.reason, "RESUME_IDENTITY_NOT_IN_THIS_OUTBOX")
        self.assertEqual(self.outbox.unfinished(), [])

        # And the same identity, offered to the executor that owns it, still resumes.
        outcome = loop_mod.resume(responses_outbox, self.runtime, responses_task,
                                  responses_attempt, worker_id="responses",
                                  client=HoldingTransport(), lease_s=LEASE_S,
                                  clock=self.clock,
                                  claimable_kinds=worker.CLAIM_KINDS)
        self.assertEqual(outcome["runtime_task_id"], responses_task)


class ARestartKeepsTheExactlyOnceProperties(BoundaryCase):
    """D - the gh-aw class does not cost what the single-executor proofs established."""

    def test_a_restart_resumes_the_same_identity_without_a_second_dispatch(self):
        # One poll of the run is reported as still running, so the first tick binds the run
        # and dies; the tick after the restart is the one that pulls and completes it.
        transport = GhawSealingTransport(hold_ticks=1)
        task_id = self.enqueue(GH, payload("BOUNDARY-RESTART"), key="k-restart")
        claimed = self.claim_ghaw()
        self.assertEqual(claimed.task_id, task_id)

        # ---- process A: dispatch, bind the run, then die hard ----------------------
        first = loop_mod.advance(self.outbox, self.runtime, claimed, worker_id=WORKER,
                                 client=transport, lease_s=LEASE_S, clock=self.clock,
                                 claimable_kinds=ghaw.CLAIM_KINDS)
        self.assertEqual(first["state"], "RUNNING")
        request_id = first["execution_request_id"]
        self.assertEqual(transport.dispatch_calls, 1)

        snapshot = self.outbox.snapshot(request_id)
        self.assertEqual(snapshot["dispatches_sent"], 1)
        self.assertEqual(snapshot["state"], "RUN_BOUND")

        # ---- process B: a brand new outbox handle over the same durable file -------
        self.outbox.close()
        self.outbox = outbox_mod.DispatchOutbox(self.outbox.db_path, clock=self.outbox_clock)
        self.addCleanup(self.outbox.close)

        stored = self.outbox.stored_request(task_id, claimed.attempts)
        self.assertEqual(stored["execution_request_id"], request_id)
        self.assertEqual(stored["task_kind"], GH)
        self.assertEqual(stored["provider"], contract.PROVIDER_GHAW_BUILDER)

        resumed = ghaw.tick(self.runtime, self.outbox, transport, worker_id=WORKER,
                            clock=self.clock)
        self.assertEqual(resumed["status"], "RESUMED")
        self.assertEqual(resumed["runtime_task_id"], task_id)
        self.assertEqual(resumed["action"], "COMPLETED")
        self.assertEqual(transport.dispatch_calls, 1, "a restart must not dispatch again")
        self.assertEqual(self.runtime.status_of(task_id), "SUCCEEDED")
        self.assertEqual(self.outbox.snapshot(request_id)["state"], "COMPLETED")

    def test_the_identity_the_resumed_tick_used_is_the_one_the_first_tick_registered(self):
        # The run is held open for one poll, so the first tick binds it and the second has
        # to finish it - which is the shape a restart actually has.
        transport = GhawSealingTransport(hold_ticks=1)
        task_id = self.enqueue(GH, payload("BOUNDARY-ID"), key="k-id")
        claimed = self.claim_ghaw()
        first = loop_mod.advance(self.outbox, self.runtime, claimed, worker_id=WORKER,
                                 client=transport, lease_s=LEASE_S, clock=self.clock,
                                 claimable_kinds=ghaw.CLAIM_KINDS)
        self.assertEqual(first["state"], "RUNNING")
        transport.dispatch_calls = 0
        resumed = loop_mod.resume(self.outbox, self.runtime, task_id, claimed.attempts,
                                  worker_id=WORKER, client=transport, lease_s=LEASE_S,
                                  clock=self.clock, claimable_kinds=ghaw.CLAIM_KINDS)
        self.assertEqual(resumed["execution_request_id"], first["execution_request_id"])
        self.assertEqual(resumed["action"], "COMPLETED")
        self.assertEqual(transport.dispatch_calls, 0)
        self.assertEqual(self.runtime.status_of(task_id), "SUCCEEDED")

    def test_a_second_dispatch_for_one_identity_is_still_forbidden(self):
        transport = GhawSealingTransport(hold_ticks=1)
        task_id = self.enqueue(GH, payload("BOUNDARY-ONCE"), key="k-once")
        claimed = self.claim_ghaw()
        first = loop_mod.advance(self.outbox, self.runtime, claimed, worker_id=WORKER,
                                 client=transport, lease_s=LEASE_S, clock=self.clock,
                                 claimable_kinds=ghaw.CLAIM_KINDS)
        request_id = first["execution_request_id"]
        self.assertEqual(self.outbox.snapshot(request_id)["dispatches_sent"], 1)
        with self.assertRaises(contract.Refused) as raised:
            self.outbox.record_dispatch_sent(request_id)
        self.assertEqual(raised.exception.reason, "SECOND_DISPATCH_FORBIDDEN")
        # The same tick, run again, is idempotent: it pulls and completes, and sends
        # nothing further.
        again = loop_mod.resume(self.outbox, self.runtime, task_id, claimed.attempts,
                                worker_id=WORKER, client=transport, lease_s=LEASE_S,
                                clock=self.clock, claimable_kinds=ghaw.CLAIM_KINDS)
        self.assertEqual(again["execution_request_id"], request_id)
        self.assertEqual(self.outbox.snapshot(request_id)["dispatches_sent"], 1)


class TheBoundaryIsStructural(unittest.TestCase):
    """The parts of U3/U10 that are properties of the source, not of a run."""

    def _calls(self, source, attribute):
        tree = ast.parse(source)
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == attribute:
                found.append(node)
        return found

    def test_no_executor_reads_priority(self):
        for name in ("c1_execution_loop.py", "c1_worker.py", "c1_ghaw_builder_worker.py"):
            source = (HERE / name).read_text(encoding="utf-8")
            tree = ast.parse(source)
            with self.subTest(module=name):
                for node in ast.walk(tree):
                    if isinstance(node, ast.Attribute):
                        self.assertNotEqual(node.attr, "priority",
                                            "%s reads priority" % name)
                    if isinstance(node, ast.Name):
                        self.assertNotEqual(node.id, "priority",
                                            "%s reads priority" % name)

    def test_the_claim_call_can_never_select_a_task_by_id(self):
        for name, expected_arguments in (("c1_worker.py", 1),
                                         ("c1_ghaw_builder_worker.py", 1)):
            source = (HERE / name).read_text(encoding="utf-8")
            calls = self._calls(source, "claim")
            with self.subTest(module=name):
                for call in calls:
                    keywords = {keyword.arg for keyword in call.keywords}
                    self.assertEqual(len(call.args), expected_arguments)
                    self.assertNotIn("task_id", keywords)
                    self.assertLessEqual(keywords, {"worker_id", "lease_s", "kinds"})

    def test_the_shared_loop_is_not_reimplemented_for_the_second_executor(self):
        source = (HERE / "c1_ghaw_builder_worker.py").read_text(encoding="utf-8")
        for forbidden in ("def _drive", "def _complete", "def _abandon",
                          "DispatchOutbox(", "sqlite3"):
            with self.subTest(token=forbidden):
                self.assertNotIn(forbidden, source)
        # No class, no state of its own: the executor is a boundary, not an implementation.
        self.assertEqual([node for node in ast.walk(ast.parse(source))
                          if isinstance(node, ast.ClassDef)], [])
        for reused in ("from c1_worker import", "tick as _shared_tick",
                       "main as _shared_main"):
            with self.subTest(token=reused):
                self.assertIn(reused, source)

    def test_the_two_real_classes_can_never_share_an_execution_identity(self):
        task_payload = payload("BOUNDARY-CLASS")
        task_id, attempt = "rt_" + "3" * 32, 1
        real = contract.execution_request_id(
            task_id, attempt, spec_of(contract.REAL_TASK_KIND, task_payload))
        ghaw_builder = contract.execution_request_id(
            task_id, attempt, spec_of(GH, task_payload))
        self.assertNotEqual(real, ghaw_builder)
        self.assertNotEqual(contract.provider_for_kind(contract.REAL_TASK_KIND),
                            contract.provider_for_kind(GH))
        self.assertNotEqual(contract.workflow_file_for_kind(contract.REAL_TASK_KIND),
                            contract.workflow_file_for_kind(GH))

    def test_the_gh_aw_workflow_target_is_declared_but_not_registered(self):
        self.assertEqual(contract.GHAW_BUILDER_WORKFLOW_FILE,
                         "c1-gh-aw-builder-v1.lock.yml")
        workflows = Path(__file__).resolve().parents[2] / ".github" / "workflows"
        present = {path.name for path in workflows.iterdir()} if workflows.is_dir() else set()
        # U1 is not this round: the file this class will be dispatched to does not exist
        # yet, and if it ever does the assertion below is what will make whoever added it
        # look at the class that points at it.
        self.assertNotIn(contract.GHAW_BUILDER_WORKFLOW_FILE, present)
        self.assertIn(contract.WORKFLOW_FILE, present)


if __name__ == "__main__":
    unittest.main()
