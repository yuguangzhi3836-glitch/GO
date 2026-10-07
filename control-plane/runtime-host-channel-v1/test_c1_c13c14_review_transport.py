"""U7B: the C13/C14 sealed round, carried by the Persistent Runtime (offline).

What is REAL here and what is a double, because the value of this file is that distinction:

  REAL   c1_execution_contract, c1_dispatch_outbox, c1_result_pull, c1_execution_loop,
         c1_c13c14_review, and - most importantly - the Lite validators: every sealed
         bundle used in these assertions is built and sealed by `lite_fixtures`, and every
         verdict is read back through `lite_bundle.validate/verify_root`. If the transport
         re-implemented any review rule, these tests would still pass while the real system
         drifted; keeping the real validators in the loop is what makes them mean something.
  DOUBLE the Runtime (fencing-faithful `RuntimeDouble`, imported from the loop's own test
         module) and the GitHub transport (`ReviewTransport`, which speaks the same five
         calls the real client does, including the 204-no-run-id shape).

  NOT PROVEN HERE
         that GitHub runs the two workflows, that the dispatch reaches them, or what the
         reviewers decide. Those need the credential on the Runtime Host and the first real
         round - deliberately not part of this candidate.
"""
import hashlib
import json
import os
import re
import sys
import tempfile
import unittest

