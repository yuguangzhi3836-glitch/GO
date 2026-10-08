"""Formal Review Issue ingress tests: `C14 · REVIEW · ...` -> Runtime, offline.

Coverage map (the shape this round had to prove):

  A  AValidReviewIssueBecomesOneC14Plan      valid issue -> ONE C14 plan, derived ids
  B  TheOwnerCannotCommissionTheSecondHalf   `C13 · REVIEW` refused; no C13 from an issue
  C  MalformedIssuesFailClosed               missing PR, missing SHA, ambiguity, closed
  D  TheCandidateIsFrozen                    head moved / base is not main -> refused
  E  TheApplicationTreeIsTheFrozenCommits    resolved at the candidate; no fallback
  F  RepeatPollingIsOneRuntimeTask           N polls -> one Runtime task, kind C14 only
  G  TheBuilderPathIsUntouched               #79-#88 still stale-refused; keys unchanged
  H  ReadOnlyAndBounded                      GET-only transport, no store, no second loop
  I  U6AndLegacyAreUntouched                 gate still disabled; no legacy kind producer
  J  ARoundCanBeRaisedOnlyByRevision         `Review revision: n` = a new human round; R1
                                             stays byte-identical; a round is still 1 attempt

No network, no Runtime host, no model call, no GitHub write.
"""
import ast
import json
import re
import sqlite3
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import c1_execution_contract as contract  # noqa: E402
import c1_issue_consumer as consumer  # noqa: E402
import c1_review_issue_ingress as ingress  # noqa: E402

REVIEW_SOURCE = HERE / "c1_review_issue_ingress.py"
FIXTURE = HERE / "issue_fixtures" / "real_c01_issues.json"

# The real values of the round this ingress was built for (PR #394), so the fixture a
# reader is asked for is the one a live poll would ask for.
CANDIDATE = "0cb92ac7900cd177be383a4429a2759007119a10"
CANDIDATE_TREE = "34c5ab3cc0eaf97a0556fedc6f7dbc661e1578f0"
ROOT_TREE = "dee681bfc20026817cedde1cb822a0a072ad8d52"
# The live base the happy-path PR is aimed at. It is a value of the PR, not an input to the
# review: the ingress reads it and freezes it.
MAIN_SHA = "d" * 40
MOVED_HEAD = "1" * 40
PR_NUMBER = 394
ISSUE_NUMBER = 901
SHORT = CANDIDATE[:12]

REVIEW_BODY = "Candidate PR: #%d\nCandidate SHA: %s\n" % (PR_NUMBER, CANDIDATE)
REVIEW_TITLE = "C14 · REVIEW · formal ingress canary"

FAKE_API = "https://api.example.invalid"
TEST_TOKEN = "not-a-real-token"
ENABLED = {consumer.INGRESS_ENABLED_ENV: "true"}
# The source anchor the captured #79-#88 bodies carry. Live, main has long since moved past
# it - which is exactly why those issues are refused, and what class G reproduces.
FIXTURE_SOURCE = "8ffcde66d36c1bbf849218529ef015f6e81725af"


def load_fixture() -> list:
    with open(FIXTURE, encoding="utf-8") as handle:
        return json.load(handle)["issues"]


def review_issue(number=ISSUE_NUMBER, *, title=None, body=None, state="open"):
    return {"number": number, "state": state,
            "title": REVIEW_TITLE if title is None else title,
            "body": REVIEW_BODY if body is None else body}


def only_such_issue():
    return [review_issue()]


# --------------------------------------------------------------------------- doubles
class FakeReader:
    """The consumer's candidate reads, answered from canned documents.

    Only the five methods the review ingress is allowed to ask for exist here, so a call it
    was not supposed to make fails loudly instead of silently reaching further.
    """

    def __init__(self, *, pull=None, files=None, commit_trees=None, trees=None,
                 missing_pull=False, missing_commit=False, compare=None):
        self.pull = pull
        self.files = [] if files is None else files
        self.commit_trees = dict(commit_trees or {})
        self.trees = dict(trees or {})
        self.missing_pull = missing_pull
        self.missing_commit = missing_commit
        self.compare = compare
        self.calls = []

    def read_pull(self, number):
        self.calls.append(("read_pull", number))
        if self.missing_pull:
            raise contract.Refused("GITHUB_HTTP_404")
        return dict(self.pull or {})

    def read_compare(self, base_sha, head_sha):
        self.calls.append(("read_compare", (base_sha, head_sha)))
        if self.compare is not None:
            return self.compare
        # The ordinary answer for a candidate branched off its own base: that base IS the
        # merge base of `base...head`.
        return {"status": "ahead", "merge_base_commit": {"sha": base_sha}}

    def read_pull_files(self, number):
        self.calls.append(("read_pull_files", number))
        return list(self.files)

    def read_commit_tree(self, commit_sha):
        self.calls.append(("read_commit_tree", commit_sha))
        if self.missing_commit or commit_sha not in self.commit_trees:
            raise contract.Refused("GITHUB_HTTP_404")
        return self.commit_trees[commit_sha]

    def read_tree(self, tree_sha):
        self.calls.append(("read_tree", tree_sha))
        if tree_sha not in self.trees:
            raise contract.Refused("GITHUB_HTTP_404")
        return list(self.trees[tree_sha])


def happy_reader(**over) -> FakeReader:
    """A reader whose answers describe PR #394 at the frozen candidate commit."""
    base = dict(
        pull={"number": PR_NUMBER, "state": "open", "base_ref": "main",
              "base_sha": MAIN_SHA, "head_sha": CANDIDATE},
        files=[{"filename": "application/tests/workbench/test_x.py", "status": "added"}],
        commit_trees={CANDIDATE: ROOT_TREE},
        trees={ROOT_TREE: [{"path": "README.md", "mode": "100644", "type": "blob",
                            "sha": "2" * 40},
                           {"path": "application", "mode": "040000", "type": "tree",
                            "sha": CANDIDATE_TREE}]})
    base.update(over)
    return FakeReader(**base)


class FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class ReviewOpener:
    """A transport for the whole consumer: the listing plus every candidate read."""

    def __init__(self, listing, *, source_head=FIXTURE_SOURCE, **reader_kwargs):
        self.reader = FakeReader(**reader_kwargs) if reader_kwargs else happy_reader()
        self.calls = []
        self._listing = listing
        self._source_head = source_head

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.calls.append({"method": request.get_method(), "url": url})
        path = url.split("?")[0]
        if path == FAKE_API + consumer.SOURCE_HEAD_PATH:
            return FakeResponse(json.dumps({"sha": self._source_head}).encode("utf-8"))
        if path == FAKE_API + consumer.ISSUES_PATH:
            match = re.search(r"[?&]page=(\d+)", url)
            page = int(match.group(1)) if match else 1
            return FakeResponse(json.dumps(self._listing if page == 1 else []).encode("utf-8"))
        if path.endswith("/files"):
            return FakeResponse(json.dumps(self.reader.read_pull_files(0)).encode("utf-8"))
        if "/git/trees/" in path:
            sha = path.rsplit("/", 1)[1]
            return FakeResponse(json.dumps({"tree": self.reader.read_tree(sha)}).encode("utf-8"))
        if "/commits/" in path:
            sha = path.rsplit("/", 1)[1]
            return FakeResponse(json.dumps(
                {"commit": {"tree": {"sha": self.reader.read_commit_tree(sha)}}}).encode("utf-8"))
        if "/compare/" in path:
            pair = path.rsplit("/", 1)[1].split("...")
            return FakeResponse(json.dumps(
                self.reader.read_compare(*pair)).encode("utf-8"))
        if "/pulls/" in path:
            return FakeResponse(json.dumps({
                "number": PR_NUMBER, "state": "open",
                "base": {"ref": self.reader.pull["base_ref"],
                         "sha": self.reader.pull.get("base_sha")},
                "head": {"sha": self.reader.pull["head_sha"]}}).encode("utf-8"))
        raise AssertionError("unexpected path %s" % path)

    @property
    def verbs(self):
        return sorted({call["method"] for call in self.calls})


