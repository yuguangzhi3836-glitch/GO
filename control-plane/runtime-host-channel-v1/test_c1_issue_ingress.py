"""Ingress tests: C01 issue -> GHAW_BUILDER_V1 Runtime call, shadow-only.

Coverage map (the letters are the acceptance cases of the task):

  A  Issue79FixtureIsParsed            the real historical #79 is understood
  B  DuplicateScansAreOneRuntimeTask    same issue scanned N times -> one task
  C  MalformedIssuesAreRefused          missing TASK_ID / objective / scope / anchor
  D  NonC01IssuesAreRefused             another cell, another shape, a PR
  E  DisabledByDefaultEnqueuesNothing   the default state cannot spend anything
  F  EnabledOfflineEnqueuesOnce         enabled + fake Runtime + temporary DB
  G  TheIngressIsStructurallyBounded    imports, signature, and no old executor
  H  SourceFreshnessIsRequired          stale / missing / malformed source is refused

Everything here is offline: no network, no Runtime host, no model call, no GitHub
write. The fixture bodies are the bytes the issues API returns today, and their
SHA256s are pinned below so a hand-edited fixture cannot pass as real input.
"""
import ast
import inspect
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import c1_execution_contract as contract  # noqa: E402
import c1_issue_ingress as ingress  # noqa: E402

INGRESS_SOURCE = HERE / "c1_issue_ingress.py"
FIXTURE = HERE / "issue_fixtures" / "real_c01_issues.json"
ENABLED = {ingress.INGRESS_ENABLED_ENV: "true"}

# The source anchor every captured fixture body carries. It is passed as the CURRENT source
# by the tests that are about parsing, identity or the enable switch - which is precisely
# the situation those issues were in when they were written: back then it was current. The
# tests that are about freshness pass a different value on purpose, and class H is where
# that lives.
FIXTURE_SOURCE_ANCHOR = "8ffcde66d36c1bbf849218529ef015f6e81725af"
# A stand-in for "main has moved on since those issues were written". It is a real commit
# from this repository's history, not an invented digest, so a failure message shows two
# plausible values rather than one that is obviously fake.
CURRENT_SOURCE_ANCHOR = "e4076276d70058d16f68fda5db047161ca6ef4cc"

# Captured at the same time as the fixture; a transcription or edit changes them.
REAL_BODY_SHA256 = {
    79: "1335fdc53928a2aa9fd42d6e3b40e188c2bb07d4a76d94586e9f99914b4daaeb",
    116: "4fbefcd452502e62f297afd22d6d8c5fe420f3f68abea946337d1844416d51c8",
    170: "106de13708cfa0a92f0be06fefbd0c4fafeefa4a4858c918bf296c677dee57a3",
}


def load_fixture() -> dict:
    with open(FIXTURE, encoding="utf-8") as handle:
        document = json.load(handle)
    return {issue["number"]: issue for issue in document["issues"]}


ISSUES = load_fixture()