import yaml
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
for extra in (HERE, ROOT / "control-plane" / "c13-c14-lite"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import c1_c13c14_review as review  # noqa: E402
import c1_dispatch_outbox as outbox_mod  # noqa: E402
import c1_execution_contract as contract  # noqa: E402
import c1_execution_loop as loop_mod  # noqa: E402
import lite_chain  # noqa: E402
import lite_fixtures  # noqa: E402
from test_c1_execution_loop import Clock, RuntimeDouble  # noqa: E402

CANDIDATE = lite_fixtures.CANDIDATE_SHA
TREE = lite_fixtures.APPLICATION_TREE
C14_TASK = lite_fixtures.C14_TASK
C13_TASK = lite_fixtures.C13_TASK
ISSUE = lite_fixtures.ISSUE_NUMBER
REQUEST_ID = lite_fixtures.REQUEST_ID
ROUND = "U7B-PR394-01"
LITE_DIR = ROOT / "control-plane" / "c13-c14-lite"
# The review adapter resolves the Lite package from a CONFIGURED directory and refuses a
# module that came from anywhere else - so the suite has to point at one explicitly.
# (Without the provenance rule these tests passed only because this module had already
# imported , which is precisely the hole readiness exists to close.)
os.environ.setdefault("C13C14_LITE_SOURCE_DIR", str(LITE_DIR))

C14 = contract.C14_REVIEW_KIND
C13 = contract.C13_REVIEW_KIND


# --------------------------------------------------------------------------- helpers
def c14_payload(**over):
    base = dict(cell_id="C14", external_task_id=C14_TASK, candidate_sha=CANDIDATE,
                application_tree=TREE, issue_number=ISSUE, review_request_id=REQUEST_ID,
                ledger_round_id=ROUND, c14_task_id=C14_TASK, c13_task_id=C13_TASK)
    base.update(over)
    return contract.build_review_task_payload(allowed_owner_cs=("C14",), **base)


def c13_payload(**over):
    base = dict(cell_id="C13", external_task_id=C13_TASK, candidate_sha=CANDIDATE,
                application_tree=TREE, issue_number=ISSUE, review_request_id=REQUEST_ID,
                ledger_round_id=ROUND, c14_task_id=C14_TASK, c13_task_id=C13_TASK,
                c14_run_id=900001, c14_runtime_task_id="rt_c14_predecessor")
    base.update(over)
    return contract.build_review_task_payload(allowed_owner_cs=("C13",), **base)


def claimed(task_id, owner_c, kind, payload, attempts=1,
            lease_until=1_700_000_120.0):
    class Claimed:
        pass
    c = Claimed()
    c.task_id, c.owner_c, c.kind, c.payload = task_id, owner_c, kind, payload
    c.attempts, c.lease_until = attempts, lease_until
    return c


def sealed(role, *, verdict="PASS_SCOPED", **kw):
    # A FAIL is only sealable with evidence - the Lite rule, not this module's, which is
    # the point: the fixtures build the record through the real seal, so a bundle that
    # reaches the transport here is one the real validators accepted.
    if verdict == "NOT_APPLICABLE" and role == "c14" and "c14_not_applicable" not in kw:
        kw["c14_not_applicable"] = {
            "review_scope": "the fixture candidate touches no governed surface",
            "basis": "fixture", "applicable_rule_set": "none",
            "applicable_rule_version": "n/a",
            "why_not_applicable": "no authoritative rule source applies to this diff"}
    if verdict == "FAIL" and role == "c14" and "c14_findings" not in kw:
        kw["c14_findings"] = [{"id": "F-1", "severity": "MAJOR",
                               "statement": "the fixture candidate breaks a rule"}]
    round_ = lite_fixtures.make_round(
        c14_verdict=verdict if role == "c14" else "PASS_SCOPED",
        c13_verdict=verdict if role == "c13" else "PASS_SCOPED", **kw)
    return round_["%s_bundle" % role]


def bundle_bytes(record) -> bytes:
    return json.dumps(record, sort_keys=True).encode("utf-8")


class ReviewTransport:
    """Offline stand-in for GitHubActionsClient: same five calls, no network."""

    def __init__(self, *, bundles, round_decision=None, run_id=770001,
                 declare_run_id=True, ambiguous=False, run_conclusion="success",
                 run_status="completed"):
        self.bundles = bundles                       # {artifact_name: {member: bytes}}
        self.round_decision = round_decision
        self.run_id = run_id
        self.next_run_id = run_id
        self.declare_run_id = declare_run_id
        self.ambiguous = ambiguous
        self.run_conclusion = run_conclusion
        self.run_status = run_status
        self.runs = {}
        self.dispatched_targets = []
        self.lookups = []
        self.member_fetches = []

    def send(self, request):
        self.dispatched_targets.append(request["workflow_file"])
        if self.ambiguous:
            return ("ambiguous", "timeout")
        run_id = self.next_run_id
        self.next_run_id += 1
        self.runs[run_id] = {
            "id": run_id, "run_attempt": 1, "status": self.run_status,
            "conclusion": self.run_conclusion,
            "head_sha": contract.REF,
            "name": contract.run_identity_name(request["runtime_task_id"],
                                               request["attempt"],
                                               request["execution_request_id"],
                                               request.get("owner_c", "C1")),
        }
        return ("sent", run_id if self.declare_run_id else None)

    def find_run(self, run_name):
        self.lookups.append(run_name)
        for run_id, run in self.runs.items():
            if run["name"] == run_name:
                return run_id
        return None

    find_run_by_name = find_run

    def get_run(self, run_id):
        found = self.runs.get(run_id)
        return None if found is None else dict(found)

    def download_artifact(self, run_id, name):
        # The single-file path belongs to the C1/C12 classes. A review result is a
        # multi-file bundle and must go through `download_artifact_members`, so this is
        # a bug if it is ever reached here, and says so.
        raise AssertionError("a review artifact is fetched by members, not as c1_result.json")

    def download_artifact_members(self, run_id, name, members):
        self.member_fetches.append((run_id, name, tuple(members)))
        bundle = self.bundles.get(name)
        if bundle is None:
            return None
        found = {}
        for member in members:
            if member not in bundle:
                raise contract.Refused("ARTIFACT_MEMBER_MISSING:" + member)
            found[member] = bundle[member]
        return {"members": found,
                "digests": {k: "sha256:" + hashlib.sha256(v).hexdigest()
                            for k, v in found.items()},
                "github_run_id": run_id}


def open_outbox(path):
    return outbox_mod.DispatchOutbox(path)


def runtime_task(runtime, owner_c, kind, payload, task_id):
    runtime.tasks[task_id] = type("T", (), {})()
    t = runtime.tasks[task_id]
    t.task_id, t.owner_c, t.kind, t.payload = task_id, owner_c, kind, payload
    t.status, t.attempts, t.max_attempts = "QUEUED", 0, 1
    t.lease_owner, t.lease_until, t.idempotency_key = None, None, None
    return t


def drive(rt, outbox, transport, owner_c, kind, payload, task_id, *, hooks=True, attempts=1,
          **extra):
    """Claim-and-advance one task through the real loop, with the review hooks."""
    if task_id not in rt.tasks:
        runtime_task(rt, owner_c, kind, payload, task_id)
    rt.tasks[task_id].status = "RUNNING"
    rt.tasks[task_id].attempts = attempts
    rt.tasks[task_id].lease_owner = "w"
    rt.tasks[task_id].lease_until = 1_700_000_120.0
    kwargs = dict(review_hooks(outbox)) if hooks else {}
    kwargs.update(extra)
    return loop_mod.advance(outbox, rt, claimed(task_id, owner_c, kind, payload, attempts),
                            worker_id="w", client=transport,
                            claimable_kinds=(kind,), **kwargs)


def review_hooks(outbox):
    return {"result_validator": review.make_result_validator(outbox),
            "artifact_loader": review.review_artifact_loader(outbox),
            "on_result_sealed": review.enqueue_c13_when_c14_admits}


# ------------------------------------------------------------------- A: the boundary
class A_TheContractDeclaresTheReviewBoundary(unittest.TestCase):
    def test_review_kinds_are_owned_by_their_own_cell_only(self):
        self.assertEqual(contract.allowed_owner_cs_for_kind(C14), ("C14",))
        self.assertEqual(contract.allowed_owner_cs_for_kind(C13), ("C13",))
        self.assertEqual(contract.BUILDER_OWNER_CS,
                         tuple("C%d" % n for n in range(1, 13)))
        for cell in contract.BUILDER_OWNER_CS:
            self.assertNotIn(cell, contract.allowed_owner_cs_for_kind(C14))
            self.assertNotIn(cell, contract.allowed_owner_cs_for_kind(C13))

    def test_each_review_kind_dispatches_to_its_own_existing_workflow(self):
        self.assertEqual(contract.workflow_file_for_kind(C14), "c14-rule-compliance.yml")
        self.assertEqual(contract.workflow_file_for_kind(C13), "c13-quality-acceptance.yml")
        self.assertEqual(contract.provider_for_kind(C14), contract.PROVIDER_GHAW_BUILDER)

    def test_run_names_start_with_the_cell(self):
        self.assertTrue(contract.run_identity_name("rt_x", 1, "r" * 64,
                                                   "C14").startswith("C14 "))
        self.assertTrue(contract.run_identity_name("rt_x", 1, "r" * 64,
                                                   "C13").startswith("C13 "))

    def test_a_c14_payload_cannot_be_enqueued_for_c13_and_the_reverse(self):
        with self.assertRaises(contract.Refused) as caught:
            c14_payload(cell_id="C13", external_task_id=C13_TASK)
        self.assertEqual(caught.exception.reason,
                         "REVIEW_PAYLOAD_CELL_NOT_OWNED_BY_THIS_EXECUTOR")
        with self.assertRaises(contract.Refused) as caught:
            c13_payload(cell_id="C14")
        self.assertEqual(caught.exception.reason,
                         "REVIEW_PAYLOAD_CELL_NOT_OWNED_BY_THIS_EXECUTOR")

    def test_the_transport_identity_is_not_part_of_the_review_payload(self):
        raw = dict(c14_payload())
        for field, value in (("runtime_task_id", "rt_x"), ("attempt", 1),
                             ("execution_request_id", "a" * 64), ("owner_c", "C14"),
                             ("review_verdict", "PASS_SCOPED"), ("accepted", True),
                             ("status", "SUCCEEDED")):
            with self.assertRaises(contract.Refused) as caught:
                contract.validate_review_task_payload(dict(raw, **{field: value}),
                                                      allowed_owner_cs=("C14",))
            self.assertTrue(caught.exception.reason.startswith("REVIEW_PAYLOAD_"),
                            (field, caught.exception.reason))

    def test_the_two_cells_get_two_runtime_tasks(self):
        a = contract.task_idempotency_key(C14, "C14", C14_TASK)
        b = contract.task_idempotency_key(C13, "C13", C13_TASK)
        self.assertNotEqual(a, b)
        self.assertEqual(a, "c1-c13c14-review-v1:C14:" + C14_TASK)

    def test_the_c13_half_requires_the_c14_execution_it_follows(self):
        with self.assertRaises(contract.Refused) as caught:
            c13_payload(c14_run_id=None)
        self.assertIn("c14_run_id", caught.exception.reason)


# --------------------------------------------------------------- B: the envelope
class B_TheEnvelopeCannotClaimMoreThanItKnows(unittest.TestCase):
    def envelope(self, **over):
        base = {"version": 1, "kind": contract.REVIEW_RESULT_KIND, "owner_c": "C14",
                "runtime_task_id": "rt_a", "attempt": 1, "execution_request_id": "e" * 64,
                "github_run_id": 770001, "github_run_attempt": 1,
                "provider": contract.PROVIDER_GHAW_BUILDER,
                "review_verdict": "PASS_SCOPED", "deployment_eligible": False,
                "accepted": True, "authorizes_any_action": False,
                "candidate_sha": CANDIDATE, "application_tree": TREE,
                "issue_number": ISSUE, "review_request_id": REQUEST_ID,
                "ledger_round_id": ROUND, "sealed_bundle_root": "a" * 64,
                "sealed_bundle_sha256": "b" * 64,
                "artifacts": {"c14_bundle.json": "c" * 64}, "status": "SUCCEEDED",
                "round_decision": None}
        base.update(over)
        return base

    def validate(self, **over):
        return contract.validate_review_result(
            self.envelope(**over), runtime_task_id="rt_a", attempt=1,
            execution_request_id_="e" * 64, task_kind=C14)

    def test_a_well_formed_envelope_passes(self):
        self.validate()

    def test_an_envelope_may_never_authorise_anything(self):
        with self.assertRaises(contract.Refused) as caught:
            self.validate(authorizes_any_action=True)
        self.assertEqual(caught.exception.reason,
                         "REVIEW_RESULT_MUST_NOT_AUTHORIZE_ANY_ACTION")

    def test_an_envelope_may_never_pre_claim_deployment_eligibility(self):
        with self.assertRaises(contract.Refused) as caught:
            self.validate(deployment_eligible=True)
        self.assertEqual(caught.exception.reason,
                         "REVIEW_RESULT_MUST_NOT_CLAIM_DEPLOYMENT_ELIGIBILITY")

    def test_the_owner_cell_must_be_the_kinds_cell(self):
        with self.assertRaises(contract.Refused) as caught:
            self.validate(owner_c="C13")
        self.assertEqual(caught.exception.reason, "REVIEW_RESULT_OWNER_CELL_MISMATCH")

    def test_a_verdict_the_cell_cannot_produce_is_refused(self):
        with self.assertRaises(contract.Refused) as caught:
            contract.validate_review_result(
                self.envelope(owner_c="C13", review_verdict="NOT_APPLICABLE",
                              artifacts={"c13_bundle.json": "c" * 64}),
                runtime_task_id="rt_a", attempt=1, execution_request_id_="e" * 64,
                task_kind=C13)
        self.assertEqual(caught.exception.reason,
                         "REVIEW_RESULT_VERDICT_UNKNOWN_FOR_THIS_CELL")

    def test_delivery_success_is_not_a_verdict(self):
        # A negative verdict is a perfectly good delivery: the execution succeeded and the
        # review concluded FAIL. `complete(success=...)` reads `accepted`, not the verdict.
        document = self.envelope(review_verdict="FAIL")
        contract.validate_review_result(document, runtime_task_id="rt_a", attempt=1,
                                        execution_request_id_="e" * 64, task_kind=C14)
        self.assertTrue(document["accepted"])
        self.assertEqual(document["status"], "SUCCEEDED")


# ------------------------------------------------- C: exactly-once on both legs
class C_ExactlyOnceOnBothReviewLegs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="u7b-")
        self.clock = Clock()
        self.rt = RuntimeDouble(self.clock)
        self.outbox = outbox_mod.DispatchOutbox(str(Path(self.tmp) / "outbox.db"))

    def transport(self, **kw):
        payload = c14_payload()
        name = contract.review_artifact_name(C14, payload["candidate_sha"])
        bundles = {name: {"c14_bundle.json": bundle_bytes(sealed("c14"))}}
        return ReviewTransport(bundles=bundles, **kw)

    def test_an_ambiguous_dispatch_is_resolved_by_lookup_never_by_a_second_post(self):
        transport = self.transport(declare_run_id=False)
        outcome = drive(self.rt, self.outbox, transport, "C14", C14, c14_payload(), "rt_c14")
        self.assertEqual(transport.dispatched_targets, ["c14-rule-compliance.yml"])
        self.assertEqual(outcome["state"], "DISPATCHED")
        snapshot = self.outbox.snapshot(self.outbox.unfinished()[0]["execution_request_id"])
        self.assertEqual(snapshot["dispatches_sent"], 1)
        self.assertEqual(snapshot["state"], outbox_mod.DISPATCH_AMBIGUOUS)

        outcome = drive(self.rt, self.outbox, transport, "C14", C14, c14_payload(), "rt_c14")
        self.assertEqual(transport.dispatched_targets, ["c14-rule-compliance.yml"])
        self.assertTrue(transport.lookups[-1].startswith("C14 "))
        self.assertEqual(transport.lookups[-1],
                         contract.run_identity_name("rt_c14", 1,
                                                    contract.build_dispatch_request(
                                                        "rt_c14", 1, contract.task_spec(
                                                            C14, c14_payload()))["execution_request_id"],
                                                    "C14"))
        self.assertEqual(outcome["action"], "COMPLETED")

    def test_a_c13_leg_looks_up_its_own_name_and_never_the_c14_one(self):
        # The run stays `in_progress`, so this test is about the dispatch and the lookup
        # and not about the result leg (which has its own tests below).
        transport = self.transport(declare_run_id=False)
        transport.run_status = "in_progress"
        payload = c13_payload()
        drive(self.rt, self.outbox, transport, "C13", C13, payload, "rt_c13", hooks=False)
        self.assertEqual(transport.dispatched_targets, ["c13-quality-acceptance.yml"])
        self.assertEqual(transport.lookups, [],
                         "nothing is looked up before an ambiguous tick reports back")
        request_id = self.outbox.unfinished()[0]["execution_request_id"]

        drive(self.rt, self.outbox, transport, "C13", C13, payload, "rt_c13", hooks=False)
        self.assertEqual(transport.dispatched_targets, ["c13-quality-acceptance.yml"],
                         "an ambiguous POST is NEVER repeated")
        self.assertEqual(len(transport.lookups), 1)
        self.assertTrue(transport.lookups[0].startswith("C13 "))
        expected = contract.run_identity_name(
            "rt_c13", 1,
            contract.build_dispatch_request("rt_c13", 1,
                                            contract.task_spec(C13, payload))["execution_request_id"],
            "C13")
        self.assertEqual(transport.lookups[0], expected)
        self.assertEqual(self.outbox.snapshot(request_id)["dispatches_sent"], 1)

    def test_a_second_post_for_one_identity_is_refused_outright(self):
        request = contract.build_dispatch_request("rt_c14", 1,
                                                  contract.task_spec(C14, c14_payload()))
        row = self.outbox.register("rt_c14", 1, request=request)
        self.outbox.record_dispatch_sent(row["request"]["execution_request_id"])
        with self.assertRaises(contract.Refused) as caught:
            self.outbox.record_dispatch_sent(row["request"]["execution_request_id"])
        self.assertEqual(caught.exception.reason, "SECOND_DISPATCH_FORBIDDEN")

    def test_the_transport_identity_travels_as_one_envelope_within_the_platform_limit(self):
        """GitHub allows ten dispatch inputs; the C13 workflow already needs all ten, so the
        Runtime's identity travels as ONE JSON envelope - and c14_run_id rides in it."""
        import yaml
        root = Path(__file__).resolve().parents[2]
        for name, cell in (("c14-rule-compliance.yml", "C14"),
                           ("c13-quality-acceptance.yml", "C13")):
            workflow = yaml.safe_load((root / ".github" / "workflows" / name).read_text(
                encoding="utf-8"))
            inputs = (workflow.get("on") or workflow.get(True))["workflow_dispatch"]["inputs"]
            self.assertLessEqual(len(inputs), 10, name)
            self.assertIn("runtime_transport", inputs)
        request = contract.build_dispatch_request("rt_9", 1, contract.task_spec(C14, c14_payload()))
        sent = contract.dispatch_inputs(request)
        transport = json.loads(sent["runtime_transport"])
        self.assertEqual(transport["owner_c"], "C14")
        self.assertEqual(transport["runtime_task_id"], "rt_9")
        self.assertNotIn("c14_run_id", transport)
        c13_request = contract.build_dispatch_request("rt_8", 1,
                                                      contract.task_spec(C13, c13_payload()))
        self.assertEqual(json.loads(contract.dispatch_inputs(c13_request)["runtime_transport"])
                         ["c14_run_id"], 900001)

    def test_the_two_legs_share_one_outbox_and_one_worker(self):
        import c1_c13c14_review_worker as worker
        self.assertEqual(worker.CLAIM_KINDS, (C14, C13))
        self.assertEqual(worker.CLAIM_OWNER_CS, ("C14", "C13"))
        self.assertEqual(worker.OUTBOX_DB, "/var/lib/go-runtime-c1/outbox-c13c14-review.db")
        self.assertEqual(worker.WORKFLOW_FILES,
                         ("c14-rule-compliance.yml", "c13-quality-acceptance.yml"))


