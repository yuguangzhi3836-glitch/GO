"""A completed Builder run carries its own review round (offline).

What this file proves, and what it deliberately does not
--------------------------------------------------------
The normal path used to stop at the Draft pull request: a person had to notice it and open a
`C14 · REVIEW · ...` issue before anything was reviewed. This file is about the hook that
removed that step, so it stays on the things that can be proven offline:

  REAL   `c1_execution_contract`, `c1_dispatch_outbox`, `c1_result_pull`,
         `c1_execution_loop`, `c1_candidate_reads`, `c1_builder_candidate`, `c1_c13c14_review`
         and - for the negative verdict case - the Lite validators, whose bundles are built
         and sealed by `lite_fixtures` and read back through `lite_chain.verify_round`. If
         the transport re-implemented a review rule, these tests would still pass while the
         system drifted.
  DOUBLE the Runtime (`RuntimeDouble`, imported from the loop's own test module) and the
         GitHub transport (`BuilderGitHub`), which speaks the calls the real client does:
         the dispatch, the sealed result, the run's OWN safe-output record, and the four
         read-only candidate reads.

  NOT PROVEN HERE
         that GitHub runs the workflow, that its safe-outputs job uploads the record, or what
         the reviewers decide. Those need a live Builder run - deliberately not part of this
         candidate.
"""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
for extra in (HERE, ROOT / "control-plane" / "c13-c14-lite"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import c1_builder_candidate as candidate_mod  # noqa: E402
import c1_dispatch_outbox as outbox_mod  # noqa: E402
import c1_execution_contract as contract  # noqa: E402
import c1_execution_loop as loop_mod  # noqa: E402
import c1_candidate_reads as reads  # noqa: E402
import c1_review_issue_ingress as review_ingress  # noqa: E402
import lite_bundle as lite_bundle_mod  # noqa: E402
import os  # noqa: E402
import lite_chain  # noqa: E402
import lite_fixtures  # noqa: E402
from test_c1_execution_loop import Clock, RuntimeDouble  # noqa: E402

# The review adapter resolves the Lite package from a CONFIGURED directory and refuses a
# module that came from anywhere else, so the suite points at one explicitly.
os.environ.setdefault("C13C14_LITE_SOURCE_DIR", str(ROOT / "control-plane" / "c13-c14-lite"))

GH = contract.GHAW_BUILDER_KIND
OWNER = "C12"
WORKER = "go-runtime-host-ghaw-builder-worker"
BUILD_ISSUE = 402
BUILD_TASK = "V71-R1-C12-01"
CANDIDATE = "3f1a" * 10
APPLICATION_TREE = "9c2b" * 10
ROOT_TREE = "5d7e" * 10
PR_NUMBER = 500
RUN_ID = 880001
REVIEW_RUN_ID = 880002
C13_RUN_ID = 880003


def builder_payload(*, issue_number=BUILD_ISSUE, external=BUILD_TASK, cell="C12"):
    return contract.build_task_payload(
        cell_id=cell, external_task_id=external,
        objective="Add one focused regression test for the workbench Cell-role boundary.",
        scope="workbench Cell-role regression only",
        source_anchor="a1b2" * 10, issue_number=issue_number,
        allowed_owner_cs=contract.BUILDER_OWNER_CS)


def claimed(task_id, owner_c, kind, payload, attempts=1, lease_until=1_700_000_120.0):
    class Claimed:
        pass
    c = Claimed()
    c.task_id, c.owner_c, c.kind, c.payload = task_id, owner_c, kind, payload
    c.attempts, c.lease_until = attempts, lease_until
    return c


class TransportFailure(Exception):
    """Not a Runtime refusal: the transport went away. Must never settle an identity."""


class BuilderGitHub:
    """Offline GitHub for a Builder run that may or may not have opened a Draft PR.

    The two halves are the two halves of the real thing: the run's SEALED RESULT (which the
    agent job uploads), and the RUN'S OWN safe-output record plus the pull request it names
    (which the Runtime has to read afterwards, because the result was sealed before the pull
    request existed).
    """

    def __init__(self, *, created=True, base_ref="main", draft=True, head=CANDIDATE,
                 app_tree=APPLICATION_TREE, files=None, record=None,
                 record_present=True, pr_entries=1, root_tree=ROOT_TREE):
        self.created = created
        self.base_ref = base_ref
        self.draft = draft
        self.head = head
        self.app_tree = app_tree
        self.root_tree = root_tree
        self.files = files if files is not None else [
            {"filename": "application/tests/workbench/test_go_parallel_workbench_build01.py",
             "status": "modified"}]
        self.record = record
        self.record_present = record_present
        self.pr_entries = pr_entries
        self.runs = {}
        self.artifacts = {}
        self.members = {}
        self.dispatched = []
        self.lookups = []
        self.reads = []

    # ------------------------------------------------------------------ transport
    def _record_bytes(self):
        if self.record is not None:
            return self.record
        lines = []
        for index in range(self.pr_entries if self.created else 0):
            lines.append(json.dumps({
                "type": "create_pull_request",
                "url": "https://github.com/%s/pull/%d" % (contract.REPO, PR_NUMBER + index),
                "number": PR_NUMBER + index, "repo": contract.REPO, "provider": "github",
                "id": 4731852338, "temporaryId": "aw_%d" % index}))
        if not self.created:
            lines.append(json.dumps({"type": "noop", "message": "nothing to do"}))
        return ("\n".join(lines) + "\n").encode("utf-8")

    def send(self, request):
        self.dispatched.append(request["workflow_file"])
        run_id = RUN_ID
        output = "gh-aw Builder answer for %s" % request["runtime_task_id"]
        self.runs[run_id] = {
            "id": run_id, "run_attempt": 1, "status": "completed", "conclusion": "success",
            "head_sha": contract.REF,
            "name": contract.run_identity_name(request["runtime_task_id"],
                                               request["attempt"],
                                               request["execution_request_id"],
                                               request.get("owner_c", "C1"))}
        document = {
            "version": contract.SCHEMA_VERSION, "kind": contract.RESULT_KIND,
            "runtime_task_id": request["runtime_task_id"], "attempt": request["attempt"],
            "execution_request_id": request["execution_request_id"],
            "github_run_id": run_id, "github_run_attempt": 1,
            "provider": contract.PROVIDER_GHAW_BUILDER, "model": "gh-aw-offline-double",
            "response_id": "stub:gh-aw-no-model-call", "status": "SUCCEEDED",
            "output_sha256": contract.output_sha256(output), "output": output,
            "accepted": True, "reused_terminal_result": False,
            "authorizes_any_action": False}
        raw = contract.canonical(document).encode("utf-8")
        self.artifacts[(run_id, "c1-ai-execution-result-"
                        + request["execution_request_id"])] = {
            "bytes": raw, "digest": "sha256:" + contract.sha256_hex(raw.decode("utf-8")),
            "github_run_id": run_id}
        return ("sent", run_id)

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
        return self.artifacts.get((run_id, name))

    def download_artifact_members(self, run_id, name, members):
        if name == candidate_mod.SAFE_OUTPUTS_ARTIFACT:
            # gh-aw uploads this unconditionally, so it is answerable for any run of the
            # workflow - no `send` needed. A transport that has none is a broken read, not
            # an absent candidate, which is exactly why the hook refuses it.
            if not self.record_present:
                return None
            available = {candidate_mod.SAFE_OUTPUTS_MEMBER: self._record_bytes()}
        else:
            available = self.members.get((run_id, name))
            if available is None:
                return None
        found = {}
        for member in members:
            if member not in available:
                raise contract.Refused("ARTIFACT_MEMBER_MISSING:" + member)
            found[member] = available[member]
        return {"members": found,
                "digests": {k: "sha256:" + hashlib.sha256(v).hexdigest()
                            for k, v in found.items()},
                "github_run_id": run_id}

    # ------------------------------------------------- read-only candidate reads
    def read_pull(self, number):
        self.reads.append(("pull", number))
        if not self.created:
            raise contract.Refused("GITHUB_HTTP_404")
        return {"number": number, "state": "open", "draft": self.draft,
                "base_ref": self.base_ref, "head_sha": self.head}

    def read_pull_files(self, number):
        self.reads.append(("files", number))
        return list(self.files)

    def read_commit_tree(self, commit_sha):
        self.reads.append(("commit", commit_sha))
        return self.root_tree

    def read_tree(self, tree_sha):
        self.reads.append(("tree", tree_sha))
        return [{"path": "application", "type": "tree", "sha": self.app_tree},
                {"path": "README.md", "type": "blob", "sha": "f" * 40}]


def open_outbox(path):
    return outbox_mod.DispatchOutbox(path)


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="c1-auto-review-")
        self.clock = Clock()
        self.rt = RuntimeDouble(self.clock)
        self.path = str(Path(self.tmp) / "outbox-ghaw-builder.db")
        self.outbox = open_outbox(self.path)
        self.addCleanup(self.outbox.close)

    def restart(self):
        """A fresh outbox handle over the same durable file. The worker died; GitHub did
        not, so the transport is deliberately NOT recreated."""
        self.outbox.close()
        self.outbox = open_outbox(self.path)
        self.addCleanup(self.outbox.close)

    def enqueue_builder(self, payload=None, key="k-builder"):
        return self.rt.enqueue(OWNER, GH, payload or builder_payload(),
                               idempotency_key=key, max_attempts=1)

    def tick(self, transport):
        import c1_ghaw_builder_worker as builder
        return builder.tick(self.rt, self.outbox, transport, worker_id=WORKER,
                            clock=self.clock)

    def c14_tasks(self):
        return [t for t in self.rt.tasks.values() if t.kind == contract.C14_REVIEW_KIND]

    def c13_tasks(self):
        return [t for t in self.rt.tasks.values() if t.kind == contract.C13_REVIEW_KIND]

    def request_id(self, task_id, payload=None, attempt=1):
        return contract.build_dispatch_request(
            task_id, attempt, contract.task_spec(GH, payload or builder_payload()))[
                "execution_request_id"]