class RuntimeDouble:
    """A stand-in for the Runtime kernel's `enqueue`.

    It mirrors the one behaviour the ingress depends on: `idempotency_key` is UNIQUE,
    so asking again with the same key returns the existing task id instead of creating
    a second task. It is backed by a real sqlite file, so "exactly one Runtime task"
    is a row count rather than an in-memory claim - and the signature matches the
    kernel's (`enqueue(owner_c, kind, payload, *, created_by_c, priority,
    available_at, max_attempts, idempotency_key)`), so the ingress is exercised against
    the call it will really make.
    """

    def __init__(self, path):
        self.path = str(path)
        self.enqueue_calls = 0
        self._db = sqlite3.connect(self.path)
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS tasks (
                   task_id TEXT PRIMARY KEY,
                   owner_c TEXT NOT NULL,
                   kind TEXT NOT NULL,
                   payload_json TEXT NOT NULL,
                   idempotency_key TEXT UNIQUE,
                   max_attempts INTEGER NOT NULL,
                   status TEXT NOT NULL)""")

    def enqueue(self, owner_c, kind, payload, *, created_by_c=None, priority=100,
                available_at=None, max_attempts=5, idempotency_key=None):
        self.enqueue_calls += 1
        if idempotency_key is not None:
            row = self._db.execute(
                "SELECT task_id FROM tasks WHERE idempotency_key = ?",
                (idempotency_key,)).fetchone()
            if row is not None:
                return row[0]
        task_id = "rt_" + uuid.uuid4().hex
        self._db.execute(
            "INSERT INTO tasks VALUES (?,?,?,?,?,?,?)",
            (task_id, owner_c, kind, contract.canonical(payload), idempotency_key,
             max_attempts, "QUEUED"))
        self._db.commit()
        return task_id

    def task_count(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

    def rows(self):
        return self._db.execute(
            "SELECT task_id, owner_c, kind, payload_json, idempotency_key,"
            " max_attempts FROM tasks ORDER BY rowid").fetchall()

    def close(self):
        self._db.close()


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="c01-ingress-")
        self.addCleanup(self._tmp.cleanup)
        self.runtime = RuntimeDouble(Path(self._tmp.name) / "runtime.db")
        # Registered after the temporary directory, so it runs before it: on Windows an
        # open sqlite handle keeps the file locked and the cleanup would fail.
        self.addCleanup(self.runtime.close)

    def issue(self, number):
        return json.loads(json.dumps(ISSUES[number]))

    def plan(self, issue, *, environ=None, current=FIXTURE_SOURCE_ANCHOR):
        """Plan one issue, supplying the current source unless a test overrides it."""
        return ingress.plan_ingress(issue, current_source_anchor=current,
                                    environ={} if environ is None else environ)

    def refused_reason(self, issue, environ=None, current=FIXTURE_SOURCE_ANCHOR):
        with self.assertRaises(contract.Refused) as caught:
            self.plan(issue, environ=environ, current=current)
        return caught.exception.reason

    def enqueue(self, issue, *, environ=ENABLED, current=FIXTURE_SOURCE_ANCHOR):
        return ingress.ingest(issue, current_source_anchor=current,
                              runtime=self.runtime, environ=environ)


# ------------------------------------------------------------------ A
class Issue79FixtureIsParsed(Case):
    """The owner's real historical C01 task is understood as it stands."""

    def test_the_fixture_is_the_real_captured_text(self):
        for number, digest in REAL_BODY_SHA256.items():
            with self.subTest(issue=number):
                self.assertEqual(
                    contract.sha256_hex(ISSUES[number]["body"]), digest)

    def test_issue_79_parses_to_the_expected_facts(self):
        parsed = ingress.parse_c01_issue(self.issue(79))
        self.assertEqual(parsed["issue_number"], 79)
        self.assertEqual(parsed["cell_id"], "C1")
        self.assertEqual(parsed["external_task_id"], "V70-R3-C01-01")
        self.assertEqual(parsed["source_anchor"],
                         "8ffcde66d36c1bbf849218529ef015f6e81725af")
        self.assertEqual(parsed["scope"], "mixed hotel funds read-only diagnosis")
        self.assertTrue(parsed["objective"].startswith(
            "source-bound read-only diagnosis of mixed hotel funds"))
        self.assertEqual(set(parsed), set(ingress.REQUIRED_FIELDS))

    def test_issue_79_plans_exactly_the_expected_runtime_call(self):
        plan = self.plan(self.issue(79), environ={})
        self.assertFalse(plan["enabled"])
        self.assertFalse(plan["enqueued"])
        self.assertEqual(plan["issue_number"], 79)
        call = plan["would_enqueue"]
        self.assertEqual(call["owner_c"], "C1")
        self.assertEqual(call["kind"], "GHAW_BUILDER_V1")
        self.assertEqual(call["max_attempts"], 1)
        self.assertEqual(call["idempotency_key"], "c1-ghaw-builder-v1:C1:V70-R3-C01-01")
        payload = call["payload"]
        self.assertEqual(payload["cell_id"], "C1")
        self.assertEqual(payload["external_task_id"], "V70-R3-C01-01")
        self.assertEqual(payload["issue_number"], 79)
        self.assertEqual(payload["source_anchor"],
                         "8ffcde66d36c1bbf849218529ef015f6e81725af")
        # What the plan hands over is what the merged contract accepts.
        self.assertEqual(contract.validate_task_payload(payload), payload)
        self.assertEqual(plan["payload_sha256"],
                         contract.sha256_hex(contract.canonical(payload)))

    def test_the_successor_issue_shape_is_understood_too(self):
        # #116 is closed today, so the ingress refuses it as it stands; the *shape*
        # (a `Successor task:` objective and a `Canonical lineage:` anchor) parses.
        successor = self.issue(116)
        self.assertEqual(
            self.refused_reason(successor), "ISSUE_NOT_OPEN")
        successor["state"] = "open"
        parsed = ingress.parse_c01_issue(successor)
        self.assertEqual(parsed["external_task_id"], "V70-R3-C01-02")
        self.assertEqual(parsed["source_anchor"],
                         "8ffcde66d36c1bbf849218529ef015f6e81725af")
        self.assertTrue(parsed["objective"].startswith("deepen hotel-funds integrity"))

    def test_a_body_without_an_explicit_anchor_line_is_refused_not_guessed(self):
        # #170's anchor only appears as a *predecessor candidate* in prose. Reading
        # that as this task's own source would be inference, so it is refused.
        changed = self.issue(170)
        self.assertEqual(self.refused_reason(changed), "ISSUE_NOT_OPEN")
        changed["state"] = "open"
        self.assertEqual(self.refused_reason(changed), "INGRESS_SOURCE_ANCHOR_NOT_FOUND")