# ------------------------------------------------- D: C14 first, and only then C13
class D_C14AdmitsC13AndOnlyThen(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="u7b-")
        self.clock = Clock()
        self.rt = RuntimeDouble(self.clock)
        self.outbox = outbox_mod.DispatchOutbox(str(Path(self.tmp) / "outbox.db"))

    def run_c14(self, verdict):
        payload = c14_payload()
        name = contract.review_artifact_name(C14, payload["candidate_sha"])
        transport = ReviewTransport(bundles={
            name: {"c14_bundle.json": bundle_bytes(sealed("c14", verdict=verdict))}},
            run_id=770001)
        outcome = drive(self.rt, self.outbox, transport, "C14", C14, payload, "rt_c14")
        return outcome, transport

    def c13_tasks(self):
        return [t for t in self.rt.tasks.values() if t.kind == C13]

    def test_an_admissible_c14_creates_exactly_one_c13_task(self):
        outcome, _ = self.run_c14("PASS_SCOPED")
        self.assertEqual(outcome["action"], "COMPLETED")
        created = self.c13_tasks()
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].owner_c, "C13")
        self.assertEqual(created[0].payload["c14_run_id"], 770001)
        self.assertEqual(created[0].payload["c14_runtime_task_id"], "rt_c14")
        self.assertEqual(created[0].payload["external_task_id"], C13_TASK)

    def test_a_not_applicable_c14_also_admits_c13(self):
        self.run_c14("NOT_APPLICABLE")
        self.assertEqual(len(self.c13_tasks()), 1)

    def test_a_failing_c14_is_a_result_not_a_transport_failure(self):
        outcome, _ = self.run_c14("FAIL")
        self.assertEqual(outcome["action"], "COMPLETED",
                         "a negative verdict is still a delivered review")
        self.assertTrue(outcome["accepted"], "accepted means DELIVERED, not PASSED")
        self.assertEqual(self.c13_tasks(), [], "a FAILed C14 must create no C13 task")
        request_id = contract.build_dispatch_request(
            "rt_c14", 1, contract.task_spec(C14, c14_payload()))["execution_request_id"]
        self.assertEqual(self.outbox.snapshot(request_id)["state"], outbox_mod.COMPLETED)
        self.assertEqual(self.rt.tasks["rt_c14"].status, "SUCCEEDED")

    def test_a_crash_between_the_enqueue_and_the_completion_is_repaired_not_repeated(self):
        payload = c14_payload()
        name = contract.review_artifact_name(C14, payload["candidate_sha"])
        transport = ReviewTransport(bundles={
            name: {"c14_bundle.json": bundle_bytes(sealed("c14"))}}, run_id=770001)

        class Boom(Exception):
            pass

        def crashing_hook(document, binding, outbox, runtime, *, client=None):
            # enqueue, then die before Runtime.complete(C14) - the exact window the ordering
            # in `complete_after_pull` exists for.
            review.enqueue_c13_when_c14_admits(document, binding, outbox, runtime)
            raise Boom("crash after the C13 enqueue, before the C14 completion")

        with self.assertRaises(Boom):
            drive(self.rt, self.outbox, transport, "C14", C14, payload, "rt_c14",
                  hooks=False, on_result_sealed=crashing_hook,
                  artifact_loader=review.review_artifact_loader(self.outbox),
                  result_validator=review.make_result_validator(self.outbox))

        created = self.c13_tasks()
        self.assertEqual(len(created), 1)
        self.assertEqual(self.rt.tasks["rt_c14"].status, "RUNNING",
                         "the C14 task must still be completable")
        c14_request_id = contract.build_dispatch_request(
            "rt_c14", 1, contract.task_spec(C14, payload))["execution_request_id"]
        self.assertEqual(self.outbox.snapshot(c14_request_id)["state"],
                         outbox_mod.RESULT_SEALED,
                         "the result is sealed and the completion has not happened")
        first_c13 = created[0].task_id

        # Restart: the row is still RESULT_SEALED, so the same hook runs again and the
        # Runtime's own idempotency hands back the SAME C13 task.
        outcome = drive(self.rt, self.outbox, transport, "C14", C14, payload, "rt_c14")
        self.assertEqual(outcome["action"], "COMPLETED")
        self.assertEqual([t.task_id for t in self.c13_tasks()], [first_c13])