# ============================================ A: a Builder run that opened a Draft PR
class A_ABuilderWithADraftPrAdmitsItsOwnReview(Case):
    def test_exactly_one_c14_task_is_created_and_the_builder_completes(self):
        task = self.enqueue_builder()
        transport = BuilderGitHub()
        outcome = self.tick(transport)
        self.assertEqual(outcome["status"], "ADVANCED")
        self.assertEqual(outcome["action"], "COMPLETED")
        self.assertEqual(transport.dispatched, ["c1-gh-aw-builder-v1.lock.yml"])

        created = self.c14_tasks()
        self.assertEqual(len(created), 1, "one Builder run, one round")
        self.assertEqual(self.rt.status_of(task), "SUCCEEDED")
        self.assertEqual(self.outbox.snapshot(self.request_id(task))["state"], "COMPLETED")

    def test_the_round_is_named_after_the_builder_issue_and_the_candidate(self):
        self.enqueue_builder()
        self.tick(BuilderGitHub())
        payload = self.c14_tasks()[0].payload
        expected = contract.review_round_identity(BUILD_ISSUE, CANDIDATE)
        self.assertEqual(payload["ledger_round_id"], expected["ledger_round_id"])
        self.assertEqual(payload["external_task_id"], expected["c14_task_id"])
        self.assertEqual(payload["c13_task_id"], expected["c13_task_id"])
        self.assertEqual(payload["issue_number"], BUILD_ISSUE)
        self.assertEqual(payload["cell_id"], "C14")

    def test_the_candidate_facts_come_from_github_not_from_the_payload(self):
        self.enqueue_builder()
        self.tick(BuilderGitHub())
        payload = self.c14_tasks()[0].payload
        self.assertEqual(payload["candidate_sha"], CANDIDATE)
        self.assertEqual(payload["application_tree"], APPLICATION_TREE)
        # The machine inventory is the candidate's OWN changed tests, sanitised by the
        # contract - the same rule the Owner's Review issue path applies.
        self.assertEqual(payload["machine_inventory"],
                         "application/tests/workbench/test_go_parallel_workbench_build01.py")
        self.assertEqual(payload["review_request_id"],
                         contract.review_request_id(CANDIDATE,
                                                    payload["ledger_round_id"]))

    def test_the_two_admission_paths_name_the_same_round(self):
        # The Owner's path and the Builder's path derive the round from the same function,
        # so the same issue and the same candidate cannot be two rounds.
        from_builder = contract.review_round_identity(BUILD_ISSUE, CANDIDATE)
        from_issue = review_ingress.round_identity(BUILD_ISSUE, CANDIDATE)
        self.assertEqual(from_builder, from_issue)

    def test_the_created_payload_is_a_valid_c14_task(self):
        self.enqueue_builder()
        self.tick(BuilderGitHub())
        payload = self.c14_tasks()[0].payload
        contract.validate_review_task_payload(payload, allowed_owner_cs=("C14",))
        self.assertEqual(contract.task_idempotency_key(
            contract.C14_REVIEW_KIND, "C14", payload["external_task_id"]),
            "c1-c13c14-review-v1:C14:" + payload["external_task_id"])

    def test_the_candidate_document_says_it_authorises_nothing(self):
        document = self.resolve()
        self.assertFalse(document["candidate"]["authorizes_any_action"])
        self.assertTrue(document["candidate"]["draft"])
        self.assertEqual(document["candidate"]["base_ref"], "main")
        self.assertEqual(document["candidate"]["github_run_id"], RUN_ID)

    def resolve(self, transport=None, payload=None):
        transport = transport or BuilderGitHub()
        request = contract.build_dispatch_request(
            "rt_x", 1, contract.task_spec(GH, payload or builder_payload()))
        return candidate_mod.resolve_builder_candidate(
            client=transport, run_id=RUN_ID, builder_request=request)