# ------------------------------------------------------------------ B
class DuplicateScansAreOneRuntimeTask(Case):
    """Rescanning the same issue cannot become a second Runtime task."""

    def test_ten_scans_produce_one_identical_runtime_call(self):
        plans = [self.plan(self.issue(79), environ={}) for _ in range(10)]
        self.assertEqual(len({p["payload_sha256"] for p in plans}), 1)
        self.assertEqual(
            len({p["would_enqueue"]["idempotency_key"] for p in plans}), 1)
        self.assertEqual(
            len({p["would_enqueue"]["payload"]["external_task_id"] for p in plans}), 1)

    def test_ten_scans_create_one_row_and_one_task_id(self):
        results = [self.enqueue(self.issue(79)) for _ in range(10)]
        self.assertTrue(all(r["action"] == "ENQUEUED" for r in results))
        self.assertEqual(len({r["runtime_task_id"] for r in results}), 1)
        self.assertEqual(self.runtime.task_count(), 1)
        # The scanner re-asked ten times; the Runtime answered with the same task.
        self.assertEqual(self.runtime.enqueue_calls, 10)
        task_id, owner_c, kind, _, key, max_attempts = self.runtime.rows()[0]
        self.assertEqual(owner_c, "C1")
        self.assertEqual(kind, "GHAW_BUILDER_V1")
        self.assertEqual(key, "c1-ghaw-builder-v1:C1:V70-R3-C01-01")
        self.assertEqual(max_attempts, 1)
        self.assertTrue(task_id.startswith("rt_"))