# ------------------------------------------------ E: transport failure vs verdict
class E_TransportFailureIsNeverAVerdict(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="u7b-")
        self.clock = Clock()
        self.rt = RuntimeDouble(self.clock)
        self.outbox = outbox_mod.DispatchOutbox(str(Path(self.tmp) / "outbox.db"))

    def test_a_failed_run_fails_the_execution_and_creates_no_c13(self):
        payload = c14_payload()
        name = contract.review_artifact_name(C14, payload["candidate_sha"])
        transport = ReviewTransport(bundles={
            name: {"c14_bundle.json": bundle_bytes(sealed("c14"))}},
            run_conclusion="failure", run_id=770009)
        outcome = drive(self.rt, self.outbox, transport, "C14", C14, payload, "rt_c14")
        self.assertEqual(outcome["action"], outbox_mod.RUN_FAILED)
        self.assertFalse(self.rt.tasks["rt_c14"].status == "SUCCEEDED")
        self.assertEqual([t for t in self.rt.tasks.values() if t.kind == C13], [])
        self.assertEqual(self.outbox.snapshot(
            contract.build_dispatch_request(
                "rt_c14", 1, contract.task_spec(C14, payload))["execution_request_id"]
        )["state"], outbox_mod.RUN_FAILED)

    def test_a_tampered_bundle_is_a_refusal_not_a_verdict(self):
        payload = c14_payload()
        name = contract.review_artifact_name(C14, payload["candidate_sha"])
        tampered = dict(sealed("c14"))
        tampered["verdict"] = "PASS_SCOPED"
        tampered["blocking_issues"] = ["someone edited this after sealing"]
        transport = ReviewTransport(bundles={
            name: {"c14_bundle.json": bundle_bytes(tampered)}}, run_id=770010)
        with self.assertRaises(contract.Refused) as caught:
            drive(self.rt, self.outbox, transport, "C14", C14, payload, "rt_c14")
        self.assertTrue(caught.exception.reason.startswith(
            "REVIEW_BUNDLE_REJECTED") or "ROOT" in caught.exception.reason,
            caught.exception.reason)
        self.assertEqual([t for t in self.rt.tasks.values() if t.kind == C13], [])


# ------------------------------------------------------- F: owner/kind isolation
class F_OwnerAndKindIsolation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="u7b-")
        self.clock = Clock()
        self.rt = RuntimeDouble(self.clock)
        self.outbox = outbox_mod.DispatchOutbox(str(Path(self.tmp) / "outbox.db"))
        self.transport = ReviewTransport(bundles={})

    def advance(self, owner_c, kind, payload, claimable):
        return loop_mod.advance(self.outbox, self.rt,
                                claimed("rt_x", owner_c, kind, payload),
                                worker_id="w", client=self.transport,
                                claimable_kinds=claimable)

    def test_a_review_kind_on_a_normal_cell_is_refused(self):
        for cell in ("C1", "C7", "C12"):
            outcome = self.advance(cell, C14, c14_payload(), (C14, C13))
            self.assertEqual(outcome["action"], "NOT_A_C1_TASK")
            self.assertEqual(outcome["reason"], "OWNER_C_MISMATCH")

    def test_the_builder_kind_on_a_control_cell_is_refused(self):
        payload = contract.build_task_payload(cell_id="C14", external_task_id="T-1",
                                              objective="o", scope="s",
                                              allowed_owner_cs=("C14",))
        for cell in ("C13", "C14"):
            outcome = self.advance(cell, contract.GHAW_BUILDER_KIND, payload,
                                   (contract.GHAW_BUILDER_KIND,))
            self.assertEqual(outcome["action"], "NOT_A_C1_TASK")

    def test_the_two_review_kinds_are_never_interchangeable(self):
        outcome = self.advance("C13", C14, c14_payload(), (C13,))
        self.assertEqual(outcome["reason"], "KIND_MISMATCH")
        outcome = self.advance("C14", C13, c13_payload(), (C14,))
        self.assertEqual(outcome["reason"], "KIND_MISMATCH")

    def test_the_review_executor_does_not_claim_the_builder_or_responses_kinds(self):
        import c1_c13c14_review_worker as worker
        for kind in (contract.GHAW_BUILDER_KIND, contract.REAL_TASK_KIND,
                     contract.KIND, "RUNTIME_PROBE", "AI_GHAW_HELLO_V1"):
            self.assertNotIn(kind, worker.CLAIM_KINDS)

    def test_no_other_executor_claims_a_review_kind(self):
        import c1_ghaw_builder_worker as builder
        import c1_worker as legacy
        for kind in (C14, C13):
            self.assertNotIn(kind, builder.CLAIM_KINDS)
            self.assertNotIn(kind, legacy.CLAIM_KINDS)


if __name__ == "__main__":
    unittest.main(verbosity=1)