class RuntimeDouble:
    """The kernel's enqueue semantics the ingress relies on: key is UNIQUE."""

    def __init__(self, path):
        self.enqueue_calls = 0
        self._db = sqlite3.connect(str(path))
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS tasks (
                   task_id TEXT PRIMARY KEY, owner_c TEXT NOT NULL, kind TEXT NOT NULL,
                   payload_json TEXT NOT NULL, idempotency_key TEXT UNIQUE,
                   max_attempts INTEGER NOT NULL, status TEXT NOT NULL)""")

    def enqueue(self, owner_c, kind, payload, *, created_by_c=None, priority=100,
                available_at=None, max_attempts=5, idempotency_key=None):
        self.enqueue_calls += 1
        if idempotency_key is not None:
            row = self._db.execute("SELECT task_id FROM tasks WHERE idempotency_key = ?",
                                   (idempotency_key,)).fetchone()
            if row is not None:
                return row[0]
        task_id = "rt_" + uuid.uuid4().hex
        self._db.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?,?)",
                         (task_id, owner_c, kind, contract.canonical(payload),
                          idempotency_key, max_attempts, "QUEUED"))
        self._db.commit()
        return task_id

    def task_count(self):
        return self._db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

    def rows(self):
        return self._db.execute(
            "SELECT task_id, owner_c, kind, payload_json, idempotency_key, max_attempts"
            " FROM tasks ORDER BY rowid").fetchall()

    def close(self):
        self._db.close()


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rvi-")

    def runtime(self):
        rt = RuntimeDouble(Path(self.tmp) / "runtime.db")
        self.addCleanup(rt.close)
        return rt


# =============================================== A: the happy path, and only one task
class A_AValidReviewIssueBecomesOneC14Plan(Case):
    def test_a_valid_issue_plans_exactly_one_c14_task(self):
        plan = ingress.plan_review_ingress(review_issue(), reader=happy_reader(),
                                           environ=ENABLED)
        self.assertEqual(plan["action"], "SHADOW_PLAN")
        self.assertFalse(plan["enqueued"])
        call = plan["would_enqueue"]
        self.assertEqual(call["owner_c"], "C14")
        self.assertEqual(call["kind"], contract.C14_REVIEW_KIND)
        self.assertEqual(call["max_attempts"], 1)
        self.assertEqual(call["payload"]["candidate_sha"], CANDIDATE)
        self.assertEqual(call["payload"]["application_tree"], CANDIDATE_TREE)
        self.assertEqual(call["payload"]["issue_number"], ISSUE_NUMBER)
        self.assertEqual(call["payload"]["cell_id"], "C14")

    def test_disabled_plans_but_never_enqueues(self):
        plan = ingress.plan_review_ingress(review_issue(), reader=happy_reader(),
                                           environ={})
        self.assertEqual(plan["action"], "DISABLED")
        self.assertFalse(plan["enabled"])

    def test_enabled_without_a_runtime_is_loud_not_silent(self):
        # "Enabled but nothing to enqueue into" must be a refusal, not a no-op that looks
        # like success - the same rule the Builder ingress holds.
        with self.assertRaises(contract.Refused) as caught:
            ingress.ingest_review(review_issue(), reader=happy_reader(),
                                  runtime=None, environ=ENABLED)
        self.assertEqual(caught.exception.reason, "RUNTIME_REQUIRED_WHEN_INGRESS_ENABLED")

    def test_disabled_never_reaches_a_runtime_even_when_one_is_handed_over(self):
        rt = self.runtime()
        result = ingress.ingest_review(review_issue(), reader=happy_reader(),
                                       runtime=rt, environ={})
        self.assertFalse(result["enqueued"])
        self.assertEqual(rt.task_count(), 0)

    def test_the_identity_is_derived_from_the_issue_and_the_frozen_candidate(self):
        plan = ingress.plan_review_ingress(review_issue(), reader=happy_reader(),
                                           environ=ENABLED)
        self.assertEqual(plan["ledger_round_id"], "FORMAL-REVIEW-I901-%s" % SHORT)
        self.assertEqual(plan["would_enqueue"]["payload"]["c14_task_id"],
                         "FORMAL-REVIEW-I901-%s-C14" % SHORT)
        self.assertEqual(plan["would_enqueue"]["payload"]["c13_task_id"],
                         "FORMAL-REVIEW-I901-%s-C13" % SHORT)
        self.assertEqual(
            plan["would_enqueue"]["idempotency_key"],
            contract.task_idempotency_key(contract.C14_REVIEW_KIND, "C14",
                                          "FORMAL-REVIEW-I901-%s-C14" % SHORT))

    def test_the_request_id_matches_the_manual_tools_derivation(self):
        # Two admission paths - this ingress and `deliver_review_round.py` - name the same
        # round. The derivation lives once, in the contract, and the manual tool delegates
        # to it; this binds the two names together so neither can drift.
        import deliver_review_round

        round_id = "FORMAL-REVIEW-I901-%s" % SHORT
        self.assertEqual(contract.review_request_id(CANDIDATE, round_id),
                         deliver_review_round.deterministic_request_id(CANDIDATE, round_id))
        plan = ingress.plan_review_ingress(review_issue(), reader=happy_reader(),
                                           environ=ENABLED)
        self.assertEqual(plan["would_enqueue"]["payload"]["review_request_id"],
                         contract.review_request_id(CANDIDATE, round_id))

    def test_the_same_issue_and_candidate_always_produce_the_same_everything(self):
        first = ingress.plan_review_ingress(review_issue(), reader=happy_reader(),
                                            environ=ENABLED)
        second = ingress.plan_review_ingress(review_issue(), reader=happy_reader(),
                                             environ=ENABLED)
        self.assertEqual(first, second)

    def test_a_different_candidate_is_a_different_round(self):
        other = "3" * 40
        other_issue = review_issue(
            902, body="Candidate PR: #395\nCandidate SHA: %s\n" % other)
        plan = ingress.plan_review_ingress(review_issue(), reader=happy_reader(),
                                           environ=ENABLED)
        other_plan = ingress.plan_review_ingress(
            other_issue,
            reader=happy_reader(pull=dict(happy_reader().pull, head_sha=other),
                                commit_trees={other: ROOT_TREE}),
            environ=ENABLED)
        self.assertNotEqual(plan["ledger_round_id"], other_plan["ledger_round_id"])
        self.assertNotEqual(plan["would_enqueue"]["idempotency_key"],
                            other_plan["would_enqueue"]["idempotency_key"])


# ==================================== B: the second half is never an issue's to create
class B_TheOwnerCannotCommissionTheSecondHalf(Case):
    def test_a_c13_review_issue_is_refused_by_name(self):
        issue = review_issue(title="C13 · REVIEW · let me skip ahead")
        with self.assertRaises(contract.Refused) as caught:
            ingress.parse_review_issue(issue)
        self.assertEqual(caught.exception.reason, "REVIEW_TITLE_CELL_IS_NOT_THE_REVIEW_CELL")
        # It reaches the parser rather than being silently dropped: an attempt to
        # commission the second half is a fact worth a refusal line.
        self.assertTrue(ingress.looks_like_review_issue(issue))

    def test_the_ingress_cannot_name_the_c13_kind_at_all(self):
        # An AST check rather than a text one: this module's DOCSTRING says where the C13
        # half comes from, which is documentation, while an import or a call would be the
        # real dependency. Only the second kind is forbidden.
        tree = ast.parse(REVIEW_SOURCE.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        self.assertNotIn("c1_c13c14_review", imported)
        self.assertNotIn("c1_c13c14_review_worker", imported)
        calls = {node.func.attr for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        self.assertNotIn("enqueue_c13_when_c14_admits", calls)
        identifiers = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        identifiers |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        self.assertNotIn("C13_REVIEW_KIND", identifiers)
        self.assertNotIn("C13_REVIEW_V1", identifiers)
        # The C13 Lite id travels as a payload FIELD - the C14 half carries the round's
        # identity - and never as something this module enqueues.
        self.assertEqual(ingress.REVIEW_INGRESS_OWNER_CS, ("C14",))
        self.assertIs(ingress.REVIEW_INGRESS_KIND, contract.C14_REVIEW_KIND)

    def test_one_enqueue_call_and_it_is_the_c14_one(self):
        source = REVIEW_SOURCE.read_text(encoding="utf-8")
        self.assertEqual(source.count("runtime.enqueue("), 1)
        plan = ingress.plan_review_ingress(review_issue(), reader=happy_reader(),
                                           environ=ENABLED)
        self.assertEqual(plan["would_enqueue"]["kind"], contract.C14_REVIEW_KIND)

    def test_an_enabled_poll_creates_exactly_one_task_and_it_is_the_c14_one(self):
        rt = self.runtime()
        result = consumer.poll_once(reader=consumer.GitHubIssuesReader(
            token_loader=lambda: TEST_TOKEN,
            opener=ReviewOpener([review_issue()], **happy_kwargs()),
            api_base=FAKE_API), runtime_factory=lambda: rt, environ=ENABLED)
        self.assertEqual(result["review_enqueued"][0]["issue_number"], ISSUE_NUMBER)
        self.assertEqual(rt.task_count(), 1)
        self.assertEqual([(row[1], row[2]) for row in rt.rows()], [("C14", contract.C14_REVIEW_KIND)])


def happy_kwargs():
    """`ReviewOpener` keyword form of the happy-path documents (the opener builds a reader)."""
    return {"pull": {"number": PR_NUMBER, "state": "open", "base_ref": "main",
                     "base_sha": MAIN_SHA, "head_sha": CANDIDATE},
            "files": [{"filename": "application/tests/workbench/test_x.py",
                       "status": "added"}],
            "commit_trees": {CANDIDATE: ROOT_TREE},
            "trees": {ROOT_TREE: [{"path": "application", "mode": "040000",
                                   "type": "tree", "sha": CANDIDATE_TREE}]}}


# ==================================================== C: malformed issues fail closed
class C_MalformedIssuesFailClosed(unittest.TestCase):
    def test_a_missing_candidate_pr_line_is_refused(self):
        issue = review_issue(body="Candidate SHA: %s\n" % CANDIDATE)
        with self.assertRaises(contract.Refused) as caught:
            ingress.parse_review_issue(issue)
        self.assertEqual(caught.exception.reason, "REVIEW_CANDIDATE_PR_NOT_FOUND")

    def test_a_missing_candidate_sha_line_is_refused(self):
        issue = review_issue(body="Candidate PR: #%d\n" % PR_NUMBER)
        with self.assertRaises(contract.Refused) as caught:
            ingress.parse_review_issue(issue)
        self.assertEqual(caught.exception.reason, "REVIEW_CANDIDATE_SHA_NOT_FOUND")

    def test_a_pr_number_that_is_not_a_number_is_refused(self):
        issue = review_issue(body="Candidate PR: #the-latest\nCandidate SHA: %s\n" % CANDIDATE)
        with self.assertRaises(contract.Refused) as caught:
            ingress.parse_review_issue(issue)
        self.assertEqual(caught.exception.reason, "REVIEW_CANDIDATE_PR_INVALID")

    def test_a_sha_that_is_not_a_commit_is_refused(self):
        issue = review_issue(body="Candidate PR: #394\nCandidate SHA: not-a-commit\n")
        with self.assertRaises(contract.Refused) as caught:
            ingress.parse_review_issue(issue)
        self.assertEqual(caught.exception.reason, "REVIEW_CANDIDATE_SHA_INVALID")

    def test_two_different_frozen_commits_are_ambiguous_not_resolved(self):
        issue = review_issue(body=REVIEW_BODY + "Candidate SHA: %s\n" % ("9" * 40))
        with self.assertRaises(contract.Refused) as caught:
            ingress.parse_review_issue(issue)
        self.assertEqual(caught.exception.reason, "REVIEW_CANDIDATE_SHA_AMBIGUOUS")

    def test_a_closed_issue_is_refused(self):
        with self.assertRaises(contract.Refused) as caught:
            ingress.parse_review_issue(review_issue(state="closed"))
        self.assertEqual(caught.exception.reason, "ISSUE_NOT_OPEN")

    def test_a_title_without_the_marker_is_not_a_review_issue(self):
        for title in ("C14 · V70-R3-C14-01 · constitutional review",
                      "C14 REVIEW for the canary",
                      "REVIEW · C14 · out of order"):
            with self.subTest(title=title):
                self.assertFalse(ingress.looks_like_review_issue(review_issue(title=title)))
        # A pull request is never an issue, here either.
        pull = review_issue()
        pull["pull_request"] = {"url": "x"}
        self.assertFalse(ingress.looks_like_review_issue(pull))

    def test_another_cells_review_marker_still_reaches_the_parser(self):
        # It is review-SHAPED, so the pre-filter must surface it as a refusal rather than
        # drop it: the marker is what the filter keys on, and the CELL is what the parser
        # refuses. A silently ignored attempt to commission the wrong half would leave no
        # record of the attempt.
        issue = review_issue(title="C01 · REVIEW · wrong family entirely")
        self.assertTrue(ingress.looks_like_review_issue(issue))
        with self.assertRaises(contract.Refused) as caught:
            ingress.parse_review_issue(issue)
        self.assertEqual(caught.exception.reason, "REVIEW_TITLE_CELL_IS_NOT_THE_REVIEW_CELL")

    def test_a_review_issue_is_never_builder_work_and_vice_versa(self):
        self.assertFalse(consumer.looks_like_builder_issue(review_issue()))
        builder = {"number": 79, "state": "open",
                   "title": "C01 · V70-R3-C01-01 · diagnostics", "body": "x"}
        self.assertFalse(ingress.looks_like_review_issue(builder))


# ============ D: the candidate is frozen (head, and its REAL base read from the PR)
class D_TheCandidateIsFrozen(Case):
    def test_a_moved_head_is_refused_and_carries_both_commits(self):
        reader = happy_reader(pull={"number": PR_NUMBER, "state": "open",
                                    "base_ref": "main", "head_sha": MOVED_HEAD})
        with self.assertRaises(ingress.CandidateHeadMoved) as caught:
            ingress.plan_review_ingress(review_issue(), reader=reader, environ=ENABLED)
        self.assertEqual(caught.exception.reason, "REVIEW_CANDIDATE_HEAD_MOVED")
        self.assertEqual(caught.exception.candidate_sha, CANDIDATE)
        self.assertEqual(caught.exception.head_sha, MOVED_HEAD)
        # Nothing was read past the PR, and nothing was planned: the refusal happens before
        # the application tree is even asked for, let alone before a Runtime exists.
        self.assertEqual([name for name, _arg in reader.calls], ["read_pull"])

    def test_a_moved_head_does_not_follow_the_branch(self):
        reader = happy_reader(pull={"number": PR_NUMBER, "state": "open",
                                    "base_ref": "main", "head_sha": MOVED_HEAD})
        rt = self.runtime()
        with self.assertRaises(ingress.CandidateHeadMoved):
            ingress.ingest_review(review_issue(), reader=reader, runtime=rt, environ=ENABLED)
        self.assertEqual(rt.task_count(), 0)

    def test_a_non_main_base_is_frozen_from_the_pr_not_refused(self):
        # #565 之前这条会 REFUSE(REVIEW_CANDIDATE_BASE_IS_NOT_MAIN)。现在 base 是候选 PR
        # 自己的事实：读出来、冻住、进 payload，而不是要求 Owner 手写或要求 base=main。
        reader = happy_reader(pull={"number": PR_NUMBER, "state": "open",
                                    "base_ref": "release/next", "base_sha": "e" * 40,
                                    "head_sha": CANDIDATE})
        plan = ingress.plan_review_ingress(review_issue(), reader=reader, environ=ENABLED)
        self.assertEqual(plan["would_enqueue"]["payload"]["frozen_base"],
                         {"ref": "release/next", "sha": "e" * 40, "pr_number": PR_NUMBER})
        # 没有手写 base 字段 => 不触发“必须显式 inventory”的收窄规则。
        self.assertEqual(plan["machine_inventory_source"], "candidate_changed_tests")

    def test_a_main_base_is_frozen_the_same_way(self):
        plan = ingress.plan_review_ingress(review_issue(), reader=happy_reader(),
                                           environ=ENABLED)
        self.assertEqual(plan["would_enqueue"]["payload"]["frozen_base"],
                         {"ref": "main", "sha": MAIN_SHA, "pr_number": PR_NUMBER})

    def test_a_non_ancestor_base_is_refused(self):
        reader = happy_reader(compare={"status": "diverged",
                                       "merge_base_commit": {"sha": "9" * 40}})
        with self.assertRaises(contract.Refused) as caught:
            ingress.plan_review_ingress(review_issue(), reader=reader, environ=ENABLED)
        self.assertEqual(caught.exception.reason, "REVIEW_FROZEN_BASE_NOT_ANCESTOR")

    def test_a_missing_pull_request_is_refused_by_name(self):
        reader = happy_reader()
        reader.missing_pull = True
        with self.assertRaises(contract.Refused) as caught:
            ingress.plan_review_ingress(review_issue(), reader=reader, environ=ENABLED)
        self.assertEqual(caught.exception.reason, "REVIEW_CANDIDATE_PR_NOT_FOUND")

    def test_the_pull_request_is_read_once_per_plan(self):
        reader = happy_reader()
        ingress.plan_review_ingress(review_issue(), reader=reader, environ=ENABLED)
        self.assertEqual([name for name, _arg in reader.calls].count("read_pull"), 1)
        self.assertEqual(reader.calls[0], ("read_pull", PR_NUMBER))


# ============================================ E: the tree comes from the frozen commit
class E_TheApplicationTreeIsTheFrozenCommits(unittest.TestCase):
    def test_the_tree_is_resolved_at_the_candidate_commit(self):
        reader = happy_reader()
        ingress.plan_review_ingress(review_issue(), reader=reader, environ=ENABLED)
        self.assertIn(("read_commit_tree", CANDIDATE), reader.calls)
        self.assertIn(("read_tree", ROOT_TREE), reader.calls)

    def test_an_unresolvable_commit_is_refused(self):
        reader = happy_reader(commit_trees={})
        with self.assertRaises(contract.Refused) as caught:
            ingress.plan_review_ingress(review_issue(), reader=reader, environ=ENABLED)
        self.assertEqual(caught.exception.reason, "REVIEW_APPLICATION_TREE_UNRESOLVED")

    def test_a_root_tree_without_an_application_entry_is_refused(self):
        reader = happy_reader(trees={ROOT_TREE: [
            {"path": "src", "mode": "040000", "type": "tree", "sha": "4" * 40}]})
        with self.assertRaises(contract.Refused) as caught:
            ingress.plan_review_ingress(review_issue(), reader=reader, environ=ENABLED)
        self.assertEqual(caught.exception.reason, "REVIEW_APPLICATION_TREE_UNRESOLVED")

    def test_an_application_entry_that_is_not_a_tree_is_refused(self):
        reader = happy_reader(trees={ROOT_TREE: [
            {"path": "application", "mode": "100644", "type": "blob", "sha": "5" * 40}]})
        with self.assertRaises(contract.Refused) as caught:
            ingress.plan_review_ingress(review_issue(), reader=reader, environ=ENABLED)
        self.assertEqual(caught.exception.reason, "REVIEW_APPLICATION_TREE_UNRESOLVED")

    def test_an_application_entry_with_a_malformed_sha_is_refused(self):
        reader = happy_reader(trees={ROOT_TREE: [
            {"path": "application", "mode": "040000", "type": "tree", "sha": "not-a-tree"}]})
        with self.assertRaises(contract.Refused) as caught:
            ingress.plan_review_ingress(review_issue(), reader=reader, environ=ENABLED)
        self.assertEqual(caught.exception.reason, "REVIEW_APPLICATION_TREE_UNRESOLVED")

    def test_there_is_no_fallback_to_another_tree(self):
        # The only tree named in the payload is the frozen candidate's, and a reader that
        # cannot answer for it produces a refusal rather than a default.
        reader = happy_reader(commit_trees={"f" * 40: ROOT_TREE})
        with self.assertRaises(contract.Refused):
            ingress.plan_review_ingress(review_issue(), reader=reader, environ=ENABLED)
        source = REVIEW_SOURCE.read_text(encoding="utf-8")
        for forbidden in ("or MAIN", "default_tree", "workflow_default_tree"):
            with self.subTest(token=forbidden):
                self.assertNotIn(forbidden, source)


# ============================================ F: repeat polling is one Runtime task
class F_RepeatPollingIsOneRuntimeTask(Case):
    def poll(self, rt, listing):
        return consumer.poll_once(
            reader=consumer.GitHubIssuesReader(
                token_loader=lambda: TEST_TOKEN,
                opener=ReviewOpener(listing, **happy_kwargs()), api_base=FAKE_API),
            runtime_factory=lambda: rt, environ=ENABLED)

    def test_ten_polls_produce_one_row_and_one_task_id(self):
        rt = self.runtime()
        ids = {self.poll(rt, [review_issue()])["review_enqueued"][0]["runtime_task_id"]
               for _ in range(10)}
        self.assertEqual(len(ids), 1, ids)
        self.assertEqual(rt.task_count(), 1)

    def test_a_second_review_issue_for_another_candidate_is_a_second_task(self):
        rt = self.runtime()
        other = "6" * 40
        first = self.poll(rt, [review_issue()])
        kwargs = happy_kwargs()
        kwargs["pull"] = dict(kwargs["pull"], head_sha=other)
        kwargs["commit_trees"] = {other: ROOT_TREE}
        second_issue = review_issue(
            902, body="Candidate PR: #395\nCandidate SHA: %s\n" % other)
        second = consumer.poll_once(
            reader=consumer.GitHubIssuesReader(
                token_loader=lambda: TEST_TOKEN,
                opener=ReviewOpener([second_issue], **kwargs), api_base=FAKE_API),
            runtime_factory=lambda: rt, environ=ENABLED)
        self.assertNotEqual(first["review_enqueued"][0]["runtime_task_id"],
                            second["review_enqueued"][0]["runtime_task_id"])
        self.assertEqual(rt.task_count(), 2)

    def test_a_refused_review_issue_creates_nothing(self):
        rt = self.runtime()
        result = self.poll(rt, [review_issue(title="C13 · REVIEW · not yours to make")])
        self.assertEqual(result["review_planned"], [])
        self.assertEqual(result["review_enqueued"], [])
        self.assertEqual(result["review_refused"][0]["reason"],
                         "REVIEW_TITLE_CELL_IS_NOT_THE_REVIEW_CELL")
        self.assertEqual(rt.task_count(), 0)


# ================================================== G: the Builder path is untouched
class G_TheBuilderPathIsUntouched(unittest.TestCase):
    def poll(self, listing, *, source_head):
        return consumer.poll_once(reader=consumer.GitHubIssuesReader(
            token_loader=lambda: TEST_TOKEN,
            opener=ReviewOpener(listing, source_head=source_head), api_base=FAKE_API),
            environ={})

    def test_historical_79_88_are_still_stale_refused(self):
        result = self.poll(load_fixture(),
                           source_head="e4076276d70058d16f68fda5db047161ca6ef4cc")
        self.assertEqual(result["planned"], [])
        stale = [entry for entry in result["refused"] if entry["issue_number"] == 79]
        self.assertEqual(stale[0]["reason"], "INGRESS_SOURCE_ANCHOR_NOT_CURRENT")
        self.assertEqual(stale[0]["parsed_source_anchor"], FIXTURE_SOURCE)
        # ...and no review work was invented out of them.
        self.assertEqual(result["review_candidates"], 0)
        self.assertEqual(result["review_planned"], [])

    def test_a_builder_issue_written_against_main_is_still_planned(self):
        result = self.poll(load_fixture(), source_head=FIXTURE_SOURCE)
        self.assertIn(79, [entry["issue_number"] for entry in result["planned"]])
        self.assertEqual([entry for entry in result["refused"]
                          if entry["issue_number"] == 79], [])
        # This poll runs with the switch off, which is the shadow configuration: the plan is
        # reported and nothing is enqueued, exactly as before this round.
        self.assertEqual(result["status"], "DISABLED")
        self.assertFalse(result["enabled"])
        self.assertEqual(result["review_candidates"], 0)

    def test_the_builder_keys_mean_what_they_always_meant(self):
        # A listing with one review issue and no Builder candidate reports an EMPTY Builder
        # side and a populated review side: the counts never mix the two families.
        result = self.poll([review_issue()], source_head=FIXTURE_SOURCE)
        self.assertEqual(result["candidates"], 0)
        self.assertEqual(result["planned"], [])
        self.assertEqual(result["review_candidates"], 1)
        self.assertEqual(len(result["review_planned"]), 1)

    def test_an_empty_listing_is_still_not_an_error(self):
        result = consumer.poll_once(
            reader=consumer.GitHubIssuesReader(
                token_loader=lambda: TEST_TOKEN,
                opener=ReviewOpener([], source_head=FIXTURE_SOURCE), api_base=FAKE_API),
            environ=ENABLED)
        self.assertEqual(result["status"], "NO_CANDIDATE")
        self.assertEqual(result["review_candidates"], 0)
        self.assertEqual(result["planned"], [])


# ================================================== H: read-only, bounded, no store
class H_ReadOnlyAndBounded(unittest.TestCase):
    def test_the_ingress_has_no_http_and_no_write_verb_of_its_own(self):
        source = REVIEW_SOURCE.read_text(encoding="utf-8")
        for forbidden in ("urllib", "requests", "http.client", "socket", "subprocess",
                          '"POST"', '"PATCH"', '"PUT"', '"DELETE"', "/comments"):
            with self.subTest(token=forbidden):
                self.assertNotIn(forbidden, source)

    def test_the_ingress_keeps_no_state_and_opens_nothing(self):
        source = REVIEW_SOURCE.read_text(encoding="utf-8")
        for forbidden in ("sqlite3", "open(", "pickle", "shelve", "pathlib", ".write("):
            with self.subTest(token=forbidden):
                self.assertNotIn(forbidden, source)

    def test_the_consumer_transport_is_still_get_only(self):
        source = (HERE / "c1_issue_consumer.py").read_text(encoding="utf-8")
        for forbidden in ('"POST"', '"PATCH"', '"PUT"', '"DELETE"', "/comments"):
            with self.subTest(token=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertIn('method="GET"', source)

    def test_the_poll_does_not_read_more_per_review_issue_than_it_needs(self):
        opener = ReviewOpener([review_issue()], **happy_kwargs())
        consumer.poll_once(reader=consumer.GitHubIssuesReader(
            token_loader=lambda: TEST_TOKEN, opener=opener, api_base=FAKE_API),
            environ={})
        self.assertEqual(opener.verbs, ["GET"])
        candidate_paths = [call["url"].split("?")[0] for call in opener.calls
                           if "/pulls/" in call["url"]
                           or "/git/trees/" in call["url"]
                           or "/compare/" in call["url"]
                           or (consumer.COMMIT_PATH.split("%")[0] in call["url"]
                               and not call["url"].endswith("/commits/main"))]
        # PULL, PULL_FILES, COMMIT, TREE, COMPARE. The compare is the extra read that proves
        # the frozen base is an ancestor of the frozen commit - one GET, and no store.
        self.assertEqual(len(candidate_paths), 5, candidate_paths)

    def test_the_machine_scope_is_the_candidates_own_tests(self):
        reader = happy_reader(files=[
            {"filename": "application/tests/workbench/test_b.py", "status": "added"},
            {"filename": "application/tests/workbench/test_a.py", "status": "modified"},
            {"filename": "application/tests/workbench/test_gone.py", "status": "removed"},
            {"filename": "application/src/go_hotel/main.py", "status": "modified"},
            {"filename": "application/tests/notes.md", "status": "added"}])
        plan = ingress.plan_review_ingress(review_issue(), reader=reader, environ=ENABLED)
        self.assertEqual(plan["machine_inventory"],
                         "application/tests/workbench/test_a.py "
                         "application/tests/workbench/test_b.py")
        self.assertEqual(plan["machine_inventory_source"], "candidate_changed_tests")

    def test_a_path_that_is_not_a_plain_test_path_never_reaches_the_field(self):
        # The value is interpolated into a shell command by the C13 workflow, so anything
        # that is not provably a path under application/tests is dropped.
        reader = happy_reader(files=[
            {"filename": "application/tests/a.py; curl attacker", "status": "added"},
            {"filename": "application/tests/$(whoami).py", "status": "added"},
            {"filename": "application/tests/ok.py", "status": "added"}])
        plan = ingress.plan_review_ingress(review_issue(), reader=reader, environ=ENABLED)
        self.assertEqual(plan["machine_inventory"], "application/tests/ok.py")

    def test_a_candidate_with_no_tests_falls_back_to_the_cells_default(self):
        reader = happy_reader(files=[{"filename": "application/src/x.py", "status": "modified"}])
        plan = ingress.plan_review_ingress(review_issue(), reader=reader, environ=ENABLED)
        self.assertIsNone(plan["machine_inventory"])
        self.assertEqual(plan["machine_inventory_source"], "workflow_default")
        self.assertNotIn("machine_inventory", plan["would_enqueue"]["payload"])

    def test_an_unreadable_file_list_does_not_block_the_round(self):
        class NoFiles(FakeReader):
            def read_pull_files(self, number):
                raise contract.Refused("GITHUB_HTTP_403")

        plan = ingress.plan_review_ingress(
            review_issue(),
            reader=NoFiles(pull=happy_reader().pull, commit_trees={CANDIDATE: ROOT_TREE},
                           trees={ROOT_TREE: [{"path": "application", "mode": "040000",
                                               "type": "tree", "sha": CANDIDATE_TREE}]}),
            environ=ENABLED)
        self.assertIsNone(plan["machine_inventory"])


# ======================================== I: U6 and the retired entry point are untouched
class I_U6AndLegacyAreUntouched(unittest.TestCase):
    def test_the_review_ingress_does_not_touch_the_solution_leak_gate(self):
        source = REVIEW_SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("solution_leak_gate", source)
        self.assertNotIn("deepseek", source.lower())

    def test_the_gate_is_still_a_disabled_bypass(self):
        import c1_solution_leak_gate as gate

        record = gate.evaluate(objective="anything", scope="anything")
        self.assertEqual(record["decision"], "PASS")
        self.assertEqual(record["reason"], "GATE_DISABLED")
        self.assertFalse(record["reviewed"])
        self.assertFalse(record["model_called"])

    def test_the_ingress_cannot_produce_a_retired_kind(self):
        source = REVIEW_SOURCE.read_text(encoding="utf-8")
        for forbidden in ("AI_WORK_V1", "AI_TASK_V1", "RUNTIME_PROBE", "AI_GHAW_HELLO_V1",
                          "GHAW_BUILDER_V1"):
            with self.subTest(token=forbidden):
                self.assertNotIn(forbidden, source)

    def test_no_legacy_worker_became_reachable(self):
        # The retired Responses worker's kinds have no producer in the channel's ingress
        # pair, which is what keeps it retired - and "producer" is a property of what the
        # modules enqueue, not of the words in their docstrings (one of them names the
        # retired kinds precisely to say it does not produce them).
        import c1_issue_ingress

        self.assertEqual(c1_issue_ingress.INGRESS_KIND, contract.GHAW_BUILDER_KIND)
        self.assertEqual(ingress.REVIEW_INGRESS_KIND, contract.C14_REVIEW_KIND)
        produced = (c1_issue_ingress.INGRESS_KIND, ingress.REVIEW_INGRESS_KIND)
        self.assertNotIn("AI_WORK_V1", produced)
        self.assertNotIn("AI_TASK_V1", produced)
        self.assertNotIn("RUNTIME_PROBE", produced)
        # The review module itself never names them at all.
        source = REVIEW_SOURCE.read_text(encoding="utf-8")
        for forbidden in ("AI_WORK_V1", "AI_TASK_V1"):
            with self.subTest(token=forbidden):
                self.assertNotIn(forbidden, source)


# ======================= J: a corrected review is a NEW round, and only a human can say so
class J_ARoundCanBeRaisedOnlyByRevision(Case):
    """`Review revision: n` is the human's statement that a round's INPUTS changed.

    The failure it answers is real and has no other answer: C14 legitimately returns FAIL,
    the FAIL is about the pull request's DESCRIPTION rather than its code, a human corrects
    the description - and the issue number and the candidate SHA are both unchanged, so the
    derived identity still addresses the round that already ran. Without a revision, the
    corrected review cannot exist at all.

    What must NOT change: revision 1 is the identity this channel has always derived, a
    round is still one attempt, and nothing but an Owner editing the issue may raise it.
    """

    def body(self, revision=None, sha=CANDIDATE, pr=PR_NUMBER):
        text = "Candidate PR: #%d\nCandidate SHA: %s\n" % (pr, sha)
        if revision is not None:
            text += "Review revision: %s\n" % revision
        return text

    def plan_for(self, body, *, issue_number=ISSUE_NUMBER, **reader_over):
        return ingress.plan_review_ingress(
            review_issue(issue_number, body=body),
            reader=happy_reader(**reader_over), environ=ENABLED)

    def poll(self, rt, listing):
        return consumer.poll_once(
            reader=consumer.GitHubIssuesReader(
                token_loader=lambda: TEST_TOKEN,
                opener=ReviewOpener(listing, **happy_kwargs()), api_base=FAKE_API),
            runtime_factory=lambda: rt, environ=ENABLED)

    def identities(self, plan):
        payload = plan["would_enqueue"]["payload"]
        return {
            "ledger_round_id": plan["ledger_round_id"],
            "c14_task_id": payload["c14_task_id"],
            "c13_task_id": payload["c13_task_id"],
            "review_request_id": payload["review_request_id"],
            "idempotency_key": plan["would_enqueue"]["idempotency_key"],
            "external_task_id": payload["external_task_id"],
        }

    # ------------------------------------------------------------ compatibility (1-3)
    def test_an_absent_line_is_revision_one_and_byte_identical_to_history(self):
        # The compatibility rule the whole design turns on: the identity this ingress
        # produced before the revision existed must be produced unchanged. `main` derives it
        # from `review_round_identity(issue, sha)` with no third argument, so that call IS
        # the historical answer and this compares against it rather than restating a literal.
        plan = self.plan_for(self.body())
        historical = contract.review_round_identity(ISSUE_NUMBER, CANDIDATE)
        self.assertEqual(plan["ledger_round_id"], "FORMAL-REVIEW-I901-%s" % SHORT)
        self.assertEqual(plan["ledger_round_id"], historical["ledger_round_id"])
        self.assertEqual(plan["would_enqueue"]["payload"]["c14_task_id"],
                         historical["c14_task_id"])
        self.assertEqual(plan["would_enqueue"]["payload"]["c13_task_id"],
                         historical["c13_task_id"])
        self.assertEqual(plan["review_revision"], 1)
        # "no revision suffix" is a regex rather than `"-R" not in ...`: the historical id
        # ends in `-REVIEW`, which contains those two characters by accident.
        self.assertIsNone(re.search(r"-R[0-9]+$", plan["ledger_round_id"]))

    def test_stating_revision_one_is_the_same_as_not_stating_it(self):
        absent = self.plan_for(self.body())
        stated = self.plan_for(self.body(revision="1"))
        self.assertEqual(stated, absent)
        self.assertEqual(stated["review_revision"], 1)

    # --------------------------------------------------------------- new round (4-6)
    def test_the_same_issue_and_candidate_at_a_new_revision_is_a_new_round(self):
        first = self.plan_for(self.body())
        second = self.plan_for(self.body(revision="2"))
        self.assertNotEqual(first["ledger_round_id"], second["ledger_round_id"])
        self.assertNotEqual(first["would_enqueue"]["idempotency_key"],
                            second["would_enqueue"]["idempotency_key"])
        self.assertNotEqual(first["payload_sha256"], second["payload_sha256"])

    def test_revision_two_is_the_historical_id_with_an_r2_suffix(self):
        plan = self.plan_for(self.body(revision="2"))
        self.assertEqual(plan["ledger_round_id"], "FORMAL-REVIEW-I901-%s-R2" % SHORT)
        self.assertEqual(plan["review_revision"], 2)

    def test_every_derived_name_of_r2_differs_from_r1(self):
        first = self.identities(self.plan_for(self.body()))
        second = self.identities(self.plan_for(self.body(revision="2")))
        for key in ("ledger_round_id", "c14_task_id", "c13_task_id",
                    "review_request_id", "idempotency_key", "external_task_id"):
            with self.subTest(key=key):
                self.assertNotEqual(first[key], second[key])
        # ...and R2 is still the SAME candidate, tree and inventory: the revision changes
        # which round this is, never what is being reviewed.
        p1 = self.plan_for(self.body())["would_enqueue"]["payload"]
        p2 = self.plan_for(self.body(revision="2"))["would_enqueue"]["payload"]
        for key in ("candidate_sha", "application_tree", "issue_number", "cell_id",
                    "machine_inventory", "frozen_base", "schema_version"):
            with self.subTest(key=key):
                self.assertEqual(p1.get(key), p2.get(key))

    def test_r2_is_no_more_than_the_derived_names_of_r1(self):
        # The design constraint, stated as a test: nothing about the round's identity is a
        # second algorithm. Every R2 name is R1's name with the revision appended to the
        # round id the contract already produces.
        r1 = self.identities(self.plan_for(self.body()))
        r2 = self.identities(self.plan_for(self.body(revision="2")))
        for key in ("ledger_round_id", "c14_task_id", "c13_task_id"):
            with self.subTest(key=key):
                self.assertEqual(r2[key], r1[key].replace(SHORT, SHORT + "-R2"))
        self.assertEqual(r2["review_request_id"],
                         contract.review_request_id(CANDIDATE, r2["ledger_round_id"]))

    # ---------------------------------------------------------------- repeat is free (7)
    def test_repeated_polling_of_r2_is_still_one_paid_task(self):
        rt = self.runtime()
        ids = {self.poll(rt, [review_issue(body=self.body(revision="2"))])
               ["review_enqueued"][0]["runtime_task_id"] for _ in range(10)}
        self.assertEqual(len(ids), 1, ids)
        self.assertEqual(rt.task_count(), 1)
        row = rt.rows()[0]
        self.assertEqual(row[2], contract.C14_REVIEW_KIND)
        self.assertEqual(row[5], ingress.REVIEW_INGRESS_MAX_ATTEMPTS)
        self.assertIn("-R2-C14", row[4])

    # ------------------------------------------------------------------ invalid (8-12)
    def test_invalid_revisions_are_refused(self):
        for text, why in (("0", "zero is not a revision"),
                          ("-1", "no negative revisions"),
                          ("-3", "no negative revisions"),
                          ("two", "not a number"),
                          ("2.5", "not an integer"),
                          ("1e2", "not a plain integer"),
                          ("two 2", "not a plain integer"),
                          ("", "an empty value is not a revision"),
                          ("100", "above MAX_REVIEW_REVISION")):
            with self.subTest(value=text, why=why):
                with self.assertRaises(contract.Refused) as caught:
                    self.plan_for(self.body(revision=text))
                self.assertEqual(caught.exception.reason, "REVIEW_REVISION_INVALID")

    def test_a_revision_stated_twice_and_disagreeing_is_ambiguous_not_resolved(self):
        body = (self.body() + "Review revision: 2\nReview revision: 3\n")
        with self.assertRaises(contract.Refused) as caught:
            self.plan_for(body)
        self.assertEqual(caught.exception.reason, "REVIEW_REVISION_AMBIGUOUS")

    def test_a_revision_stated_twice_with_one_value_is_one_revision(self):
        # The same convention the candidate lines already hold: stated twice, agreeing, is
        # a value stated twice rather than an ambiguity.
        body = self.body() + "Review revision: 2\nReview revision: 2\n"
        self.assertEqual(self.plan_for(body)["review_revision"], 2)

    def test_explicit_revision_one_and_explicit_revision_two_are_both_accepted(self):
        self.assertEqual(self.plan_for(self.body(revision="1"))["review_revision"], 1)
        self.assertEqual(self.plan_for(self.body(revision="2"))["review_revision"], 2)

    def test_the_upper_bound_is_a_bound_and_not_an_unbounded_suffix(self):
        self.assertEqual(self.plan_for(self.body(revision="99"))["review_revision"], 99)
        with self.assertRaises(contract.Refused):
            self.plan_for(self.body(revision="100"))

    def test_a_malformed_revision_never_reaches_a_runtime(self):
        rt = self.runtime()
        result = self.poll(rt, [review_issue(body=self.body(revision="0"))])
        self.assertEqual(result["review_planned"], [])
        self.assertEqual(result["review_enqueued"], [])
        self.assertEqual(result["review_refused"][0]["reason"], "REVIEW_REVISION_INVALID")
        self.assertEqual(rt.task_count(), 0)

    # ------------------------------------------------- the old round is never touched (16)
    def test_raising_the_revision_leaves_r1_byte_identical_and_creates_only_r2(self):
        rt = self.runtime()
        first = self.poll(rt, [review_issue(body=self.body())])
        r1_id = first["review_enqueued"][0]["runtime_task_id"]
        before = rt.rows()
        self.assertEqual(len(before), 1)

        second = self.poll(rt, [review_issue(body=self.body(revision="2"))])
        r2_id = second["review_enqueued"][0]["runtime_task_id"]
        self.assertNotEqual(r1_id, r2_id)

        rows = rt.rows()
        self.assertEqual(rt.task_count(), 2, "one new round, not a rewrite of the old one")
        self.assertEqual(rows[0], before[0], "R1's row is byte-identical, not updated")
        self.assertEqual(rows[0][0], r1_id)
        self.assertIn("FORMAL-REVIEW-I901-%s-C14" % SHORT, rows[0][4])
        self.assertIn("FORMAL-REVIEW-I901-%s-R2-C14" % SHORT, rows[1][4])

    def test_a_round_is_still_exactly_one_attempt_whatever_its_revision(self):
        for revision in (None, "1", "2", "99"):
            with self.subTest(revision=revision):
                rt = self.runtime()
                self.poll(rt, [review_issue(body=self.body(revision=revision))])
                self.assertEqual(rt.rows()[0][5], 1)

    # ------------------------------------------- the revision is the human's, not the code's
    def test_the_revision_marker_is_read_in_exactly_one_place(self):
        # A revision a second module could also read is a second answer to "which round is
        # this". The literal lives in the parser's marker constant and nowhere else.
        readers = sorted(path.name for path in HERE.glob("c1_*.py")
                         if ingress.REVIEW_REVISION_MARKER in
                         path.read_text(encoding="utf-8"))
        self.assertEqual(readers, ["c1_review_issue_ingress.py"])

    def test_nothing_in_the_channel_may_raise_a_revision_by_itself(self):
        # A revision that a failed verdict, a retry counter or a timer could raise would be
        # a retry loop wearing a round's name. Nothing derives one either: the contract takes
        # it as an argument and defaults it to the historical round, and the bound is one
        # constant rather than a value a caller may pick.
        for path in sorted(HERE.glob("c1_*.py")):
            source = path.read_text(encoding="utf-8")
            for token in ("revision + 1", "revision += 1", "review_revision + 1"):
                with self.subTest(source=path.name, token=token):
                    self.assertNotIn(token, source)
        holders = sorted(path.name for path in HERE.glob("c1_*.py")
                         if "MAX_REVIEW_REVISION" in path.read_text(encoding="utf-8"))
        self.assertEqual(holders, ["c1_execution_contract.py"])
        import inspect

        parameter = inspect.signature(
            contract.review_round_identity).parameters["revision"]
        self.assertIs(parameter.default, 1)
        self.assertIsNone(getattr(ingress, "next_revision", None))

    def test_the_revision_is_not_a_payload_field(self):
        # No schema change, no new DB column: the revision is carried by the round id, which
        # is already in the payload. A payload field would be a second answer to "which
        # round is this", and the schema would have to version for it.
        payload = self.plan_for(self.body(revision="2"))["would_enqueue"]["payload"]
        self.assertNotIn("review_revision", payload)
        self.assertNotIn("revision", payload)
        contract.validate_review_task_payload(payload, allowed_owner_cs=("C14",))
        self.assertEqual(contract.REVIEW_PAYLOAD_SCHEMA_VERSION, 1)

    def test_the_revision_does_not_touch_the_frozen_candidate_reads(self):
        # Raising a revision must not turn into a heavier requirement: the reads are the
        # same five GETs, and the frozen base is the same base, at any revision.
        r1 = happy_reader()
        r2 = happy_reader()
        first = ingress.plan_review_ingress(review_issue(body=self.body()), reader=r1,
                                            environ=ENABLED)
        second = ingress.plan_review_ingress(review_issue(body=self.body(revision="2")),
                                             reader=r2, environ=ENABLED)
        self.assertEqual([c[0] for c in r1.calls], [c[0] for c in r2.calls])
        self.assertEqual(first["would_enqueue"]["payload"]["frozen_base"],
                         second["would_enqueue"]["payload"]["frozen_base"])
        self.assertEqual(len(r2.calls), 5)


if __name__ == "__main__":
    unittest.main()