# ------------------------------------------------------------------ C
class MalformedIssuesAreRefused(Case):
    """A missing field is a refusal, and a refusal is never an enqueue."""

    def _broken(self, mutate):
        issue = self.issue(79)
        mutate(issue)
        return issue

    def test_the_expected_reason_for_each_broken_input(self):
        cases = {
            "ISSUE_TITLE_NOT_THREE_SEGMENTS":
                self._broken(lambda i: i.update(
                    title="C01 · mixed hotel funds read-only diagnosis")),
            "ISSUE_TITLE_TASK_ID_NOT_FOUND":
                self._broken(lambda i: i.update(
                    title="C01 · V70-C01-01 · mixed hotel funds read-only diagnosis")),
            "ISSUE_TITLE_TASK_ID_CELL_MISMATCH":
                self._broken(lambda i: i.update(
                    title="C01 · V70-R3-C02-99 · mixed hotel funds read-only diagnosis")),
            "ISSUE_NUMBER_INVALID":
                self._broken(lambda i: i.pop("number")),
            "INGRESS_OBJECTIVE_NOT_FOUND":
                self._broken(lambda i: i.update(
                    body=i["body"].replace("Task: source-bound", "Note: source-bound"))),
            "INGRESS_OBJECTIVE_EMPTY":
                self._broken(lambda i: i.update(body="Task:\n\nCanonical source: "
                                                     "`main 8ffcde66d36c1bbf849218529ef015f6e81725af`")),
            "INGRESS_SOURCE_ANCHOR_NOT_FOUND":
                self._broken(lambda i: i.update(
                    body=i["body"].replace("Canonical source:", "Background:"))),
            "INGRESS_SOURCE_ANCHOR_AMBIGUOUS":
                self._broken(lambda i: i.update(
                    body=i["body"] + "\nCanonical lineage: also `{0}`\n".format("b" * 40))),
            "ISSUE_BODY_EMPTY":
                self._broken(lambda i: i.update(body="")),
            "ISSUE_IS_A_PULL_REQUEST":
                self._broken(lambda i: i.update(pull_request={"url": "x"})),
            "ISSUE_NOT_OPEN":
                self._broken(lambda i: i.update(state="closed")),
        }
        for expected, issue in cases.items():
            with self.subTest(reason=expected):
                self.assertEqual(self.refused_reason(issue), expected)

    def test_a_64_hex_digest_is_not_accepted_as_an_anchor(self):
        issue = self._broken(lambda i: i.update(
            body="Canonical source: `main {0}`\n\nTask: do the thing.\n".format("a" * 64)))
        self.assertEqual(self.refused_reason(issue), "INGRESS_SOURCE_ANCHOR_NOT_FOUND")

    def test_a_body_that_repeats_the_title_differently_is_refused(self):
        issue = self._broken(lambda i: i.update(
            body=i["body"] + "\nTASK_ID: `V70-R3-C01-09`\n"))
        self.assertEqual(self.refused_reason(issue),
                         "INGRESS_TASK_ID_TITLE_BODY_MISMATCH")
        issue = self._broken(lambda i: i.update(body=i["body"] + "\nCELL_ID: `C02`\n"))
        self.assertEqual(self.refused_reason(issue), "INGRESS_CELL_TITLE_BODY_MISMATCH")

    def test_no_malformed_input_enqueues_anything_even_when_enabled(self):
        broken = [
            self._broken(lambda i: i.update(title="C01 · no task id here")),
            self._broken(lambda i: i.update(body="Task: x")),
            self._broken(lambda i: i.update(state="closed")),
            self._broken(lambda i: i.update(pull_request={})),
        ]
        for issue in broken:
            with self.subTest(issue=issue["number"]):
                with self.assertRaises(contract.Refused):
                    self.enqueue(issue)
        self.assertEqual(self.runtime.enqueue_calls, 0)
        self.assertEqual(self.runtime.task_count(), 0)