# =============================================================== G: the workflows
class G_ProductionWorkflowsAreStructurallySound(unittest.TestCase):
    """The two production workflows, checked as DATA rather than as parseable YAML.

    "The YAML parser could read it" is not a gate. A workflow that references an input it
    never declares, that declares an input it no longer uses, or that contains a step with
    neither `run:` nor `uses:`, is broken in a way only GitHub would have found - at
    dispatch time, on the live path, with a real run. So each of those is asserted here.
    """

    NAMES = ("c14-rule-compliance.yml", "c13-quality-acceptance.yml")
    # Inputs this round REMOVED. Referencing one is a live blocker: the dispatch that used
    # to supply it no longer does, so the workflow would fail against itself.
    STALE = ("owner_c", "runtime_task_id", "attempt", "execution_request_id", "c14_run_id")

    def documents(self):
        root = Path(__file__).resolve().parents[2]
        for name in self.NAMES:
            raw = (root / ".github" / "workflows" / name).read_text(encoding="utf-8")
            document = yaml.safe_load(raw)
            inputs = (document.get("on") or document.get(True))["workflow_dispatch"]["inputs"]
            yield name, raw, document, inputs

    def test_every_referenced_input_is_declared(self):
        for name, raw, _document, inputs in self.documents():
            referenced = set(re.findall(r"inputs\.([A-Za-z0-9_]+)", raw))
            undeclared = sorted(referenced - set(inputs))
            self.assertEqual(undeclared, [],
                             "%s references undeclared dispatch inputs: %s" % (name, undeclared))

    def test_runtime_transport_is_declared_exactly_once(self):
        for name, raw, _document, inputs in self.documents():
            self.assertIn("runtime_transport", inputs, name)
            self.assertEqual(raw.count("      runtime_transport:"), 1, name)

    def test_no_removed_input_survives_anywhere(self):
        for name, raw, _document, inputs in self.documents():
            for stale in self.STALE:
                self.assertNotIn(stale, inputs, "%s still declares %s" % (name, stale))
                self.assertNotIn("inputs.%s" % stale, raw,
                                 "%s still references inputs.%s" % (name, stale))

    def test_exactly_one_transport_preflight_per_job_that_has_one(self):
        for name, _raw, document, _inputs in self.documents():
            for job, body in document["jobs"].items():
                steps = body.get("steps") or []
                asserters = [s for s in steps
                             if s.get("name") == (
                                 "Assert the Runtime transport identity belongs to this cell")]
                self.assertLessEqual(len(asserters), 1, "%s/%s" % (name, job))
                for step in asserters:
                    self.assertIn("run", step)
                    self.assertIn("inputs.runtime_transport".replace("inputs.", "${{ inputs.") +
                                  " }}", step["env"]["RUNTIME_TRANSPORT"])

    def test_no_step_is_neither_run_nor_uses(self):
        for name, _raw, document, _inputs in self.documents():
            for job, body in document["jobs"].items():
                for index, step in enumerate(body.get("steps") or []):
                    self.assertTrue("run" in step or "uses" in step,
                                    "%s/%s step %d (%r) has neither run nor uses"
                                    % (name, job, index, step.get("name")))

    def test_the_execution_backend_checkout_is_a_real_checkout(self):
        for name, _raw, document, _inputs in self.documents():
            steps = document["jobs"][next(iter(document["jobs"]))]["steps"]
            checkouts = [s for s in steps
                         if str(s.get("name") or "").startswith(
                             "Check out the execution backend")]
            self.assertEqual(len(checkouts), 1, name)
            self.assertEqual(checkouts[0]["uses"], "actions/checkout@v4", name)
            self.assertEqual(checkouts[0]["with"]["ref"], "${{ github.sha }}", name)

    def test_the_transport_preflight_runs_before_the_checkout(self):
        for name, _raw, document, _inputs in self.documents():
            steps = document["jobs"][next(iter(document["jobs"]))]["steps"]
            self.assertEqual(steps[0]["name"],
                             "Assert the Runtime transport identity belongs to this cell")
            self.assertEqual(steps[1]["uses"], "actions/checkout@v4")

    def test_dispatch_input_count_is_within_the_platform_limit(self):
        for name, _raw, _document, inputs in self.documents():
            self.assertLessEqual(len(inputs), 10, name)
            self.assertEqual(len(inputs), len(set(inputs)), name)

    def test_every_wire_input_is_declared_by_the_workflow_it_is_sent_to(self):
        """A dispatch may only carry inputs the receiving workflow DECLARES.

        GitHub does not ignore an undeclared `workflow_dispatch` input; it refuses the
        dispatch. So a wire set that is not a subset of the receiving workflow's declared
        inputs is not untidiness - it is a dispatch that never happens, and the failure
        surfaces as an opaque refusal in the worker's tick rather than as a workflow error.

        This is the defect the FIRST live C14 round hit: `machine_inventory` (the C13
        machine-test inventory) was being put on the C14 dispatch, and the C14 workflow
        declares nine inputs and that is not one of them. The contract's own table is held
        against the workflow files here, so the two cannot drift again.
        """
        declared = {name: set(inputs) for name, _raw, _document, inputs in self.documents()}
        inventory = "application/tests/workbench/test_go_parallel_workbench_build01.py"
        c14_request = contract.build_dispatch_request(
            "rt_1", 1, contract.task_spec(C14, c14_payload(machine_inventory=inventory,
                                                           ai_model="m")))
        c13_request = contract.build_dispatch_request(
            "rt_2", 1, contract.task_spec(C13, c13_payload(machine_inventory=inventory,
                                                           ai_model="m")))
        wires = {
            "c14-rule-compliance.yml": contract.dispatch_inputs(c14_request),
            "c13-quality-acceptance.yml": contract.dispatch_inputs(c13_request),
        }
        for name, wire in wires.items():
            self.assertEqual(sorted(set(wire) - declared[name]), [],
                             "%s would be sent undeclared inputs" % name)
        # The two Cells do NOT share one optional set: the C13 workflow declares the
        # machine inventory and the C14 workflow does not, and the wire follows the
        # workflow rather than the payload.
        self.assertNotIn("machine_inventory", declared["c14-rule-compliance.yml"])
        self.assertIn("machine_inventory", declared["c13-quality-acceptance.yml"])
        self.assertNotIn("machine_inventory", wires["c14-rule-compliance.yml"])
        self.assertEqual(wires["c13-quality-acceptance.yml"]["machine_inventory"], inventory)
        # ...while an optional input BOTH workflows declare still travels to both.
        self.assertEqual(wires["c14-rule-compliance.yml"]["ai_model"], "m")
        self.assertEqual(wires["c13-quality-acceptance.yml"]["ai_model"], "m")