# ============================================ B: the crash window
class B_TheCrashWindowIsRepairedNotRepeated(Case):
    def test_a_crash_after_the_enqueue_is_repaired_with_the_same_c14_task(self):
        task = self.enqueue_builder()
        transport = BuilderGitHub()

        # The Runtime becomes unreachable exactly once, AFTER the C14 enqueue and before the
        # Builder completion - which is the window `complete_after_pull`'s ordering exists
        # for. Only `complete` is broken: everything else stays the real code.
        real_complete = self.rt.complete
        state = {"failures": 1}

        def unreliable(*args, **kwargs):
            if state["failures"]:
                state["failures"] -= 1
                raise TransportFailure("the Runtime was not reachable")
            return real_complete(*args, **kwargs)

        self.rt.complete = unreliable

        first = self.tick(transport)
        self.assertEqual(first["status"], "FAILED", "one bad completion must not be fatal")

        # The C14 task exists - it was enqueued BEFORE the completion was attempted - and the
        # Builder is not complete yet.
        created = self.c14_tasks()
        self.assertEqual(len(created), 1)
        self.assertNotEqual(self.rt.status_of(task), "SUCCEEDED")
        self.assertEqual(self.outbox.snapshot(self.request_id(task))["state"],
                         "RESULT_SEALED")

        # A restart: a fresh outbox handle over the same file, the same transport.
        self.restart()
        second = self.tick(transport)
        self.assertEqual(second["status"], "RESUMED", second)
        self.assertEqual(second["action"], "COMPLETED")
        self.assertEqual(len(self.c14_tasks()), 1, "the same round, not a second one")
        self.assertEqual(self.c14_tasks()[0].task_id, created[0].task_id)
        self.assertEqual(self.rt.status_of(task), "SUCCEEDED")
        self.assertEqual(transport.dispatched, ["c1-gh-aw-builder-v1.lock.yml"])