# ------------------------------------------------------------------ D
class TheControlOnlyCellsAreRefused(Case):
    """The ingress serves the Builder's cells - C01..C12 - and refuses C13 and C14.

    Those two are the control-only cells: Independent QA/Release and the
    constitutional/legal/regulatory control cell. They are not Builder work, and an issue
    scanner must not be able to turn one into Builder work by titling an issue a certain
    way. The range is not restated here - it is whatever the contract says the Builder
    executor owns - so this class cannot drift from the executor.
    """

    def test_every_builder_cell_is_accepted_and_canonicalised(self):
        for cell in ("C01", "C02", "C09", "C10", "C11", "C12"):
            issue = self.issue(79)
            issue["title"] = "%s · V70-R3-%s-01 · a bounded engineering task" % (cell, cell)
            with self.subTest(cell=cell):
                parsed = ingress.parse_c01_issue(issue)
                self.assertEqual(parsed["cell_id"], contract.canonical_cell_id(cell))

    def test_a_control_only_cell_is_refused(self):
        for cell in ("C13", "C14"):
            issue = self.issue(79)
            issue["title"] = "%s · V70-R3-%s-01 · not a builder task" % (cell, cell)
            with self.subTest(cell=cell):
                self.assertEqual(self.refused_reason(issue),
                                 "INGRESS_CELL_NOT_OWNED_BY_BUILDER_EXECUTOR")

    def test_a_cell_outside_the_kernel_range_is_refused(self):
        # C00/C15/C99 are well-formed two-digit cells the kernel does not have, so they
        # reach the SHARED canonicaliser and are refused there - by the same parser every
        # other consumer uses, not by a private list kept in this file.
        for cell in ("C00", "C15", "C99"):
            issue = self.issue(79)
            issue["title"] = "%s · V70-R3-%s-01 · does not exist" % (cell, cell)
            with self.subTest(cell=cell):
                self.assertEqual(self.refused_reason(issue),
                                 "CELL_ID_NOT_A_KNOWN_RESPONSIBILITY_DOMAIN")

    def test_a_one_digit_zero_cell_cannot_even_form_a_title(self):
        # "C0" passes the title's shape regex, but no legal task id can carry it, so the
        # title gate refuses it before the canonicaliser is asked. Two independent
        # refusals for the same non-cell is the point of having both.
        issue = self.issue(79)
        issue["title"] = "C0 · V70-R3-C00-01 · malformed"
        self.assertEqual(self.refused_reason(issue),
                         "ISSUE_TITLE_TASK_ID_CELL_MISMATCH")

    def test_the_other_title_shape_used_by_this_tracker_is_refused(self):
        # e.g. "V70-R4-C05-01 — bind FAILED reconciliation to current UNKNOWN episode"
        issue = self.issue(79)
        issue["title"] = ("V70-R4-C05-01 — bind FAILED reconciliation to current "
                          "UNKNOWN episode")
        self.assertEqual(self.refused_reason(issue), "ISSUE_TITLE_NOT_THREE_SEGMENTS")

    def test_none_of_them_enqueues(self):
        for title in ("C13 · V70-R3-C13-01 · not a builder task",
                      "C14 · V70-R3-C14-01 · not a builder task",
                      "C15 · V70-R3-C15-01 · does not exist",
                      "V70-R4-C05-01 — bind FAILED reconciliation"):
            issue = self.issue(79)
            issue["title"] = title
            with self.assertRaises(contract.Refused):
                self.enqueue(issue)
        self.assertEqual(self.runtime.task_count(), 0)


# ------------------------------------------------------------------ E
class DisabledByDefaultEnqueuesNothing(Case):
    """The default state reads and plans, and cannot write anywhere."""

    def test_only_the_literal_true_enables_it(self):
        for value in ("true", "TRUE", " True ", "tRuE"):
            with self.subTest(value=value):
                self.assertTrue(ingress.ingress_enabled({ingress.INGRESS_ENABLED_ENV: value}))
        for value in ("", " ", "false", "1", "yes", "on", "ture", "true;"):
            with self.subTest(value=value):
                self.assertFalse(ingress.ingress_enabled({ingress.INGRESS_ENABLED_ENV: value}))

    def test_the_real_process_environment_is_disabled_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ingress.INGRESS_ENABLED_ENV, None)
            self.assertFalse(ingress.ingress_enabled())
            plan = self.plan(self.issue(79))
            self.assertEqual(plan["action"], "DISABLED")
            self.assertFalse(plan["enabled"])
            # A disabled ingress still computes the task it would create.
            self.assertEqual(plan["would_enqueue"]["kind"], "GHAW_BUILDER_V1")
            result = self.enqueue(self.issue(79), environ={})
            self.assertEqual(result["action"], "DISABLED")
            self.assertFalse(result["enqueued"])

    def test_disabled_ingest_writes_nothing_even_handed_a_runtime(self):
        for value in ("", "false", "1", "yes"):
            with self.subTest(value=value):
                result = self.enqueue(self.issue(79),
                                      environ={ingress.INGRESS_ENABLED_ENV: value})
                self.assertEqual(result["action"], "DISABLED")
                self.assertNotIn("runtime_task_id", result)
        self.assertEqual(self.runtime.enqueue_calls, 0)
        self.assertEqual(self.runtime.task_count(), 0)

    def test_planning_cannot_enqueue_by_construction(self):
        # The planning function takes no Runtime at all, so no argument can reach
        # enqueue through it.
        self.assertNotIn("runtime", inspect.signature(ingress.plan_ingress).parameters)