# ============================================ H: the C13 verdict, through the REAL chain
class H_ANegativeC13VerdictIsADeliveredReview(unittest.TestCase):
    """Every case below builds its round decision by RUNNING the Lite chain.

    The point of using `lite_chain.verify_round` and `Decision.as_dict()` instead of a
    hand-written `{"decision": "ACCEPT"}` fixture is that the mapping asserted here - which
    verdict yields which decision - is the Lite chain's, not this module's. If the transport
    ever grew its own rule set, these tests would still pass while the system drifted.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="u7b-real-")
        self.clock = Clock()
        self.rt = RuntimeDouble(self.clock)
        self.outbox = outbox_mod.DispatchOutbox(str(Path(self.tmp) / "outbox.db"))

    # ---------------------------------------------------------------- the C14 half
    def run_c14(self, round_, run_id=770001):
        payload = c14_payload()
        name = contract.review_artifact_name(C14, payload["candidate_sha"])
        transport = ReviewTransport(
            bundles={name: {"c14_bundle.json": bundle_bytes(round_["c14_bundle"])}},
            run_id=run_id)
        outcome = drive(self.rt, self.outbox, transport, "C14", C14, payload, "rt_c14")
        self.assertEqual(outcome["action"], "COMPLETED")
        return transport

    def run_c13(self, round_, decision, *, payload=None, run_id=770002, corrupt=None):
        members = {"c13_bundle.json": bundle_bytes(round_["c13_bundle"]),
                   "round_decision.json": json.dumps(
                       decision.as_dict() if hasattr(decision, "as_dict") else decision).encode()}
        if corrupt is not None:
            members.update(corrupt)
        name = contract.review_artifact_name(C13, CANDIDATE)
        transport = ReviewTransport(bundles={name: members}, run_id=run_id)
        c14_request = contract.build_dispatch_request(
            "rt_c14", 1, contract.task_spec(C14, c14_payload()))["execution_request_id"]
        c14_row = self.outbox.snapshot(c14_request)
        payload = payload or c13_payload(
            c14_run_id=c14_row["github_run_id"], c14_runtime_task_id="rt_c14")
        return drive_to_result(self.rt, self.outbox, transport, payload, "rt_c13")

    # ------------------------------------------------------------------- the cases
    def test_case_a_c13_pass_scoped_is_an_accepted_round(self):
        round_ = lite_fixtures.make_round(c14_verdict="PASS_SCOPED",
                                          c13_verdict="PASS_SCOPED")
        decision = lite_chain.verify_round(**lite_fixtures.chain_kwargs(round_))
        self.assertEqual(decision.decision, "ACCEPT", "the real Lite chain decides this")
        self.run_c14(round_)
        outcome, result = self.run_c13(round_, decision)
        self.assertEqual(outcome, "COMPLETED")
        self.assertTrue(result["accepted"])
        self.assertEqual(result["review_verdict"], "PASS_SCOPED")
        self.assertFalse(result["deployment_eligible"])
        self.assertEqual(result["round_decision"]["decision"], "ACCEPT")
        # The RUNTIME's own record, not the envelope's shape: the point of the whole round
        # is that a delivered review reaches `Runtime.complete`, and only the task's status
        # proves it did.
        self.assertEqual(self.rt.tasks["rt_c13"].status, "SUCCEEDED")

    def test_case_b_c13_fail_is_a_delivered_review_not_a_transport_failure(self):
        round_ = lite_fixtures.make_round(c14_verdict="PASS_SCOPED", c13_verdict="FAIL")
        decision = lite_chain.verify_round(**lite_fixtures.chain_kwargs(round_))
        self.assertEqual(decision.decision, "BLOCK", "the real Lite chain decides this")
        self.run_c14(round_)
        outcome, result = self.run_c13(round_, decision)
        # THE point: a BLOCK round is not a failed delivery.
        self.assertEqual(outcome, "COMPLETED")
        self.assertTrue(result["accepted"], "accepted == DELIVERED, not PASSED")
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["review_verdict"], "FAIL")
        self.assertFalse(result["deployment_eligible"])
        self.assertEqual(result["round_decision"]["decision"], "BLOCK")
        # A BLOCK round is a DELIVERED review: the Runtime task itself succeeded.
        self.assertEqual(self.rt.tasks["rt_c13"].status, "SUCCEEDED")

    def test_case_c_c13_blocked_is_also_a_delivered_review(self):
        round_ = lite_fixtures.make_round(c14_verdict="PASS_SCOPED", c13_verdict="BLOCKED")
        decision = lite_chain.verify_round(**lite_fixtures.chain_kwargs(round_))
        self.assertEqual(decision.decision, "BLOCK")
        self.run_c14(round_)
        outcome, result = self.run_c13(round_, decision)
        self.assertEqual(outcome, "COMPLETED")
        self.assertTrue(result["accepted"])
        self.assertEqual(result["review_verdict"], "BLOCKED")
        self.assertEqual(self.rt.tasks["rt_c13"].status, "SUCCEEDED")

    def test_case_d_a_rejected_chain_is_a_refusal(self):
        # A REJECT is what the Lite chain produces for evidence it cannot trust. It is the
        # ONE decision that is a chain-integrity failure, and the transport must refuse it.
        round_ = lite_fixtures.make_round(c14_verdict="PASS_SCOPED", c13_verdict="FAIL")
        decision = lite_chain.verify_round(**lite_fixtures.chain_kwargs(round_))
        forged = dict(decision.as_dict())
        forged["decision"] = "REJECT"
        forged["rejects"] = [{"reason": "root_recompute_mismatch", "where": "c13"}]
        self.run_c14(round_)
        with self.assertRaises(contract.Refused) as caught:
            self.run_c13(round_, forged)
        self.assertTrue(caught.exception.reason.startswith("REVIEW_ROUND_DECISION_REJECTED"),
                        caught.exception.reason)
        # A REJECT is never adopted: the Runtime task is NOT completed by it.
        self.assertNotEqual(self.rt.tasks["rt_c13"].status, "SUCCEEDED")

    def test_a_round_decision_that_authorises_anything_is_refused(self):
        round_ = lite_fixtures.make_round(c14_verdict="PASS_SCOPED", c13_verdict="FAIL")
        decision = lite_chain.verify_round(**lite_fixtures.chain_kwargs(round_))
        forged = dict(decision.as_dict())
        forged["authorizes_any_action"] = True
        self.run_c14(round_)
        with self.assertRaises(contract.Refused) as caught:
            self.run_c13(round_, forged)
        self.assertEqual(caught.exception.reason,
                         "REVIEW_ROUND_DECISION_MUST_NOT_AUTHORIZE_ANY_ACTION")

    def test_an_accEPTED_round_over_a_failing_c13_is_refused(self):
        round_ = lite_fixtures.make_round(c14_verdict="PASS_SCOPED", c13_verdict="FAIL")
        self.run_c14(round_)
        with self.assertRaises(contract.Refused) as caught:
            self.run_c13(round_, {"decision": "ACCEPT", "authorizes_any_action": False})
        self.assertEqual(caught.exception.reason,
                         "REVIEW_ROUND_ACCEPTED_WITH_A_NON_PASS_C13:FAIL")


def drive_to_result(rt, outbox, transport, payload, task_id):
    """Drive one C13 execution to its sealed result and return (action, result document)."""
    outcome = drive(rt, outbox, transport, "C13", C13, payload, task_id)
    request = contract.build_dispatch_request(task_id, 1,
                                              contract.task_spec(C13, payload))
    request_id = request["execution_request_id"]
    document = outbox.terminal_result(request_id)
    return outcome.get("action"), document


# ============================================== I: the unit and the code cannot drift
class I_TheUnitMatchesTheCodeItRuns(unittest.TestCase):
    """The shipped systemd unit is the only install definition, so it is asserted against
    the module's own constants rather than described in prose in two places."""

    UNIT = "go-runtime-host-c13c14-review-worker.service"

    def setUp(self):
        import c1_c13c14_review as review_module
        import c1_c13c14_review_worker as worker_module
        self.worker = worker_module
        self.review = review_module
        self.text = (Path(__file__).resolve().parents[2] / "control-plane" /
                     "runtime-host-channel-v1" / "systemd" / self.UNIT).read_text(encoding="utf-8")
        self.settings = {}
        self.environ = []
        for line in self.text.splitlines():
            if line.startswith("Environment="):
                self.environ.append(line.partition("=")[2])
            elif line.startswith(("ExecStart=", "ExecStartPre=", "WorkingDirectory=",
                                  "User=", "Group=")):
                key, _, value = line.partition("=")
                self.settings[key] = value

    def test_exec_start_is_this_worker(self):
        self.assertEqual(
            self.settings["ExecStart"],
            "/usr/bin/python3 -B /opt/go/runtime-host-c13c14-review-worker/"
            "c1_c13c14_review_worker.py")
        self.assertTrue(self.settings["ExecStart"].endswith(
            "c1_c13c14_review_worker.py"))

    def test_exec_start_pre_is_the_readiness_check(self):
        self.assertEqual(self.settings["ExecStartPre"],
                         self.settings["ExecStart"] + " --check")

    def test_working_directory_is_the_install_root(self):
        self.assertEqual(self.settings["WorkingDirectory"],
                         "/opt/go/runtime-host-c13c14-review-worker")

    def test_condition_paths_name_the_worker_the_lite_package_and_the_credential(self):
        for expected in (
                "ConditionPathExists=/opt/go/runtime-host-c13c14-review-worker/"
                "c1_c13c14_review_worker.py",
                "ConditionPathExists=/opt/go/c13c14-lite/lite_bundle.py",
                "ConditionPathExists=/etc/go-runtime-c1/github-token"):
            self.assertIn(expected, self.text)
        self.assertIn("After=go-c1-c14-runtime.service", self.text)

    def test_sandbox_and_identity_reuse_the_builder_worker(self):
        self.assertEqual(self.settings["User"], "go-runtime")
        self.assertEqual(self.settings["Group"], "go-runtime")
        for line in ("NoNewPrivileges=true", "PrivateTmp=true", "ProtectSystem=strict",
                     "ProtectHome=true", "ProtectKernelTunables=true",
                     "ProtectKernelModules=true", "ProtectControlGroups=true",
                     "PrivateDevices=true", "UMask=0077",
                     "WantedBy=multi-user.target"):
            self.assertIn(line, self.text)

    def test_read_only_and_read_write_paths(self):
        read_only = [l for l in self.text.splitlines() if l.startswith("ReadOnlyPaths=")]
        read_write = [l for l in self.text.splitlines() if l.startswith("ReadWritePaths=")]
        self.assertEqual(len(read_only), 1)
        self.assertEqual(len(read_write), 1)
        for path in ("/opt/go/c1-c14-runtime", "/opt/go/c13c14-lite"):
            self.assertIn(path, read_only[0])
        for path in ("/var/lib/go-c-runtime", "/var/lib/go-runtime-c1"):
            self.assertIn(path, read_write[0])

    def test_the_unit_and_the_module_agree_on_identity_and_outbox(self):
        # The worker id and the unit name are the same identity, so the two are tied
        # together by construction rather than by a second copy of the string.
        self.assertEqual(self.worker.WORKER_ID + ".service", self.UNIT)
        self.assertEqual(self.worker.OUTBOX_DB,
                         "/var/lib/go-runtime-c1/outbox-c13c14-review.db")
        self.assertIn(self.worker.OUTBOX_DB, self.text)
        self.assertEqual(self.worker.CLAIM_KINDS, (C14, C13))
        self.assertEqual(self.worker.CLAIM_OWNER_CS, ("C14", "C13"))

    def test_the_credential_path_matches_the_existing_host_credential(self):
        self.assertIn("C1_GITHUB_TOKEN_PATH=/etc/go-runtime-c1/github-token", self.environ)
        # The path the HOST actually configures - i.e. the one the other two units already
        # use - not the module's built-in default, which is the old /etc/go-runtime-host
        # location the channel deliberately moved away from.
        builder = (Path(__file__).resolve().parents[1] / "runtime-host-channel-v1" /
                   "systemd" /
                   "go-runtime-host-ghaw-builder-worker.service").read_text(encoding="utf-8")
        self.assertIn("Environment=C1_GITHUB_TOKEN_PATH=/etc/go-runtime-c1/github-token",
                      builder)
        self.assertIn("ConditionPathExists=/etc/go-runtime-c1/github-token", builder)

    def test_the_lite_directory_matches_the_code_default(self):
        self.assertIn("Environment=C13C14_LITE_SOURCE_DIR=/opt/go/c13c14-lite", self.text)
        self.assertEqual(self.review.DEFAULT_LITE_SOURCE_DIR, "/opt/go/c13c14-lite")

    def test_there_is_still_exactly_one_review_executor_and_one_outbox(self):
        systemd = (Path(__file__).resolve().parents[2] / "control-plane" /
                   "runtime-host-channel-v1" / "systemd")
        units = sorted(item.name for item in systemd.iterdir() if item.suffix == ".service")
        self.assertEqual([u for u in units if "c13c14" in u or "review" in u], [self.UNIT])
        # Exactly two executors exist now: the gh-aw Builder and this review worker. The
        # retired C1 Responses worker's unit was removed from this directory, and a third
        # "worker" unit reappearing here would mean that retirement had been undone.
        self.assertEqual(sorted(u for u in units if "worker" in u),
                         sorted(["go-runtime-host-c13c14-review-worker.service",
                                 "go-runtime-host-ghaw-builder-worker.service"]))
        self.assertNotIn("go-runtime-host-c1-worker.service", units)
        # The unit NAMES the file; the worker DECLARES it - exactly once, because that
        # string is the single definition of which outbox this executor owns.
        self.assertIn("outbox-c13c14-review.db", self.text)
        worker_source = (Path(__file__).resolve().parents[1] / "runtime-host-channel-v1" /
                         "c1_c13c14_review_worker.py").read_text(encoding="utf-8")
        self.assertEqual(worker_source.count("OUTBOX_DB = "), 1,
                         "the outbox path must be DECLARED once")
        self.assertIn("/var/lib/go-runtime-c1/outbox-c13c14-review.db", worker_source)


