"""Ingress tests: C01 issue -> GHAW_BUILDER_V1 Runtime call, shadow-only.

Coverage map (the letters are the acceptance cases of the task):

  A  Issue79FixtureIsParsed            the real historical #79 is understood
  B  DuplicateScansAreOneRuntimeTask    same issue scanned N times -> one task
  C  MalformedIssuesAreRefused          missing TASK_ID / objective / scope / anchor
  D  NonC01IssuesAreRefused             another cell, another shape, a PR
  E  DisabledByDefaultEnqueuesNothing   the default state cannot spend anything
  F  EnabledOfflineEnqueuesOnce         enabled + fake Runtime + temporary DB
  G  TheIngressIsStructurallyBounded    imports, signature, and no old executor

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

    def refused_reason(self, issue, environ=None):
        with self.assertRaises(contract.Refused) as caught:
            ingress.plan_ingress(issue, environ={} if environ is None else environ)
        return caught.exception.reason


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
        plan = ingress.plan_ingress(self.issue(79), environ={})
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
        plans = [ingress.plan_ingress(self.issue(79), environ={}) for _ in range(10)]
        self.assertEqual(len({p["payload_sha256"] for p in plans}), 1)
        self.assertEqual(
            len({p["would_enqueue"]["idempotency_key"] for p in plans}), 1)
        self.assertEqual(
            len({p["would_enqueue"]["payload"]["external_task_id"] for p in plans}), 1)

    def test_ten_scans_create_one_row_and_one_task_id(self):
        results = [ingress.ingest(self.issue(79), runtime=self.runtime, environ=ENABLED)
                   for _ in range(10)]
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
                    ingress.ingest(issue, runtime=self.runtime, environ=ENABLED)
        self.assertEqual(self.runtime.enqueue_calls, 0)
        self.assertEqual(self.runtime.task_count(), 0)


# ------------------------------------------------------------------ D
class NonC01IssuesAreRefused(Case):
    """The ingress owns C01 and nothing else."""

    def test_another_cell_is_refused(self):
        issue = self.issue(79)
        issue["title"] = "C02 · V70-R3-C02-01 · trusted coupon plan and exact consent"
        self.assertEqual(self.refused_reason(issue), "INGRESS_ISSUE_IS_NOT_C01")

    def test_the_other_title_shape_used_by_this_tracker_is_refused(self):
        # e.g. "V70-R4-C05-01 — bind FAILED reconciliation to current UNKNOWN episode"
        issue = self.issue(79)
        issue["title"] = ("V70-R4-C05-01 — bind FAILED reconciliation to current "
                          "UNKNOWN episode")
        self.assertEqual(self.refused_reason(issue), "ISSUE_TITLE_NOT_THREE_SEGMENTS")

    def test_neither_of_them_enqueues(self):
        for title in ("C02 · V70-R3-C02-01 · trusted coupon plan and exact consent",
                      "V70-R4-C05-01 — bind FAILED reconciliation"):
            issue = self.issue(79)
            issue["title"] = title
            with self.assertRaises(contract.Refused):
                ingress.ingest(issue, runtime=self.runtime, environ=ENABLED)
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
            plan = ingress.plan_ingress(self.issue(79))
            self.assertEqual(plan["action"], "DISABLED")
            self.assertFalse(plan["enabled"])
            # A disabled ingress still computes the task it would create.
            self.assertEqual(plan["would_enqueue"]["kind"], "GHAW_BUILDER_V1")
            result = ingress.ingest(self.issue(79), runtime=self.runtime)
            self.assertEqual(result["action"], "DISABLED")
            self.assertFalse(result["enqueued"])

    def test_disabled_ingest_writes_nothing_even_handed_a_runtime(self):
        for value in ("", "false", "1", "yes"):
            with self.subTest(value=value):
                result = ingress.ingest(self.issue(79), runtime=self.runtime,
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
        result = ingress.ingest(self.issue(79), runtime=self.runtime, environ=ENABLED)
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
            ingress.ingest(self.issue(79), environ=ENABLED)
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
                     str(number)],
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
            modules, {"__future__", "json", "os", "re", "sys", "c1_execution_contract"},
            "the ingress must import the shared contract and the standard library only")

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