# ------------------------------------------------------------------ F
class EnabledOfflineEnqueuesOnce(Case):
    """Enabled, with a fake Runtime and a temporary DB: exactly one task."""

    def test_enabled_ingest_enqueues_the_planned_call(self):
        result = self.enqueue(self.issue(79))
        self.assertEqual(result["action"], "ENQUEUED")
        self.assertTrue(result["enqueued"])
        self.assertEqual(result["runtime_task_id"],
                         self.runtime.rows()[0][0])
        self.assertEqual(self.runtime.enqueue_calls, 1)
        self.assertEqual(self.runtime.task_count(), 1)
        task_id, owner_c, kind, payload_json, key, max_attempts = self.runtime.rows()[0]
        self.assertEqual(owner_c, "C1")
        self.assertEqual(kind, "GHAW_BUILDER_V1")
        self.assertEqual(key, "c1-ghaw-builder-v1:C1:V70-R3-C01-01")
        self.assertEqual(max_attempts, 1)
        # The row holds the validated payload, byte for byte.
        self.assertEqual(payload_json,
                         contract.canonical(result["would_enqueue"]["payload"]))
        self.assertEqual(contract.canonical(json.loads(payload_json)),
                         contract.canonical(result["would_enqueue"]["payload"]))

    def test_enabled_without_a_runtime_is_a_loud_refusal(self):
        with self.assertRaises(contract.Refused) as caught:
            ingress.ingest(self.issue(79),
                           current_source_anchor=FIXTURE_SOURCE_ANCHOR, environ=ENABLED)
        self.assertEqual(caught.exception.reason,
                         "RUNTIME_REQUIRED_WHEN_INGRESS_ENABLED")

    def test_the_cli_prints_a_plan_and_cannot_enqueue(self):
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env[ingress.INGRESS_ENABLED_ENV] = "true"
        for number, expected in ((79, 0), (170, 3)):
            with self.subTest(issue=number):
                done = subprocess.run(
                    [sys.executable, str(INGRESS_SOURCE), "--plan", str(FIXTURE),
                     str(number), FIXTURE_SOURCE_ANCHOR],
                    cwd=str(HERE), env=env, capture_output=True, text=True)
                self.assertEqual(done.returncode, expected, done.stderr)
                if expected == 0:
                    plan = json.loads(done.stdout)
                    self.assertFalse(plan["enqueued"])
                    self.assertEqual(plan["would_enqueue"]["owner_c"], "C1")
                else:
                    self.assertIn("REFUSED ISSUE_NOT_OPEN", done.stdout)


# ------------------------------------------------------------------ G
class TheIngressIsStructurallyBounded(Case):
    """It reaches no old executor, and no part of the C1 channel but the contract."""

    def test_it_imports_the_contract_and_nothing_else_from_the_repository(self):
        tree = ast.parse(INGRESS_SOURCE.read_text(encoding="utf-8"))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.add((node.module or "").split(".")[0])
        self.assertEqual(
            modules, {"__future__", "json", "os", "re", "sys", "c1_execution_contract",
                      "c1_solution_leak_gate"},
            "the ingress must import the shared contract, the U6 gate seam and the "
            "standard library only")

    def test_it_holds_no_reference_to_the_old_c01_executor(self):
        source = INGRESS_SOURCE.read_text(encoding="utf-8")
        for forbidden in ("c1_ai_execution_backend", "c1_dispatch_outbox",
                          "c1_result_pull", "c1_execution_loop", "c1_worker",
                          "workflow_dispatch", "codex", "/root/"):
            with self.subTest(token=forbidden):
                self.assertNotIn(forbidden, source)

    def test_it_does_not_write_evidence_or_open_pull_requests(self):
        # `pull_request` is deliberately absent from this list: the ingress must be
        # able to *recognise* a pull request in order to refuse it.
        source = INGRESS_SOURCE.read_text(encoding="utf-8")
        for forbidden in ("evidence", "actions/runs", "urllib", "subprocess",
                          "socket", "requests."):
            with self.subTest(token=forbidden):
                self.assertNotIn(forbidden, source)

    def test_the_runtime_double_matches_the_kernel_call_the_ingress_makes(self):
        # If the ingress ever calls enqueue with a different shape, this fails here
        # rather than in a live run.
        parameters = inspect.signature(self.runtime.enqueue).parameters
        self.assertEqual(list(parameters)[:3], ["owner_c", "kind", "payload"])
        for name in ("idempotency_key", "max_attempts"):
            self.assertEqual(parameters[name].kind,
                             inspect.Parameter.KEYWORD_ONLY)