# ============================================ C: the same result processed repeatedly
class C_TheSameResultIsOneRound(Case):
    def test_reprocessing_a_sealed_result_never_creates_a_second_round(self):
        task = self.enqueue_builder()
        transport = BuilderGitHub()
        self.tick(transport)
        first = self.c14_tasks()[0].task_id

        # The hook itself, run three more times over the same sealed result. Idempotency is
        # the Runtime's key, not a caller's memory.
        request_id = self.request_id(task)
        snapshot = self.outbox.snapshot(request_id)
        request = self.outbox.stored_request(task, 1)
        document = self.outbox.terminal_result(request_id)
        binding = {"owner_c": snapshot["request_json"] and json.loads(
            snapshot["request_json"])["owner_c"],
            "runtime_task_id": snapshot["runtime_task_id"],
            "expected_attempt": snapshot["attempt"]}
        for _ in range(3):
            candidate_mod.enqueue_review_when_the_builder_has_a_candidate(
                document, binding, self.outbox, self.rt, client=transport)
        self.assertEqual(len(self.c14_tasks()), 1)
        self.assertEqual(self.c14_tasks()[0].task_id, first)

    def test_a_completed_tick_does_not_re_run_the_round(self):
        self.enqueue_builder()
        transport = BuilderGitHub()
        self.tick(transport)
        self.restart()
        again = self.tick(transport)
        self.assertEqual(again["status"], "IDLE")
        self.assertEqual(len(self.c14_tasks()), 1)
        self.assertEqual(transport.dispatched, ["c1-gh-aw-builder-v1.lock.yml"])


# ============================================ D: no pull request at all
class D_NoPullRequestIsALegalOutcome(Case):
    def test_a_run_that_created_no_pr_completes_with_no_review(self):
        task = self.enqueue_builder()
        transport = BuilderGitHub(created=False)
        outcome = self.tick(transport)
        self.assertEqual(outcome["status"], "ADVANCED")
        self.assertEqual(outcome["action"], "COMPLETED")
        self.assertEqual(self.rt.status_of(task), "SUCCEEDED")
        self.assertEqual(self.c14_tasks(), [], "no candidate, no round")
        self.assertEqual(self.c13_tasks(), [])
        self.assertEqual(transport.reads, [], "nothing was read: there was nothing to read")

    def test_a_record_with_no_create_pull_request_entry_is_the_same_answer(self):
        transport = BuilderGitHub(created=False, record=b'{"type":"missing_tool"}\n')
        request = contract.build_dispatch_request(
            "rt_x", 1, contract.task_spec(GH, builder_payload()))
        resolved = candidate_mod.resolve_builder_candidate(
            client=transport, run_id=RUN_ID, builder_request=request)
        self.assertFalse(resolved["created_pull_request"])
        self.assertEqual(resolved["reason"], candidate_mod.REASON_NO_CANDIDATE)


# ============================================ E: a candidate that cannot be trusted
class E_AnUnusableCandidateRefusesToCompleteTheBuilder(Case):
    def refuse(self, transport, payload=None):
        task = self.enqueue_builder(payload)
        outcome = self.tick(transport)
        snapshot = self.outbox.snapshot(self.request_id(task, payload))
        return task, outcome, snapshot

    def assert_refused(self, transport, reason, payload=None):
        task, outcome, snapshot = self.refuse(transport, payload)
        self.assertEqual(outcome["status"], "FAILED")
        self.assertEqual(snapshot["state"], "ABANDONED")
        self.assertEqual(snapshot["abandon_reason"],
                         "BUILDER_CANDIDATE_REFUSED:" + reason)
        self.assertNotEqual(self.rt.status_of(task), "SUCCEEDED",
                            "the Builder must not be completed as if all were well")
        self.assertEqual(self.c14_tasks(), [], "no round may be created from a refusal")

    def test_a_pull_request_aimed_somewhere_other_than_main(self):
        self.assert_refused(BuilderGitHub(base_ref="release/next"),
                            reads.REASON_PR_BASE_NOT_MAIN)

    def test_a_pull_request_that_is_not_a_draft(self):
        self.assert_refused(BuilderGitHub(draft=False), candidate_mod.REASON_NOT_DRAFT)

    def test_an_application_tree_that_will_not_resolve(self):
        self.assert_refused(BuilderGitHub(app_tree="not-a-sha"),
                            reads.REASON_TREE_UNRESOLVED)

    def test_a_run_that_claims_two_pull_requests(self):
        self.assert_refused(BuilderGitHub(pr_entries=2), candidate_mod.REASON_PR_AMBIGUOUS)

    def test_a_missing_safe_output_record_is_not_an_absent_candidate(self):
        self.assert_refused(BuilderGitHub(record_present=False),
                            candidate_mod.REASON_RECORD_MISSING)

    def test_a_corrupt_record_is_refused(self):
        self.assert_refused(BuilderGitHub(record=b"{not json}\n"),
                            candidate_mod.REASON_RECORD_INVALID)

    def test_a_builder_task_with_no_originating_issue_cannot_name_a_round(self):
        payload = builder_payload(issue_number=None)
        self.assert_refused(BuilderGitHub(), candidate_mod.REASON_WITHOUT_AN_ISSUE,
                            payload=payload)

    def test_a_refusal_never_leaves_work_in_the_outbox(self):
        self.refuse(BuilderGitHub(draft=False))
        self.assertEqual(self.outbox.unfinished(), [],
                         "a settled identity must not hold the worker forever")