# ========================================= J: readiness refuses paid work it cannot finish
class J_ReadinessRefusesWorkItCouldNotFinish(unittest.TestCase):
    """`--check` must be a gate, and must have no side effects at all."""

    def test_lite_is_required_before_anything_is_claimed(self):
        from lite_errors import Block  # noqa: F401  (the package must be importable here)
        good = review.review_readiness(source_dir=str(LITE_DIR), runtime_dir=str(LITE_DIR))
        self.assertNotEqual(good.get("reason"), "C13C14_LITE_PACKAGE_INCOMPLETE")
        bad = review.review_readiness(source_dir="/nonexistent", runtime_dir="/nonexistent")
        self.assertEqual(bad["status"], "REFUSED")
        self.assertEqual(bad["reason"], "C13C14_LITE_PACKAGE_INCOMPLETE")

    def test_an_already_imported_lite_module_cannot_satisfy_a_missing_directory(self):
        review.review_readiness(source_dir=str(LITE_DIR), runtime_dir=str(LITE_DIR))
        # `lite_bundle` is in sys.modules by now. A provenance-blind check would accept it
        # for ANY directory, and would therefore pass on a host where the package is absent.
        again = review.review_readiness(source_dir="/somewhere/else", runtime_dir=str(LITE_DIR))
        self.assertEqual(again["reason"], "C13C14_LITE_PACKAGE_INCOMPLETE")

    def test_check_opens_nothing_and_touches_nothing(self):
        import contextlib
        import io

        touched = []

        class Never:
            def __getattr__(self, name):
                def _record(*args, **kwargs):
                    touched.append(name)
                    raise AssertionError("--check must not use %s" % name)
                return _record

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = self.worker.main(["--check"], runtime=Never(), outbox=Never(),
                                    client=Never(), token_loader=lambda: "token",
                                    readiness=lambda: {"runtime_source": "importable:/x",
                                                       "lite_package": "importable:/y",
                                                       "lite_modules": list(
                                                           review.READINESS_LITE_MODULES)})
        self.assertEqual(touched, [], "--check claimed or dispatched something")
        self.assertEqual(code, 0)
        self.assertIn("C14_REVIEW_V1", stdout.getvalue())
        self.assertIn("C13_REVIEW_V1", stdout.getvalue())

    def test_check_exits_non_zero_when_readiness_refuses(self):
        import contextlib
        import io

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = self.worker.main(["--check"], runtime=None, outbox=None, client=None,
                                    token_loader=lambda: "token",
                                    readiness=lambda: {"status": "REFUSED",
                                                       "reason": "C13C14_LITE_PACKAGE_INCOMPLETE",
                                                       "lite_package": "missing:lite_bundle"})
        self.assertEqual(code, 1)
        self.assertIn("C13C14_LITE_PACKAGE_INCOMPLETE", stdout.getvalue())

    @property
    def worker(self):
        import c1_c13c14_review_worker
        return c1_c13c14_review_worker