# ------------------------------------------------------------------ H
class SourceFreshnessIsRequired(Case):
    """An issue is admitted only against the source the repository is on right now.

    The failure this closes, with the live numbers behind it: on 2026-10-04 the ten open
    owner issues #79-#88 all carried `canonical source: ... 8ffcde66...` while main was
    `e4076276...`. Every one of them parsed, validated against the Builder's own cell range
    and would have enqueued - ten paid engineering executions against a tree none of them
    was written for. Nothing here closes or edits those issues; the ingress simply stops
    agreeing that they are work. The bodies are historical Evidence and stay as they are.
    """

    def retitled(self, *, cell=1, anchor=FIXTURE_SOURCE_ANCHOR, number=79):
        """The real captured body, re-titled for one cell and bound to one anchor.

        Only the title and, when asked for, the commit on the anchor line are rewritten.
        The rest - the anchor label, the objective marker, the provenance lines - is the
        captured text, so this exercises the real shape rather than an invented one.
        """
        issue = self.issue(number)
        issue["title"] = "C%02d · V70-R3-C%02d-01 · a bounded engineering task" % (cell, cell)
        if anchor != FIXTURE_SOURCE_ANCHOR:
            self.assertEqual(issue["body"].count(FIXTURE_SOURCE_ANCHOR), 1)
            issue["body"] = issue["body"].replace(FIXTURE_SOURCE_ANCHOR, anchor)
        return issue

    def test_the_parser_still_understands_the_historical_issue(self):
        # Freshness is an ADMISSION rule, not a parsing rule. Teaching the parser to
        # disown old issues would lose the ability to read them at all - and with it the
        # ability to say WHY one is old.
        parsed = ingress.parse_c01_issue(self.issue(79))
        self.assertEqual(parsed["source_anchor"], FIXTURE_SOURCE_ANCHOR)

    def test_a_historical_issue_is_refused_once_main_has_moved(self):
        with self.assertRaises(ingress.SourceAnchorNotCurrent) as caught:
            self.plan(self.issue(79), current=CURRENT_SOURCE_ANCHOR)
        self.assertEqual(caught.exception.reason, "INGRESS_SOURCE_ANCHOR_NOT_CURRENT")

    def test_the_refusal_carries_the_two_values_it_was_made_of(self):
        with self.assertRaises(ingress.SourceAnchorNotCurrent) as caught:
            self.plan(self.issue(79), current=CURRENT_SOURCE_ANCHOR)
        refusal = caught.exception
        self.assertEqual(refusal.issue_number, 79)
        self.assertEqual(refusal.parsed_source_anchor, FIXTURE_SOURCE_ANCHOR)
        self.assertEqual(refusal.current_source_anchor, CURRENT_SOURCE_ANCHOR)
        # And it is an ordinary refusal, so every existing caller still sees a Refused.
        self.assertIsInstance(refusal, contract.Refused)

    def test_every_cell_is_refused_for_the_same_stale_source(self):
        # The ten historical issues are one per cell and all carry one anchor. Re-titling
        # the real body for each cell exercises exactly that, without inventing ten bodies:
        # whatever the cell, an anchor that is not the current main is refused.
        for cell in range(1, 13):
            with self.subTest(cell=cell):
                self.assertEqual(
                    self.refused_reason(self.retitled(cell=cell),
                                        current=CURRENT_SOURCE_ANCHOR),
                    "INGRESS_SOURCE_ANCHOR_NOT_CURRENT")

    def test_the_disabled_shadow_path_reports_the_same_verdict(self):
        # The shadow poll is what tells an operator a backlog is stale, so it has to reach
        # the same verdict as the live path - the switch changes what happens on a PASS,
        # never what the admission rules are.
        self.assertEqual(
            self.refused_reason(self.issue(79), environ={}, current=CURRENT_SOURCE_ANCHOR),
            "INGRESS_SOURCE_ANCHOR_NOT_CURRENT")

    def test_a_stale_issue_cannot_enqueue_even_when_enabled(self):
        with self.assertRaises(contract.Refused):
            self.enqueue(self.issue(79), current=CURRENT_SOURCE_ANCHOR)
        self.assertEqual(self.runtime.enqueue_calls, 0)
        self.assertEqual(self.runtime.task_count(), 0)

    def test_an_issue_bound_to_the_current_source_is_accepted(self):
        issue = self.retitled(anchor=CURRENT_SOURCE_ANCHOR)
        plan = self.plan(issue, current=CURRENT_SOURCE_ANCHOR)
        self.assertEqual(plan["would_enqueue"]["owner_c"], "C1")
        self.assertEqual(plan["would_enqueue"]["payload"]["source_anchor"],
                         CURRENT_SOURCE_ANCHOR)
        result = self.enqueue(issue, current=CURRENT_SOURCE_ANCHOR)
        self.assertEqual(result["action"], "ENQUEUED")
        self.assertEqual(self.runtime.task_count(), 1)

    def test_the_gate_does_not_enter_the_task_identity(self):
        # Freshness is admission, not a redesign of identity. The same issue, admitted
        # against the same source, derives exactly the key and payload it always did.
        plan = self.plan(self.issue(79))
        self.assertEqual(plan["would_enqueue"]["idempotency_key"],
                         "c1-ghaw-builder-v1:C1:V70-R3-C01-01")
        self.assertEqual(plan["would_enqueue"]["payload"]["source_anchor"],
                         FIXTURE_SOURCE_ANCHOR)
        self.assertEqual(plan["would_enqueue"]["max_attempts"], 1)

    def test_a_missing_current_source_is_refused_not_assumed(self):
        for missing in (None, "", "   "):
            with self.subTest(value=repr(missing)):
                with self.assertRaises(contract.Refused) as caught:
                    ingress.plan_ingress(self.issue(79), current_source_anchor=missing)
                self.assertEqual(caught.exception.reason,
                                 "INGRESS_CURRENT_SOURCE_ANCHOR_INVALID")

    def test_a_malformed_current_source_is_refused(self):
        bad_values = ("not-a-sha", "8ffcde66", FIXTURE_SOURCE_ANCHOR[:-1],
                      FIXTURE_SOURCE_ANCHOR + "0", "0" * 64,
                      "8ffcde66d36c1bbf849218529ef015f6e81725ag", 12345, ["a"] * 40)
        for bad in bad_values:
            with self.subTest(value=repr(bad)):
                with self.assertRaises(contract.Refused) as caught:
                    ingress.plan_ingress(self.issue(79), current_source_anchor=bad)
                self.assertEqual(caught.exception.reason,
                                 "INGRESS_CURRENT_SOURCE_ANCHOR_INVALID")

    def test_a_differently_cased_current_source_is_the_same_commit(self):
        # GitHub always answers in lowercase; accepting another case is normalising one
        # spelling of the same value, not relaxing the comparison, which is still exact.
        plan = self.plan(self.issue(79),
                         current=FIXTURE_SOURCE_ANCHOR.upper())
        self.assertEqual(plan["would_enqueue"]["payload"]["source_anchor"],
                         FIXTURE_SOURCE_ANCHOR)

    def test_the_current_source_is_required_and_has_no_default(self):
        # Structural, and the point of the whole design: an optional parameter with a
        # default would be a gate a live caller could step over by forgetting an argument.
        for function in (ingress.plan_ingress, ingress.ingest):
            with self.subTest(function=function.__name__):
                parameter = inspect.signature(function).parameters["current_source_anchor"]
                self.assertEqual(parameter.kind, inspect.Parameter.KEYWORD_ONLY)
                self.assertIs(parameter.default, inspect.Parameter.empty)

    def test_omitting_the_current_source_is_an_error_not_a_pass(self):
        with self.assertRaises(TypeError):
            ingress.plan_ingress(self.issue(79))
        with self.assertRaises(TypeError):
            ingress.ingest(self.issue(79), runtime=self.runtime, environ=ENABLED)
        self.assertEqual(self.runtime.enqueue_calls, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