# ============================================ F/G: through the real review chain
def auto_round(*, c14_task_id, c13_task_id, issue_number, round_id,
               c14_verdict="PASS_SCOPED", c13_verdict="PASS_SCOPED",
               candidate_sha=CANDIDATE, application_tree=APPLICATION_TREE):
    """A complete, internally consistent round for the ids the AUTO path derives.

    `lite_fixtures.make_round` names its contract after the fixture's own task ids, and the
    auto path's ids are derived from the Builder's issue and the candidate - so the same
    fixture builders are used here with those ids substituted. Nothing about the round is
    hand-made: the bundles are built and sealed by the Lite fixtures, and the decision is
    produced by `lite_chain.verify_round`.
    """
    fx = lite_fixtures
    now = fx.fresh_now()
    # The Lite dispatch's request id IS the payload's `review_request_id`: the real
    # workflows are handed exactly that string and build their contract from it. The fixture
    # builder hardcodes its own, so it is set here to what the auto path derives - which is
    # what makes this round the one the auto-admitted task actually describes.
    request_id = contract.review_request_id(candidate_sha, round_id)
    c14_contract = fx.contract("c14", candidate_sha=candidate_sha,
                               application_tree=application_tree, task_id=c14_task_id,
                               issue_number=issue_number,
                               ledger_reference={"round_id": round_id, "cell_id": "C14",
                                                 "task_id": c14_task_id}, now=now)
    c14_findings = ([{"id": "F-1", "severity": "MAJOR",
                      "statement": "the candidate breaks a governed rule"}]
                    if c14_verdict == "FAIL" else None)
    c14_contract["request_id"] = request_id
    c14_opinion = fx.opinion("c14", verdict=c14_verdict, candidate_sha=candidate_sha,
                             findings=c14_findings)
    c14_bundle, c14_artifacts = fx.build_bundle(
        "c14", candidate_sha=candidate_sha, application_tree=application_tree,
        dispatch_contract=c14_contract, opinion_obj=c14_opinion, run_id=REVIEW_RUN_ID,
        execution_id="stub-c14-ai-execution-0001", nonce="c14-nonce-000000000001", now=now)
    prereq = {
        "c14_root": c14_bundle[lite_bundle_mod.C14_ROOT_FIELD],
        "c14_verdict": c14_bundle["verdict"],
        "c14_candidate_sha": c14_bundle["candidate_sha"],
        "c14_rule_scope_sha256": c14_bundle["rule_review_scope_sha256"],
        "c14_remediation_closed": c14_bundle["remediation_status"] in ("CLOSED",
                                                                      "NOT_REQUIRED"),
    }
    c13_contract = fx.contract("c13", candidate_sha=candidate_sha,
                               application_tree=application_tree, task_id=c13_task_id,
                               issue_number=issue_number,
                               ledger_reference={"round_id": round_id, "cell_id": "C13",
                                                 "task_id": c13_task_id}, now=now)
    c13_contract["request_id"] = request_id
    c13_opinion = fx.opinion("c13", verdict=c13_verdict, candidate_sha=candidate_sha,
                             remaining_risks=["synthetic residual risk"])
    c13_bundle, c13_artifacts = fx.build_bundle(
        "c13", candidate_sha=candidate_sha, application_tree=application_tree,
        dispatch_contract=c13_contract, opinion_obj=c13_opinion, prereq=prereq,
        run_id=C13_RUN_ID, execution_id="stub-c13-ai-execution-0001",
        nonce="c13-nonce-000000000001", now=now)
    artifacts = dict(c14_artifacts)
    artifacts.update(c13_artifacts)
    dispatch = {
        "candidate_sha": candidate_sha, "application_tree": application_tree,
        "cell_pair": "C13+C14", "issue_number": issue_number,
        "request_id": request_id,
        "c14_task_id": c14_task_id, "c13_task_id": c13_task_id,
        "c14_ledger_reference": c14_contract["ledger_reference"],
        "c13_ledger_reference": c13_contract["ledger_reference"],
    }
    return {"c14_bundle": c14_bundle, "c13_bundle": c13_bundle,
            "c14_contract": c14_contract, "c13_contract": c13_contract,
            "artifacts": artifacts, "dispatch": dispatch, "now": now,
            "implementation_execution_id": "impl-ai-execution-0001"}


