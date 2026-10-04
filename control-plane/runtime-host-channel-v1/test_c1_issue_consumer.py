"""Consumer tests: GitHub open C01 issues -> Runtime.enqueue, offline and read-only.

Coverage map:

  A  TheGitHubAccessIsReadOnly        GET only, one path, no comment, no write verb
  B  OnlyC01IssuesAreConsidered       pull requests and other cells never reach the parser
  C  RepeatPollingIsOneRuntimeTask    N polls -> one Runtime task (kernel UNIQUE)
  D  MalformedClosedAndOtherCellsFailClosed
  E  DisabledByDefaultWritesNothing   shadow output, no Runtime constructed at all
  F  EnabledOfflineEnqueuesOnce       injected Runtime double over a temporary DB
  G  CheckIsOffline                   capability report touches no network and no Runtime
  H  StructuralBounds                 no second parser, no local de-dup store, no smoke

No network, no Runtime host, no model call, no GitHub write to the real repository.
"""
import ast
import json
import os
import re
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
import c1_issue_consumer as consumer  # noqa: E402

CONSUMER_SOURCE = HERE / "c1_issue_consumer.py"
UNIT_FILE = HERE / "systemd" / "go-runtime-host-c01-issue-consumer.service"
FIXTURE = HERE / "issue_fixtures" / "real_c01_issues.json"
ENABLED = {consumer.INGRESS_ENABLED_ENV: "true"}
FAKE_API = "https://api.example.invalid"
TEST_TOKEN = "not-a-real-token"
PAGE_IN_URL = re.compile(r"[?&]page=(\d+)")

# The source anchor the captured fixture bodies carry. The fake platform reports THIS as
# the default-branch head by default, which is the world those issues were written in: the
# tests that are about fetching, planning and de-duplication keep their meaning, and the
# tests about freshness move the head on purpose (see class SourceHeadIsReadOncePerPoll).
FIXTURE_SOURCE = "8ffcde66d36c1bbf849218529ef015f6e81725af"
# A real commit from this repository's history, used to represent "main has moved since
# those issues were written".
MOVED_ON_SOURCE = "e4076276d70058d16f68fda5db047161ca6ef4cc"


def load_fixture() -> dict:
    with open(FIXTURE, encoding="utf-8") as handle:
        document = json.load(handle)
    return {issue["number"]: issue for issue in document["issues"]}


ISSUES = load_fixture()


class FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class RecordingOpener:
    """A transport that records what was asked for and answers with canned documents.

    It is the only thing standing in for the network, so the request the consumer would
    really send - verb, URL, headers - is what gets asserted. Two paths are served: the
    issue listing (from `pages`) and the default-branch head, which is why the poll can be
    checked for reading the source exactly once.
    """

    def __init__(self, pages, *, source_head=FIXTURE_SOURCE, source_body=None,
                 source_raises=None):
        self.calls = []
        self._pages = pages
        self._source_head = source_head
        # A raw body (for the malformed / not-an-object cases) or an exception (for the
        # HTTP and transport failures) replaces the well-formed answer when supplied.
        self._source_body = source_body
        self._source_raises = source_raises
        self.source_calls = 0

    def __call__(self, request, timeout=None):
        self.calls.append({"method": request.get_method(), "url": request.full_url,
                           "headers": dict(request.headers), "timeout": timeout})
        if request.full_url.split("?")[0] == FAKE_API + consumer.SOURCE_HEAD_PATH:
            self.source_calls += 1
            if self._source_raises is not None:
                raise self._source_raises
            if self._source_body is not None:
                return FakeResponse(self._source_body)
            return FakeResponse(json.dumps({"sha": self._source_head}).encode("utf-8"))
        match = PAGE_IN_URL.search(request.full_url)
        page = int(match.group(1)) if match else 1
        body = self._pages[page - 1] if page - 1 < len(self._pages) else []
        return FakeResponse(json.dumps(body).encode("utf-8"))

    @property
    def verbs(self):
        return sorted({call["method"] for call in self.calls})

    @property
    def paths(self):
        return sorted({call["url"].split("?")[0] for call in self.calls})