# ================ K: the lease, confirmed before the only leg that can spend anything
class K_NoPaidDispatchWithoutTheLease(unittest.TestCase):
    """The second live C14 round: a dispatch the Runtime would not accept.

    The first live C14 round sat in a refused dispatch for longer than its lease while the
    defect behind that refusal was diagnosed and fixed. The Runtime recovered the task as
    `MAX_ATTEMPTS_EXHAUSTED` and escalated it - correctly - and the worker then came back,
    found the identity still pending in its OWN outbox, and dispatched it anyway. The run
    was real and succeeded, and the completion was refused because the task was no longer
    RUNNING under this worker: a paid execution whose result could not be recorded.

    What these tests pin is the rule that prevents it. The lease is confirmed at the one
    place that can spend, and an identity that cannot be renewed is not dispatched - the
    transport is not even asked. A fresh claim is unaffected, because `claim()` has just
    granted exactly the lease this checks.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="u7b-lease-")
        self.clock = Clock()
        self.rt = RuntimeDouble(self.clock)
        self.outbox = outbox_mod.DispatchOutbox(str(Path(self.tmp) / "outbox.db"))

    @property
    def worker(self):
        import c1_c13c14_review_worker
        return c1_c13c14_review_worker

    def transport(self, kind, **kw):
        payload = c14_payload() if kind == C14 else c13_payload()
        role = "c14" if kind == C14 else "c13"
        name = contract.review_artifact_name(kind, payload["candidate_sha"])
        return ReviewTransport(
            bundles={name: {"%s_bundle.json" % role: bundle_bytes(sealed(role))}}, **kw)

    def register(self, kind, payload, task_id, *, status, lease_until):
        """A pending identity in the outbox, and a Runtime task in a given fenced state."""
        request = contract.build_dispatch_request(task_id, 1,
                                                  contract.task_spec(kind, payload))
        self.outbox.register(task_id, 1, request=request)
        task = runtime_task(self.rt, contract.REVIEW_OWNER_C[kind], kind, payload, task_id)
        task.status, task.attempts = status, 1
        task.lease_owner, task.lease_until = "w", lease_until
        return request

    def resume(self, kind, task_id, transport):
        return loop_mod.resume(self.outbox, self.rt, task_id, 1, worker_id="w",
                               client=transport, claimable_kinds=(kind,),
                               confirm_lease=True, **review_hooks(self.outbox))

    def test_an_escalated_task_is_never_dispatched(self):
        # The live shape: the Runtime had already recovered and escalated the task.
        transport = self.transport(C14)
        request = self.register(C14, c14_payload(), "rt_c14",
                                status="ESCALATED", lease_until=1_700_000_120.0)
        outcome = self.resume(C14, "rt_c14", transport)
        self.assertEqual(transport.dispatched_targets, [],
                         "a task the Runtime has escalated must never be dispatched")
        self.assertEqual(outcome["action"], outbox_mod.ABANDONED)
        self.assertEqual(outcome["reason"], "LEASE_LOST")
        snapshot = self.outbox.snapshot(request["execution_request_id"])
        self.assertEqual(snapshot["dispatches_sent"], 0)
        self.assertEqual(snapshot["state"], outbox_mod.ABANDONED)

    def test_an_expired_lease_is_never_dispatched_on_either_leg(self):
        # The other unrecoverable shape: still RUNNING, but the lease has run out.
        for kind, payload, task_id in ((C14, c14_payload(), "rt_c14"),
                                       (C13, c13_payload(), "rt_c13")):
            with self.subTest(kind=kind):
                transport = self.transport(kind)
                request = self.register(kind, payload, task_id, status="RUNNING",
                                        lease_until=1_700_000_000.0)
                outcome = self.resume(kind, task_id, transport)
                self.assertEqual(transport.dispatched_targets, [], kind)
                self.assertEqual(outcome["reason"], "LEASE_LOST")
                self.assertEqual(
                    self.outbox.snapshot(request["execution_request_id"])["dispatches_sent"], 0)

    def test_a_resume_that_still_holds_its_lease_dispatches_and_completes(self):
        # The confirmation must not break crash recovery, which is why `resume` exists.
        transport = self.transport(C14)
        request = self.register(C14, c14_payload(), "rt_c14", status="RUNNING",
                                lease_until=1_700_000_120.0)
        outcome = self.resume(C14, "rt_c14", transport)
        self.assertEqual(transport.dispatched_targets, ["c14-rule-compliance.yml"])
        self.assertEqual(outcome["action"], "COMPLETED")
        self.assertEqual(self.rt.tasks["rt_c14"].status, "SUCCEEDED")
        self.assertEqual(
            self.outbox.snapshot(request["execution_request_id"])["dispatches_sent"], 1)

    def test_a_lookup_that_finds_an_already_paid_run_is_never_blocked_by_the_lease(self):
        # A lookup spends nothing, and the run it finds may already hold an answer worth
        # adopting - so it must still happen, even with the lease gone.
        transport = self.transport(C14, declare_run_id=False)
        transport.run_status = "completed"
        request = self.register(C14, c14_payload(), "rt_c14", status="RUNNING",
                                lease_until=1_700_000_120.0)
        self.resume(C14, "rt_c14", transport)                      # ambiguous POST
        self.clock.advance(1000)                                   # the lease dies
        self.resume(C14, "rt_c14", transport)
        self.assertEqual(len(transport.lookups), 1)
        self.assertIsNotNone(self.outbox.terminal_result(request["execution_request_id"]))

    def test_a_fresh_claim_is_unaffected_by_the_confirmation(self):
        # `advance()` was just handed the lease, so the confirmation passes by construction.
        transport = self.transport(C14)
        outcome = drive(self.rt, self.outbox, transport, "C14", C14, c14_payload(), "rt_c14",
                        confirm_lease=True)
        self.assertEqual(transport.dispatched_targets, ["c14-rule-compliance.yml"])
        self.assertEqual(outcome["action"], "COMPLETED")
        self.assertEqual(self.rt.tasks["rt_c14"].status, "SUCCEEDED")

    def test_the_confirmation_is_off_by_default(self):
        # The Builder's settlement tests drive exactly this shape - a tick whose lease has
        # already gone still dispatches - and pin what happens next, so the generic loop's
        # default must stay as it was. Only the review executor opts in.
        transport = self.transport(C14, declare_run_id=False)
        self.register(C14, c14_payload(), "rt_c14", status="RUNNING",
                      lease_until=1_700_000_000.0)
        outcome = loop_mod.resume(self.outbox, self.rt, "rt_c14", 1, worker_id="w",
                                  client=transport, claimable_kinds=(C14,))
        self.assertEqual(transport.dispatched_targets, ["c14-rule-compliance.yml"])
        self.assertNotEqual(outcome.get("reason"), "LEASE_LOST")

    def test_the_review_executor_opts_in_without_being_asked(self):
        # Running the review worker the ordinary way - no extra arguments - must be the
        # strict configuration. An opt-in that a unit could forget is not an opt-in.
        self.register(C14, c14_payload(), "rt_c14", status="ESCALATED",
                      lease_until=1_700_000_120.0)
        transport = self.transport(C14)
        outcome = self.worker.tick(self.rt, self.outbox, transport)
        self.assertEqual(transport.dispatched_targets, [], outcome)
        self.assertEqual(outcome["reason"], "LEASE_LOST")