class ReviewTransport:
    """Offline GitHub for the review executor: members out of the Lite artifact."""

    def __init__(self, *, bundles, run_id):
        self.bundles = bundles
        self.runs = {}
        self.next_run_id = run_id
        self.dispatched = []

    def send(self, request):
        self.dispatched.append(request["workflow_file"])
        run_id = self.next_run_id
        self.next_run_id += 1
        self.runs[run_id] = {"id": run_id, "run_attempt": 1, "status": "completed",
                            "conclusion": "success", "head_sha": contract.REF,
                            "name": contract.run_identity_name(
                                request["runtime_task_id"], request["attempt"],
                                request["execution_request_id"],
                                request.get("owner_c", "C1"))}
        return ("sent", run_id)

    def find_run(self, run_name):
        for run_id, run in self.runs.items():
            if run["name"] == run_name:
                return run_id
        return None

    find_run_by_name = find_run

    def get_run(self, run_id):
        found = self.runs.get(run_id)
        return None if found is None else dict(found)

    def download_artifact(self, run_id, name):
        raise AssertionError("a review artifact is fetched by members")

    def download_artifact_members(self, run_id, name, members):
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


class F_TheAutoAdmittedC14RunsThroughTheRealChain(Case):
    def auto_c14(self):
        """Builder -> the C14 task the hook created, taken from the outbox, not fabricated."""
        self.enqueue_builder()
        self.tick(BuilderGitHub())
        created = self.c14_tasks()
        self.assertEqual(len(created), 1)
        return created[0]

    def run_review(self, task, bundle, *, decision=None, run_id):
        import c1_c13c14_review_worker as review_worker
        payload = task.payload
        kind = task.kind
        role = "c14" if kind == contract.C14_REVIEW_KIND else "c13"
        members = {"%s_bundle.json" % role: json.dumps(bundle, sort_keys=True).encode()}
        if decision is not None:
            members["round_decision.json"] = json.dumps(
                decision.as_dict() if hasattr(decision, "as_dict") else decision).encode()
        name = contract.review_artifact_name(kind, payload["candidate_sha"])
        transport = ReviewTransport(bundles={name: members}, run_id=run_id)
        hooks = review_worker.review_hooks(self.outbox)
        # The review executor claims its own work; here the task already exists, so the
        # claim it would have made is reproduced on the real task object - status, attempt
        # and lease - and nothing else about the round is faked.
        task.status, task.attempts = "RUNNING", 1
        task.lease_owner, task.lease_until = "review", 1_700_000_120.0
        outcome = loop_mod.advance(
            self.outbox, self.rt, claimed(task.task_id, task.owner_c, kind, payload, 1),
            worker_id="review", client=transport, claimable_kinds=(kind,), **hooks)
        return outcome, transport

    def test_a_negative_c14_is_a_delivered_review_and_creates_no_c13(self):
        task = self.auto_c14()
        round_ = auto_round(c14_task_id=task.payload["external_task_id"],
                            c13_task_id=task.payload["c13_task_id"],
                            issue_number=BUILD_ISSUE,
                            round_id=task.payload["ledger_round_id"],
                            c14_verdict="FAIL")
        self.assertEqual(round_["c14_bundle"]["verdict"], "FAIL")
        outcome, transport = self.run_review(task, round_["c14_bundle"],
                                             run_id=REVIEW_RUN_ID)
        self.assertEqual(outcome["action"], "COMPLETED")
        self.assertEqual(transport.dispatched, ["c14-rule-compliance.yml"])
        self.assertEqual(self.rt.status_of(task.task_id), "SUCCEEDED")
        self.assertEqual(self.c13_tasks(), [],
                         "a C14 that does not admit C13 creates no C13 task")

    def test_the_full_positive_chain_runs_c14_then_c13_exactly_once_each(self):
        task = self.auto_c14()
        round_ = auto_round(c14_task_id=task.payload["external_task_id"],
                            c13_task_id=task.payload["c13_task_id"],
                            issue_number=BUILD_ISSUE,
                            round_id=task.payload["ledger_round_id"])
        c14_outcome, c14_transport = self.run_review(task, round_["c14_bundle"],
                                                     run_id=REVIEW_RUN_ID)
        self.assertEqual(c14_outcome["action"], "COMPLETED")
        self.assertEqual(self.rt.status_of(task.task_id), "SUCCEEDED")

        created = self.c13_tasks()
        self.assertEqual(len(created), 1, "the sealed C14 admits exactly one C13")
        c13_task = created[0]
        self.assertEqual(c13_task.owner_c, "C13")
        self.assertEqual(c13_task.payload["c14_run_id"], REVIEW_RUN_ID)

        # The Lite chain decides, not this file: `verify_round` over the two sealed bundles.
        decision = lite_chain.verify_round(**lite_fixtures.chain_kwargs(round_))
        self.assertEqual(decision.decision, "ACCEPT")
        c13_outcome, c13_transport = self.run_review(c13_task, round_["c13_bundle"],
                                                     decision=decision,
                                                     run_id=C13_RUN_ID)
        self.assertEqual(c13_outcome["action"], "COMPLETED")
        self.assertEqual(c13_transport.dispatched, ["c13-quality-acceptance.yml"])
        self.assertEqual(self.rt.status_of(c13_task.task_id), "SUCCEEDED")
        self.assertEqual(len(self.c14_tasks()), 1)
        self.assertEqual(len(self.c13_tasks()), 1)
        # Three paid executions, three dispatch targets, and not one repeat.
        self.assertEqual(c14_transport.dispatched, ["c14-rule-compliance.yml"])