class RuntimeDouble:
    """The kernel's enqueue semantics the consumer relies on: key is UNIQUE."""

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
            row = self._db.execute(
                "SELECT task_id FROM tasks WHERE idempotency_key = ?",
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
        self._tmp = tempfile.TemporaryDirectory(prefix="c01-consumer-")
        self.addCleanup(self._tmp.cleanup)
        self.runtime = RuntimeDouble(Path(self._tmp.name) / "runtime.db")
        self.addCleanup(self.runtime.close)

    def issue(self, number):
        return json.loads(json.dumps(ISSUES[number]))

    def reader(self, pages, *, per_page=consumer.PER_PAGE, source_head=FIXTURE_SOURCE,
               source_body=None, source_raises=None):
        self.opener = RecordingOpener(pages, source_head=source_head,
                                      source_body=source_body,
                                      source_raises=source_raises)
        return consumer.GitHubIssuesReader(
            token_loader=lambda: TEST_TOKEN, opener=self.opener, api_base=FAKE_API,
            per_page=per_page)

    def expected_plan(self, number, *, current=FIXTURE_SOURCE):
        # The one authority on the plan is the ingress; the consumer only reports it.
        import c1_issue_ingress
        return c1_issue_ingress.plan_ingress(self.issue(number),
                                             current_source_anchor=current, environ={})


# ------------------------------------------------------------------ A
class TheGitHubAccessIsReadOnly(Case):
    """One verb, one path, no comment, no write - by construction and by request."""

    def test_the_listing_is_a_single_get_to_the_issues_endpoint(self):
        reader = self.reader([[self.issue(79)]], per_page=1)
        reader.list_open_issues(pages=1)
        self.assertEqual(self.opener.verbs, ["GET"])
        self.assertEqual(self.opener.paths, [FAKE_API + consumer.ISSUES_PATH])
        self.assertEqual(consumer.ISSUES_PATH,
                         "/repos/yuguangzhi3836-glitch/GO/issues")

    def test_the_token_travels_in_a_header_and_never_in_the_url(self):
        reader = self.reader([[self.issue(79)]], per_page=1)
        reader.list_open_issues(pages=1)
        call = self.opener.calls[0]
        self.assertNotIn(TEST_TOKEN, call["url"])
        self.assertEqual(call["headers"].get("Authorization"), "Bearer " + TEST_TOKEN)
        self.assertEqual(call["timeout"], consumer.HTTP_TIMEOUT_S)

    def test_pagination_is_bounded_and_stops_on_a_short_page(self):
        reader = self.reader([[self.issue(79)], [self.issue(116)]], per_page=100)
        listing = reader.list_open_issues(pages=3)
        self.assertEqual(listing["pages_fetched"], 1, "a short page ends the listing")
        self.assertEqual(listing["listed"], 1)
        with self.assertRaises(contract.Refused) as caught:
            reader.list_open_issues(pages=0)
        self.assertEqual(caught.exception.reason, "PAGES_OUT_OF_RANGE")
        with self.assertRaises(contract.Refused) as caught:
            reader.list_open_issues(pages=consumer.MAX_PAGES + 1)
        self.assertEqual(caught.exception.reason, "PAGES_OUT_OF_RANGE")

    def test_the_page_number_is_taken_from_the_real_query_string(self):
        # per_page= also contains "page=" - the harness must not confuse them.
        reader = self.reader([[self.issue(79)], [self.issue(116)]], per_page=1)
        listing = reader.list_open_issues(pages=1)
        self.assertEqual(listing["listed"], 1)
        self.assertIn("per_page=1", self.opener.calls[0]["url"])
        self.assertRegex(self.opener.calls[0]["url"], r"[?&]page=1\b")

    def test_no_write_verb_and_no_comment_path_exists_in_the_module(self):
        source = CONSUMER_SOURCE.read_text(encoding="utf-8")
        for forbidden in ('"POST"', '"PATCH"', '"PUT"', '"DELETE"',
                          "/comments", "issues/comments", "labels", "assignees"):
            with self.subTest(token=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertIn('method="GET"', source)

    def test_a_listing_failure_is_reported_without_leaking_the_response(self):
        # The denial is on the ISSUE LISTING path specifically. The poll's source read is a
        # different request and is answered normally, because this test is about how a
        # listing failure is reported - not about the source read, which has its own class.
        class Denied:
            def __call__(self, request, timeout=None):
                if request.full_url.split("?")[0] == FAKE_API + consumer.SOURCE_HEAD_PATH:
                    return FakeResponse(json.dumps({"sha": FIXTURE_SOURCE}).encode("utf-8"))
                raise consumer.urllib.error.HTTPError(request.full_url, 403,
                                                      "forbidden", {}, None)

        reader = consumer.GitHubIssuesReader(token_loader=lambda: TEST_TOKEN,
                                             opener=Denied(), api_base=FAKE_API)
        result = consumer.poll_once(reader=reader, environ={})
        self.assertEqual(result["status"], "LISTING_FAILED")
        self.assertEqual(result["reason"], "HTTP_403")
        self.assertNotIn(TEST_TOKEN, json.dumps(result))


# ------------------------------------------------------------------ B
class OnlyBuilderCellsAreConsidered(Case):
    """Control-only cells, unknown cells and pull requests never reach the parser."""

    def test_the_prefilter_accepts_builder_cells_only(self):
        # Cell spellings are upper case, as the ingress' own title regex requires - a
        # lower-case cell never has been a candidate, and this round does not change that.
        for cell in ("C01", "C1", "C02", "C09", "C10", "C12"):
            issue = self.issue(79)
            issue["title"] = "%s · V70-R3-C12-01 · platform hardening" % cell
            with self.subTest(cell=cell):
                self.assertTrue(consumer.looks_like_builder_issue(issue))
        for title in ("C13 · V70-R3-C13-01 · independent acceptance",
                      "C14 · V70-R3-C14-01 · constitutional review",
                      "C15 · V70-R3-C15-01 · does not exist",
                      "C0 · V70-R3-C01-01 · no such cell",
                      "C00 · V70-R3-C01-01 · no such cell",
                      "V70-R4-C05-01 — bind FAILED reconciliation",
                      "C01 · no task id here",
                      "C13 independent acceptance for PR #76"):
            issue = self.issue(79)
            issue["title"] = title
            with self.subTest(title=title):
                self.assertFalse(consumer.looks_like_builder_issue(issue))
        pull = self.issue(79)
        pull["pull_request"] = {"url": "x"}
        self.assertFalse(consumer.looks_like_builder_issue(pull))

    def test_every_builder_cell_becomes_a_candidate_and_nothing_else_does(self):
        listing = [self.issue(79)]
        accepted = ("C02 · V70-R3-C02-01 · trusted coupon plan and exact consent",
                    "C12 · V70-R3-C12-01 · platform hardening")
        rejected = ("C13 · V70-R3-C13-01 · independent acceptance",
                    "V70-R4-C05-01 — bind FAILED reconciliation")
        for index, title in enumerate(accepted + rejected):
            clone = self.issue(79)
            clone["title"] = title
            clone["number"] = 999 - index
            listing.append(clone)
        pull = self.issue(79)
        pull["number"] = 900
        pull["pull_request"] = {"url": "x"}
        listing.append(pull)

        result = consumer.poll_once(reader=self.reader([listing]), environ={})
        self.assertEqual(result["listed"], 6)
        # Three candidates - C01, C02 and C12. The control-only cell and the
        # non-three-segment title are filtered before the parser ever sees them, and so
        # is the pull request.
        self.assertEqual(result["candidates"], 3)
        self.assertEqual(sorted(e["issue_number"] for e in result["planned"]),
                         [79, 998, 999])
        self.assertEqual(result["refused"], [])
        self.assertEqual(result["enqueued"], [])


# ------------------------------------------------------------------ C
class RepeatPollingIsOneRuntimeTask(Case):
    """Re-polling is the mechanism, not a hazard: the Runtime is the only authority."""

    def test_ten_polls_produce_one_row_and_one_task_id(self):
        reader = self.reader([[self.issue(79)]], per_page=1)
        results = [consumer.poll_once(reader=reader, runtime=self.runtime,
                                      environ=ENABLED) for _ in range(10)]
        self.assertTrue(all(r["status"] == "PASS" for r in results))
        self.assertTrue(all(r["enqueued"] for r in results))
        self.assertEqual(len({r["enqueued"][0]["runtime_task_id"] for r in results}), 1)
        self.assertEqual(len({r["enqueued"][0]["idempotency_key"] for r in results}), 1)
        self.assertEqual(self.runtime.enqueue_calls, 10)
        self.assertEqual(self.runtime.task_count(), 1)

        task_id, owner_c, kind, payload_json, key, max_attempts = self.runtime.rows()[0]
        self.assertEqual(owner_c, "C1")
        self.assertEqual(kind, "GHAW_BUILDER_V1")
        self.assertEqual(key, "c1-ghaw-builder-v1:C1:V70-R3-C01-01")
        self.assertEqual(max_attempts, 1)
        self.assertTrue(task_id.startswith("rt_"))
        # What landed in the Runtime is exactly what the ingress planned - byte for byte.
        expected = self.expected_plan(79)["would_enqueue"]["payload"]
        self.assertEqual(payload_json, contract.canonical(expected))
        self.assertEqual(results[0]["enqueued"][0]["payload_sha256"],
                         self.expected_plan(79)["payload_sha256"])

    def test_two_candidates_in_one_listing_become_two_distinct_tasks(self):
        second = self.issue(116)
        second["state"] = "open"
        result = consumer.poll_once(reader=self.reader([[self.issue(79), second]]),
                                    runtime=self.runtime, environ=ENABLED)
        self.assertEqual(result["candidates"], 2)
        self.assertEqual(len(result["enqueued"]), 2)
        self.assertEqual(len({e["runtime_task_id"] for e in result["enqueued"]}), 2)
        self.assertEqual(len({e["idempotency_key"] for e in result["enqueued"]}), 2)
        self.assertEqual(self.runtime.task_count(), 2)

    def test_one_tick_considers_at_most_the_configured_number_of_candidates(self):
        listing = []
        for index in range(consumer.MAX_CANDIDATES_PER_POLL + 5):
            clone = self.issue(79)
            clone["number"] = 500 + index
            listing.append(clone)
        result = consumer.poll_once(reader=self.reader([listing]), runtime=self.runtime,
                                    environ=ENABLED)
        self.assertEqual(result["candidates"], len(listing))
        self.assertEqual(result["considered"], consumer.MAX_CANDIDATES_PER_POLL)
        self.assertLessEqual(self.runtime.task_count(),
                             consumer.MAX_CANDIDATES_PER_POLL)


# ------------------------------------------------------------------ D
class MalformedClosedAndOtherCellsFailClosed(Case):
    """Anything unexpected is refused, and a refusal never enqueues."""

    def test_a_title_without_a_task_id_never_becomes_a_candidate(self):
        broken = self.issue(79)
        broken["title"] = "C01 · no task id here"
        result = consumer.poll_once(reader=self.reader([[broken]]),
                                    runtime=self.runtime, environ=ENABLED)
        self.assertEqual(result["candidates"], 0, "the prefilter keeps it out")
        self.assertEqual(result["planned"], [])
        self.assertEqual(result["refused"], [])
        self.assertEqual(self.runtime.enqueue_calls, 0)

    def test_a_c01_titled_issue_with_a_bad_body_is_refused(self):
        broken = self.issue(79)
        broken["body"] = "Task: do the thing."          # no canonical source line
        result = consumer.poll_once(reader=self.reader([[broken]]),
                                    runtime=self.runtime, environ=ENABLED)
        self.assertEqual(result["candidates"], 1)
        self.assertEqual(result["planned"], [])
        self.assertEqual(result["refused"],
                         [{"issue_number": 79,
                           "reason": "INGRESS_SOURCE_ANCHOR_NOT_FOUND"}])
        self.assertEqual(self.runtime.task_count(), 0)
        self.assertEqual(self.runtime.enqueue_calls, 0)

    def test_a_closed_issue_is_refused_even_if_it_arrives_in_the_listing(self):
        # The listing asks for state=open, but the consumer must not trust that: a
        # closed issue arriving anyway is refused by the ingress itself.
        result = consumer.poll_once(reader=self.reader([[self.issue(116)]]),
                                    runtime=self.runtime, environ=ENABLED)
        self.assertEqual(result["refused"],
                         [{"issue_number": 116, "reason": "ISSUE_NOT_OPEN"}])
        self.assertEqual(self.runtime.task_count(), 0)

    def test_a_pull_request_is_never_considered(self):
        pull = self.issue(79)
        pull["pull_request"] = {"url": "x"}
        result = consumer.poll_once(reader=self.reader([[pull]]),
                                    runtime=self.runtime, environ=ENABLED)
        self.assertEqual(result["candidates"], 0)
        self.assertEqual(self.runtime.enqueue_calls, 0)

    def test_an_empty_listing_is_not_an_error(self):
        result = consumer.poll_once(reader=self.reader([[]]), runtime=self.runtime,
                                    environ=ENABLED)
        self.assertEqual(result["status"], "NO_CANDIDATE")
        self.assertEqual(result["candidates"], 0)
        self.assertEqual(self.runtime.enqueue_calls, 0)


# ------------------------------------------------------------------ E
class DisabledByDefaultWritesNothing(Case):
    """The shadow path cannot reach the Runtime, structurally."""

    def test_the_default_environment_is_disabled(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(consumer.INGRESS_ENABLED_ENV, None)
            self.assertFalse(consumer.ingress_enabled())
            result = consumer.poll_once(reader=self.reader([[self.issue(79)]]),
                                        environ=None)
            self.assertEqual(result["status"], "DISABLED")
            self.assertFalse(result["enabled"])
            self.assertEqual(result["enqueued"], [])
            self.assertEqual(result["considered"], 1, "it still reports the plan")
            self.assertEqual(result["planned"][0]["idempotency_key"],
                             "c1-ghaw-builder-v1:C1:V70-R3-C01-01")

    def test_disabled_never_uses_a_runtime_even_when_one_is_injected(self):
        for value in ("", "false", "1", "yes"):
            with self.subTest(value=value):
                result = consumer.poll_once(
                    reader=self.reader([[self.issue(79)]]), runtime=self.runtime,
                    environ={consumer.INGRESS_ENABLED_ENV: value})
                self.assertEqual(result["status"], "DISABLED")
                self.assertEqual(result["enqueued"], [])
        self.assertEqual(self.runtime.enqueue_calls, 0)
        self.assertEqual(self.runtime.task_count(), 0)

    def test_the_shadow_path_does_not_even_build_a_runtime(self):
        def explode():
            raise AssertionError("the Runtime must not be built while disabled")

        result = consumer.poll_once(reader=self.reader([[self.issue(79)]]),
                                    runtime_factory=explode, environ={})
        self.assertEqual(result["status"], "DISABLED")
        self.assertEqual(result["planned"][0]["external_task_id"], "V70-R3-C01-01")


# ------------------------------------------------------------------ F
class EnabledOfflineEnqueuesOnce(Case):
    """Enabled, with an injected Runtime over a temporary DB."""

    def test_enabled_poll_enqueues_the_planned_call(self):
        result = consumer.poll_once(reader=self.reader([[self.issue(79)]]),
                                    runtime=self.runtime, environ=ENABLED)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["enabled"])
        self.assertEqual(len(result["enqueued"]), 1)
        entry = result["enqueued"][0]
        self.assertEqual(entry["runtime_task_id"], self.runtime.rows()[0][0])
        self.assertEqual(entry["external_task_id"], "V70-R3-C01-01")
        self.assertEqual(self.runtime.enqueue_calls, 1)
        self.assertEqual(self.runtime.task_count(), 1)

    def test_enabled_without_a_runtime_is_loud_not_silent(self):
        result = consumer.poll_once(reader=self.reader([[self.issue(79)]]),
                                    runtime=None, runtime_factory=None, environ=ENABLED)
        self.assertEqual(result["status"], "RUNTIME_UNAVAILABLE")
        self.assertEqual(result["runtime_error"], "RUNTIME_UNAVAILABLE")
        self.assertEqual(result["enqueued"], [])
        self.assertEqual(result["planned"][0]["external_task_id"], "V70-R3-C01-01")

    def test_the_runtime_factory_is_used_only_when_enabled(self):
        calls = []

        def factory():
            calls.append(1)
            return self.runtime

        consumer.poll_once(reader=self.reader([[self.issue(79)]]),
                           runtime_factory=factory, environ={})
        self.assertEqual(calls, [])
        consumer.poll_once(reader=self.reader([[self.issue(79)]]),
                           runtime_factory=factory, environ=ENABLED)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.runtime.task_count(), 1)


# ------------------------------------------------------------------ G
class CheckIsOffline(Case):
    """`--check` answers without a network call and without importing the kernel."""

    def test_check_reports_capability_without_a_runtime(self):
        report = consumer.check({}, token_loader=lambda: TEST_TOKEN)
        self.assertEqual(report["status"], "READY")
        self.assertFalse(report["enabled"])
        self.assertEqual(report["credential"], "present")
        self.assertEqual(report["github_access"], "GET only")
        self.assertFalse(report["runtime_imported"])
        self.assertEqual(report["issues_endpoint"], consumer.ISSUES_PATH)

    def test_check_fails_closed_on_a_missing_credential(self):
        def missing():
            raise contract.Refused("TOKEN_FILE_UNREADABLE")

        report = consumer.check({}, token_loader=missing)
        self.assertEqual(report["status"], "BLOCKED_NO_CREDENTIAL")
        self.assertEqual(report["credential"], "absent")
        self.assertEqual(report["credential_reason"], "TOKEN_FILE_UNREADABLE")

    def test_the_cli_check_fails_closed_without_a_credential(self):
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env[consumer.TOKEN_FILE_ENV] = str(Path(self._tmp.name) / "absent-token")
        done = subprocess.run([sys.executable, str(CONSUMER_SOURCE), "--check"],
                              cwd=str(HERE), env=env, capture_output=True, text=True)
        # Non-zero is the point: this is what the unit's ExecStartPre relies on to
        # refuse to start a poller that could only fail every tick.
        self.assertEqual(done.returncode, 1, done.stderr)
        report = json.loads(done.stdout)
        self.assertEqual(report["status"], "BLOCKED_NO_CREDENTIAL")
        self.assertFalse(report["enabled"])
        self.assertEqual(report["credential"], "absent")

    def test_the_cli_without_arguments_is_a_usage_error(self):
        done = subprocess.run([sys.executable, str(CONSUMER_SOURCE), "--nonsense"],
                              cwd=str(HERE), capture_output=True, text=True)
        self.assertEqual(done.returncode, 2)
        self.assertIn("usage", done.stderr)

    def test_the_interval_is_clamped(self):
        self.assertEqual(consumer.poll_interval_s({}), consumer.DEFAULT_INTERVAL_S)
        self.assertEqual(consumer.poll_interval_s({consumer.INTERVAL_ENV: "abc"}),
                         consumer.DEFAULT_INTERVAL_S)
        self.assertEqual(consumer.poll_interval_s({consumer.INTERVAL_ENV: "0"}),
                         consumer.MIN_INTERVAL_S)
        self.assertEqual(consumer.poll_interval_s({consumer.INTERVAL_ENV: "99999"}),
                         consumer.MAX_INTERVAL_S)
        self.assertEqual(consumer.poll_interval_s({consumer.INTERVAL_ENV: "30"}), 30)


# ------------------------------------------------------------------ H
class StructuralBounds(Case):
    """It reuses the ingress, adds no store, and cannot enqueue the smoke class."""

    def test_it_imports_the_ingress_and_nothing_unexpected(self):
        tree = ast.parse(CONSUMER_SOURCE.read_text(encoding="utf-8"))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.add(node.module or "")
        self.assertEqual(modules, {
            "__future__", "json", "os", "sys", "time", "urllib.error",
            "urllib.request", "importlib",
            "c1_execution_contract", "c1_github_actions_client", "c1_issue_ingress",
        })
        # The Runtime kernel is reached only through importlib, inside the factory, so
        # nothing here imports it - or its database - at module load.
        self.assertNotIn("runtime", modules)
        self.assertNotIn("sqlite3", modules)

    def test_it_reuses_the_ingress_instead_of_reimplementing_it(self):
        source = CONSUMER_SOURCE.read_text(encoding="utf-8")
        for reused in ("from c1_issue_ingress import", "plan_ingress(", "ingest(",
                       "ingress_enabled(", "is_builder_cell(", "TITLE_SEPARATOR",
                       "TITLE_CELL"):
            with self.subTest(symbol=reused):
                self.assertIn(reused, source)
        # No second parser, no second schema, no second idempotency derivation, and no
        # second opinion about which cells are Builder cells: the ingress owns all four,
        # and the consumer only calls them.
        for forbidden in ("def parse_c01_issue", "build_task_payload",
                          "real_idempotency_key", "schema_version",
                          "canonical_cell_id", "BUILDER_OWNER_CS"):
            with self.subTest(token=forbidden):
                self.assertNotIn(forbidden, source)

    def test_it_keeps_no_local_state_of_what_it_has_seen(self):
        source = CONSUMER_SOURCE.read_text(encoding="utf-8")
        for forbidden in ("open(", "sqlite3", "json.dump", "pathlib", "shelve",
                          "pickle", ".write("):
            with self.subTest(token=forbidden):
                self.assertNotIn(forbidden, source)

    def test_it_cannot_enqueue_the_smoke_or_probeClass(self):
        source = CONSUMER_SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("AI_WORK_V1", source)
        self.assertNotIn("RUNTIME_PROBE", source)

    def test_the_unit_is_separate_disabled_and_reuses_the_installed_ingress(self):
        text = UNIT_FILE.read_text(encoding="utf-8")
        directives = [line for line in text.splitlines()
                      if line.strip() and not line.strip().startswith(("#", ";"))]
        self.assertIn("WantedBy=multi-user.target", text)
        # Never the Management Agent's bundle, as a directive: adding files there
        # changes the Agent's executor_sha256 and makes it refuse to start.
        for line in directives:
            with self.subTest(directive=line):
                self.assertNotIn("/opt/go/runtime-host-agent", line)
        self.assertIn("User=go-runtime", text)
        self.assertIn("ConditionPathExists=/etc/go-runtime-c1/github-token", text)
        self.assertIn("C1_GITHUB_TOKEN_PATH=/etc/go-runtime-c1/github-token", text)
        # Installed beside the ingress it reuses, so the host keeps exactly one copy of
        # c1_issue_ingress.py rather than a second copy that can go stale.
        self.assertIn("ExecStart=/usr/bin/python3 -B "
                      "/opt/go/runtime-host-c1-worker/c1_issue_consumer.py", text)
        self.assertIn("ExecStartPre=", text)
        # The enable switch is documented but NOT set: unset is the shipped state.
        self.assertIn(consumer.INGRESS_ENABLED_ENV, text)
        self.assertNotIn("Environment=%s=true" % consumer.INGRESS_ENABLED_ENV, text)

    def test_the_ingress_switch_is_the_only_switch(self):
        # One switch, not two: the consumer must not invent its own enable variable.
        source = CONSUMER_SOURCE.read_text(encoding="utf-8")
        self.assertIn("INGRESS_ENABLED_ENV", source)
        self.assertNotIn("C01_ISSUE_CONSUMER_ENABLED", source)


# ------------------------------------------------------------------ source freshness
class SourceHeadIsReadOncePerPoll(Case):
    """One poll, one source snapshot - and a poll that cannot read one does nothing.

    The consumer's second read-only path exists so admission can be about the CURRENT tree
    rather than about whatever an issue claims. It is read once per poll (not once per
    issue) and a failure to read it stops the poll before anything is planned, so a poll
    can never admit a candidate against a source nobody verified.
    """

    def test_the_source_head_is_read_exactly_once_per_poll(self):
        listing = []
        for cell in range(1, 11):
            issue = self.issue(79)
            issue["number"] = 900 + cell
            issue["title"] = "C%02d · V70-R3-C%02d-01 · bounded task" % (cell, cell)
            listing.append(issue)
        result = consumer.poll_once(reader=self.reader([listing]), runtime=self.runtime,
                                    environ={}, pages=1)
        self.assertEqual(len(result["planned"]), 10)
        self.assertEqual(self.opener.source_calls, 1,
                         "one source snapshot per poll, not one per candidate")
        # 1 source GET + 1 listing page, and nothing else.
        self.assertEqual(len(self.opener.calls), 2)

    def test_the_source_read_is_a_get_to_the_commits_endpoint(self):
        self.reader([[]]).read_current_source()
        self.assertEqual(self.opener.verbs, ["GET"])
        self.assertEqual(self.opener.paths, [FAKE_API + consumer.SOURCE_HEAD_PATH])
        self.assertTrue(consumer.SOURCE_HEAD_PATH.endswith("/commits/main"))

    def test_the_poll_reports_the_snapshot_it_used(self):
        result = consumer.poll_once(reader=self.reader([[]]), environ={}, pages=1)
        self.assertEqual(result["current_source_anchor"], FIXTURE_SOURCE)

    def test_a_historical_issue_is_refused_and_reported_with_both_anchors(self):
        result = consumer.poll_once(reader=self.reader([[self.issue(79)],
                                                        [self.issue(79)]],
                                                       source_head=MOVED_ON_SOURCE),
                                    runtime=self.runtime, environ=ENABLED, pages=1)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["planned"], [])
        self.assertEqual(result["enqueued"], [])
        self.assertEqual(self.runtime.task_count(), 0)
        self.assertEqual(len(result["refused"]), 1)
        refusal = result["refused"][0]
        self.assertEqual(refusal["issue_number"], 79)
        self.assertEqual(refusal["reason"], "INGRESS_SOURCE_ANCHOR_NOT_CURRENT")
        self.assertEqual(refusal["parsed_source_anchor"], FIXTURE_SOURCE)
        self.assertEqual(refusal["current_source_anchor"], MOVED_ON_SOURCE)

    def test_a_whole_stale_backlog_yields_no_plan_at_all(self):
        # The live shape: several open issues, all written against an older main. Under the
        # current head none of them is work, so the poll plans nothing and enqueues nothing
        # even with the switch on.
        listing = []
        for cell in (1, 2, 3):
            issue = self.issue(79)
            issue["number"] = 950 + cell
            issue["title"] = "C%02d · V70-R3-C%02d-01 · bounded task" % (cell, cell)
            listing.append(issue)
        result = consumer.poll_once(reader=self.reader([listing], source_head=MOVED_ON_SOURCE),
                                    runtime=self.runtime, environ=ENABLED, pages=1)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(len(result["refused"]), 3)
        self.assertTrue(all(r["reason"] == "INGRESS_SOURCE_ANCHOR_NOT_CURRENT"
                            for r in result["refused"]))
        self.assertEqual(result["planned"], [])
        self.assertEqual(result["enqueued"], [])
        self.assertEqual(self.runtime.enqueue_calls, 0)

    def test_a_failed_source_read_stops_the_poll_before_anything_else(self):
        for label, kwargs in (
                ("http_404", {"source_raises": consumer.urllib.error.HTTPError(
                    consumer.SOURCE_HEAD_PATH, 404, "Not Found", None, None)}),
                ("http_500", {"source_raises": consumer.urllib.error.HTTPError(
                    consumer.SOURCE_HEAD_PATH, 500, "Server Error", None, None)}),
                ("transport", {"source_raises": OSError("no route")}),
                ("not_json", {"source_body": b"<html>nope</html>"}),
                ("not_an_object", {"source_body": b'["not", "an", "object"]'}),
                ("missing_sha", {"source_body": b'{"commit": {}}'}),
                ("invalid_sha", {"source_body": b'{"sha": "not-a-sha"}'}),
                ("short_sha", {"source_body": b'{"sha": "8ffcde66"}'}),
        ):
            with self.subTest(case=label):
                factory_calls = []

                def factory():
                    factory_calls.append(1)
                    return self.runtime

                result = consumer.poll_once(
                    reader=self.reader([[self.issue(79)]], **kwargs),
                    runtime_factory=factory, environ=ENABLED, pages=1)
                self.assertEqual(result["status"], "SOURCE_HEAD_LOOKUP_FAILED")
                # Nothing was planned and nothing was enqueued: the poll stopped at the
                # first read, so the result carries no plan to inspect at all.
                self.assertNotIn("planned", result)
                self.assertNotIn("enqueued", result)
                self.assertNotIn("candidates", result)
                self.assertEqual(factory_calls, [],
                                 "a failed source read must not even build a Runtime")
                self.assertEqual(self.runtime.enqueue_calls, 0)
                self.assertEqual(self.opener.source_calls, 1)
                # Nothing else was read: the poll stopped at the first read.
                self.assertEqual(len(self.opener.calls), 1)

    def test_the_source_head_endpoint_is_reported_by_check(self):
        report = consumer.check({}, token_loader=lambda: TEST_TOKEN)
        self.assertEqual(report["source_head_endpoint"], consumer.SOURCE_HEAD_PATH)
        self.assertIn("source_anchor", report["source_freshness"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