# ============================================ H: the wiring and the boundaries
class H_TheWiringAndTheBoundaries(unittest.TestCase):
    def test_the_builder_executor_installs_its_completion_hook_by_default(self):
        import c1_ghaw_builder_worker as builder
        import c1_worker as shared
        from test_c1_execution_loop import Clock as _Clock, RuntimeDouble as _RT
        tmp = tempfile.mkdtemp(prefix="c1-wiring-")
        outbox = open_outbox(str(Path(tmp) / "outbox.db"))
        self.addCleanup(outbox.close)
        self.assertIn("on_result_sealed", builder.builder_hooks(outbox))

        # And the RESIDENT loop installs it, so running the worker the ordinary way cannot
        # leave the hand-over unwired. What the loop receives is recorded by intercepting
        # the one tick it runs.
        seen = {}
        original = shared.tick

        def recorder(runtime, opened_outbox, client, **kwargs):
            seen["hooks"] = kwargs
            return {"status": "IDLE"}

        shared.tick = recorder
        emitted = shared.emit
        shared.emit = lambda *args, **kwargs: None
        try:
            code = builder.main(["--once"], runtime=_RT(_Clock()), client=object(),
                                outbox=outbox, token_loader=lambda: "offline-token")
        finally:
            shared.tick = original
            shared.emit = emitted
        self.assertEqual(code, 0)
        self.assertIn("on_result_sealed", seen["hooks"])
        self.assertTrue(callable(seen["hooks"]["on_result_sealed"]))

    def test_the_readiness_check_refuses_a_transport_that_cannot_resolve_a_candidate(self):
        import c1_ghaw_builder_worker as builder

        class NoReads:
            pass

        report = builder.builder_readiness(client=NoReads())
        self.assertEqual(report["status"], "REFUSED")
        self.assertEqual(report["reason"], "BUILDER_COMPLETION_CAPABILITY_MISSING")
        for name in ("read_pull", "read_pull_files", "read_commit_tree", "read_tree"):
            self.assertIn(name, report["detail"])

    def test_the_readiness_check_passes_for_the_real_transport(self):
        import c1_ghaw_builder_worker as builder
        report = builder.builder_readiness(client=BuilderGitHub())
        self.assertNotIn("status", report)

    def test_the_hook_ignores_anything_that_is_not_a_builder_completion(self):
        tmp = tempfile.mkdtemp(prefix="c1-scope-")
        outbox = open_outbox(str(Path(tmp) / "outbox.db"))
        self.addCleanup(outbox.close)
        runtime = RuntimeDouble(Clock())
        review_document = {"kind": contract.REVIEW_RESULT_KIND, "accepted": True}
        binding = {"owner_c": "C14", "runtime_task_id": "rt_r", "expected_attempt": 1}
        self.assertIsNone(
            candidate_mod.enqueue_review_when_the_builder_has_a_candidate(
                review_document, binding, outbox, runtime, client=BuilderGitHub()))
        self.assertEqual(runtime.tasks, {})

    def test_the_round_identity_has_exactly_one_definition(self):
        # The format string exists in the contract and nowhere else. A second copy of
        # "which round is this" is the one thing a round identity may not have.
        sources = [HERE / "c1_candidate_reads.py", HERE / "c1_builder_candidate.py",
                   HERE / "c1_review_issue_ingress.py", HERE / "c1_issue_consumer.py"]
        for path in sources:
            with self.subTest(source=path.name):
                self.assertNotIn("FORMAL-REVIEW-I", path.read_text(encoding="utf-8"))
        self.assertIn("FORMAL-REVIEW-I",
                      (HERE / "c1_execution_contract.py").read_text(encoding="utf-8"))

    def test_the_machine_test_scope_has_exactly_one_definition(self):
        for path in (HERE / "c1_candidate_reads.py", HERE / "c1_builder_candidate.py",
                     HERE / "c1_review_issue_ingress.py"):
            with self.subTest(source=path.name):
                self.assertNotIn("application/tests/[A-Za-z0-9_./-]",
                                 path.read_text(encoding="utf-8"))
        self.assertIn("application/tests/[A-Za-z0-9_./-]",
                      (HERE / "c1_execution_contract.py").read_text(encoding="utf-8"))

    def test_only_one_review_executor_and_one_outbox_exist(self):
        units = sorted(p.name for p in (HERE / "systemd").glob("*.service"))
        self.assertIn("go-runtime-host-c13c14-review-worker.service", units)
        self.assertIn("go-runtime-host-ghaw-builder-worker.service", units)
        self.assertEqual(
            [u for u in units if "c13c14" in u],
            ["go-runtime-host-c13c14-review-worker.service"],
            "one review executor, not one per cell")
        import c1_ghaw_builder_worker as builder
        self.assertEqual(builder.OUTBOX_DB,
                         "/var/lib/go-runtime-c1/outbox-ghaw-builder.db")

    def test_no_second_dispatch_state_machine_was_added(self):
        # The dispatch leg is still the outbox's: exactly one place records a POST.
        source = (HERE / "c1_builder_candidate.py").read_text(encoding="utf-8")
        for forbidden in ("record_dispatch_sent", "dispatch_workflow", "def send"):
            with self.subTest(token=forbidden):
                self.assertNotIn(forbidden, source)


# ============================================ I: the document is checked, not trusted
class I_TheCandidateDocumentIsCheckedNotTrusted(Case):
    """Each required check, directly, on a document that breaks exactly one of them.

    The hook builds this document itself, so a test that only drives the happy path would
    never exercise a single one of these lines - and "the checks are dead code" is exactly
    how a boundary rots. Every case below breaks one field and nothing else.
    """

    def document(self, **over):
        base = {"version": candidate_mod.BUILDER_CANDIDATE_VERSION,
                "kind": candidate_mod.BUILDER_CANDIDATE_KIND,
                "runtime_task_id": "rt_auto", "attempt": 1,
                "execution_request_id": "e" * 64, "github_run_id": RUN_ID,
                "pr_number": PR_NUMBER, "pr_url": "https://github.com/x/y/pull/500",
                "candidate_sha": CANDIDATE, "base_ref": "main", "draft": True,
                "application_tree": APPLICATION_TREE, "machine_inventory": None,
                "authorizes_any_action": False}
        base.update(over)
        return base

    def checking(self, **over):
        return candidate_mod.check_candidate_document(
            self.document(**over), run_id=RUN_ID,
            binding={"owner_c": OWNER, "runtime_task_id": "rt_auto", "expected_attempt": 1},
            document={"execution_request_id": "e" * 64, "attempt": 1,
                      "github_run_id": RUN_ID})

    def refuse(self, reason, **over):
        with self.assertRaises(contract.Refused) as caught:
            self.checking(**over)
        self.assertIn(reason, caught.exception.reason)

    def test_a_well_formed_document_passes(self):
        self.checking()

    def test_an_unknown_field_is_refused(self):
        self.refuse("UNKNOWN_FIELD", verdict="PASS_SCOPED")

    def test_a_missing_field_is_refused(self):
        incomplete = self.document()
        del incomplete["application_tree"]
        with self.assertRaises(contract.Refused) as caught:
            candidate_mod.check_candidate_document(
                incomplete, run_id=RUN_ID,
                binding={"owner_c": OWNER, "runtime_task_id": "rt_auto",
                         "expected_attempt": 1},
                document={"execution_request_id": "e" * 64, "attempt": 1,
                          "github_run_id": RUN_ID})
        self.assertIn("MISSING_FIELD", caught.exception.reason)

    def test_a_wrong_kind_or_version_is_refused(self):
        self.refuse("KIND_OR_VERSION", version=2)

    def test_a_document_from_another_runtime_task_is_refused(self):
        self.refuse(candidate_mod.REASON_IDENTITY, runtime_task_id="rt_other")

    def test_a_document_from_another_execution_identity_is_refused(self):
        self.refuse(candidate_mod.REASON_IDENTITY, execution_request_id="f" * 64)

    def test_a_document_from_another_attempt_is_refused(self):
        self.refuse(candidate_mod.REASON_IDENTITY, attempt=2)

    def test_a_document_from_another_run_is_refused(self):
        self.refuse(candidate_mod.REASON_RUN_ID, github_run_id=RUN_ID + 1)

    def test_a_document_may_never_authorise_anything(self):
        self.refuse("AUTHORIZES_ANY_ACTION", authorizes_any_action=True)

    def test_a_candidate_that_is_not_a_draft_is_refused(self):
        self.refuse(candidate_mod.REASON_NOT_DRAFT, draft=False)

    def test_a_candidate_aimed_elsewhere_is_refused(self):
        self.refuse("BASE_REF", base_ref="release/next")

    def test_a_truncated_candidate_sha_is_refused(self):
        self.refuse("CANDIDATE_SHA", candidate_sha=CANDIDATE[:39])

    def test_a_truncated_application_tree_is_refused(self):
        self.refuse("APPLICATION_TREE", application_tree=APPLICATION_TREE[:39])

    def test_a_blank_machine_inventory_is_refused(self):
        self.refuse("MACHINE_INVENTORY", machine_inventory="   ")

    def test_an_unparseable_pull_request_number_is_refused(self):
        self.refuse(candidate_mod.REASON_PR_NUMBER_INVALID,
                    pr_number="500", pr_url="https://github.com/x/y/pull/500")

    def test_the_machine_test_scope_reaches_a_shell_only_as_a_plain_path(self):
        # The value is interpolated into the C13 workflow's own command, so the sanitiser is
        # the thing standing between a candidate's diff and a shell.
        inventory = contract.review_test_inventory([
            {"filename": "application/tests/workbench/test_a.py", "status": "modified"},
            {"filename": "application/tests/a.py; rm -rf /", "status": "modified"},
            {"filename": "application/src/go_hotel/no_test.py", "status": "modified"},
            {"filename": "application/tests/gone.py", "status": "removed"},
            {"filename": "application/tests/b.py", "status": "added"},
        ])
        self.assertEqual(inventory, "application/tests/b.py application/tests/workbench/test_a.py")

    def test_a_candidate_that_changed_no_test_leaves_the_cells_default_standing(self):
        self.assertIsNone(contract.review_test_inventory(
            [{"filename": "application/src/go_hotel/x.py", "status": "modified"}]))


if __name__ == "__main__":
    unittest.main()
