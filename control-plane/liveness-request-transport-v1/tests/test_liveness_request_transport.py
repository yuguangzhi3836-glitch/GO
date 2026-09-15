"""The transport's own rules, checked without git.

git plumbing is proven end to end by ``install/verify_transport_is_bounded.py``
against a real repository; what is pinned here is everything that decides whether
that plumbing is allowed to run at all, plus the boundedness claims the tool makes
about itself.
"""
import datetime as dt
import importlib.machinery
import importlib.util
import json
import pathlib
import shutil
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOL = ROOT / "command-center" / "go-liveness-request-transport"
SCHEMA = ROOT / "contracts" / "liveness_request_transport_v1.schema.json"


def load_tool():
    loader = importlib.machinery.SourceFileLoader("lrt", str(TOOL))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


X = load_tool()
AT = dt.datetime(2026, 9, 15, 12, 0, 0, tzinfo=dt.timezone.utc)


def request_body(request_id="liveness-control-plane-health-1", **over):
    value = {"schema_version": "1", "request_id": request_id, "action_id": X.ACTION_ID,
             "environment": X.ENVIRONMENT, "requested_at": X.iso(AT)}
    value.update(over)
    return value


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="lrt-"))
        self.outbox = self.root / "outbox"
        self.outbox.mkdir()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def put(self, request_id, body=None):
        (self.outbox / (request_id + ".json")).write_bytes(X.canonical(body or request_body(request_id)))

    def test_a_well_formed_probe_is_read(self):
        self.put("liveness-control-plane-health-1")
        request = X.newest_outbox_request(self.outbox)
        self.assertEqual(request["action_id"], "CONTROL_PLANE_HEALTH")
        self.assertEqual(request["environment"], "HK-STAGING-01")

    def test_only_the_five_common_fields_are_accepted(self):
        for extra in ({"parameters": {}}, {"plan_id": "p"}, {"pr_number": "7"},
                      {"signature": "0" * 8}, {"release_id": "r"}):
            body = request_body(**extra)
            with self.assertRaises(X.Refuse) as caught:
                X.validate_outbox_request("liveness-control-plane-health-1.json",
                                          json.dumps(body).encode())
            self.assertEqual(str(caught.exception), "outbox_fields", extra)

    def test_only_the_declared_action_and_environment_are_relayed(self):
        for over in ({"action_id": "HK_STAGING_VERIFY"}, {"action_id": "HK_STAGING_DEPLOY"},
                     {"action_id": "CONTROL_PLANE_HEALTH_"},
                     {"environment": "PRODUCTION"}, {"environment": "HK-STAGING-02"}):
            with self.assertRaises(X.Refuse) as caught:
                X.validate_outbox_request("liveness-control-plane-health-1.json",
                                          json.dumps(request_body(**over)).encode())
            self.assertEqual(str(caught.exception), "outbox_action_or_environment", over)

    def test_the_filename_must_carry_the_request_id(self):
        other = request_body("liveness-control-plane-health-2")
        with self.assertRaises(X.Refuse) as caught:
            X.validate_outbox_request("liveness-control-plane-health-1.json",
                                      json.dumps(other).encode())
        self.assertEqual(str(caught.exception), "outbox_filename_binding")

    def test_a_non_string_field_is_refused(self):
        for over in ({"requested_at": 0}, {"request_id": 7}, {"action_id": None}):
            with self.assertRaises(X.Refuse):
                X.validate_outbox_request("liveness-control-plane-health-1.json",
                                          json.dumps(request_body(**over)).encode())

    def test_unreadable_json_is_refused(self):
        with self.assertRaises(X.Refuse) as caught:
            X.validate_outbox_request("liveness-control-plane-health-1.json", b"{")
        self.assertEqual(str(caught.exception), "outbox_json")

    def test_a_request_id_outside_the_pattern_is_refused(self):
        for request_id in ("../escape", "has space", "", "-leading"):
            with self.assertRaises(X.Refuse):
                X.validate_outbox_request(request_id + ".json", b"{}")

    def test_the_newest_probe_wins(self):
        self.put("liveness-control-plane-health-1")
        self.put("liveness-control-plane-health-2")
        self.assertEqual(X.newest_outbox_request(self.outbox)["request_id"],
                         "liveness-control-plane-health-2")

    def test_an_empty_or_missing_outbox_publishes_nothing(self):
        self.assertIsNone(X.newest_outbox_request(self.outbox))
        self.assertIsNone(X.newest_outbox_request(self.root / "absent"))
        self.assertEqual(X.relay(self.outbox, self.root, "unused", "unused", AT)["result"],
                         "SKIPPED_NO_REQUEST")


class StalenessTests(unittest.TestCase):
    def test_a_fresh_probe_publishes(self):
        request = request_body()
        for age in (0, 60, X.MAX_PUBLISH_AGE_SECONDS):
            moment = AT + dt.timedelta(seconds=age)
            self.assertEqual(X.publish_decision(request, moment)[0], "PUBLISH", age)

    def test_a_probe_past_the_window_is_skipped_not_published(self):
        request = request_body()
        moment = AT + dt.timedelta(seconds=X.MAX_PUBLISH_AGE_SECONDS + 1)
        decision, age = X.publish_decision(request, moment)
        self.assertEqual(decision, "SKIPPED_STALE")
        self.assertGreater(age, X.MAX_PUBLISH_AGE_SECONDS)

    def test_a_probe_dated_in_the_future_is_refused(self):
        with self.assertRaises(X.Refuse) as caught:
            X.publish_decision(request_body(), AT - dt.timedelta(seconds=1))
        self.assertEqual(str(caught.exception), "requested_at_in_the_future")

    def test_the_publish_window_sits_inside_the_bridge_window(self):
        """The margin is transport slack, not a second way to raise the probe rate."""
        self.assertLess(X.MAX_PUBLISH_AGE_SECONDS, X.bounds()["bridge_max_age_seconds"])


class BoundedSubmissionTests(unittest.TestCase):
    """The Bridge's own rule: exactly one added requests/<id>.json, no deletions."""

    BASE = ["README.md", "tasks/one.json"]

    def test_one_added_request_file_is_bounded(self):
        self.assertEqual(
            X.assert_submission_is_bounded(self.BASE, self.BASE + ["requests/a.json"],
                                           "requests/a.json"),
            ["requests/a.json"])

    def test_anything_else_is_refused(self):
        for label, head in (
                ("two_added_files", self.BASE + ["requests/a.json", "requests/b.json"]),
                ("a_file_that_is_not_a_request", self.BASE + ["tasks/two.json"]),
                ("a_deletion", ["README.md"]),
                ("nothing_added", list(self.BASE))):
            with self.assertRaises(X.Refuse, msg=label) as caught:
                X.assert_submission_is_bounded(self.BASE, head, "requests/a.json")
            self.assertIn("submission_not_bounded", str(caught.exception), label)

    def test_a_path_outside_requests_is_refused(self):
        for request_id in ("../escape", "ok/../bad", "with space"):
            with self.assertRaises(X.Refuse):
                X.request_path(request_id)


class ArchiveTests(unittest.TestCase):
    def test_only_missing_files_are_added(self):
        self.assertEqual(
            X.archive_plan({"requests/a.json": b"a"},
                           {"requests/a.json": b"a", "requests/b.json": b"b"}),
            {"requests/b.json": b"b"})

    def test_a_path_the_archive_already_holds_is_never_rewritten(self):
        with self.assertRaises(X.Refuse) as caught:
            X.archive_plan({"requests/a.json": b"a"}, {"requests/a.json": b"CHANGED"})
        self.assertEqual(str(caught.exception), "archive_path_conflict:requests/a.json")

    def test_a_path_outside_requests_is_refused(self):
        with self.assertRaises(X.Refuse):
            X.archive_plan({}, {"tasks/a.json": b"a"})


class BoundednessClaimTests(unittest.TestCase):
    """The claims the tool makes about itself, and its contract, kept in step."""

    def setUp(self):
        self.bounds = X.bounds()
        self.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    def test_one_transport_branch_and_one_archive_branch(self):
        self.assertEqual(self.bounds["transport_branch"], "boss-request-liveness-transport")
        self.assertTrue(self.bounds["transport_branch"].startswith("boss-request-"))
        self.assertEqual(self.bounds["archive_branch"], "request/liveness-archive")
        self.assertEqual(self.bounds["transport_branches"], 1)
        self.assertEqual(self.bounds["archive_branches"], 1)

    def test_one_submission_and_one_request_per_cycle(self):
        self.assertEqual(self.bounds["submissions_per_cycle"], 1)
        self.assertEqual(self.bounds["requests_per_submission"], 1)

    def test_the_transport_cannot_touch_a_pull_request(self):
        for key in ("pr_creation_capability", "merge_capability", "close_capability",
                    "api_client"):
            self.assertEqual(self.bounds[key], "ABSENT", key)

    def test_the_archive_is_append_only(self):
        self.assertIs(self.bounds["archive_is_append_only"], True)

    def test_the_tool_holds_no_http_client_at_all(self):
        source = TOOL.read_text(encoding="utf-8")
        # "requests" alone is a path prefix here, so look for the import, not the word.
        for forbidden in ("urllib", "http.client", "import requests", "socket",
                          "import gh", "gh.get_token", "GROWING"):
            self.assertFalse(forbidden in source, forbidden)

    def test_the_contract_requires_exactly_the_bounds_the_tool_emits(self):
        """The tool and its own contract, pinned against each other.

        Comparing the tool against a copy of its own dictionary would be a
        comparison that cannot fail; the schema is read from disk instead.
        """
        required = set(self.schema["properties"]["bounds"]["required"])
        self.assertEqual(required, set(self.bounds))
        self.assertEqual(self.schema["properties"]["bounds"]["properties"]
                         ["transport_branches"]["const"], 1)
        self.assertEqual(self.schema["properties"]["bounds"]["properties"]
                         ["bridge_max_age_seconds"]["const"], 900)
        self.assertFalse(self.schema["additionalProperties"])

    def test_the_contract_declares_the_same_branches(self):
        properties = self.schema["properties"]["bounds"]["properties"]
        self.assertEqual(properties["transport_branch"]["const"], X.TRANSPORT_BRANCH)
        self.assertEqual(properties["archive_branch"]["const"], X.ARCHIVE_BRANCH)

    def test_every_report_result_is_in_the_contract_enum(self):
        emitted = {"PUBLISHED", "ALREADY_PUBLISHED", "SKIPPED_STALE",
                   "SKIPPED_NO_REQUEST", "REFUSED"}
        self.assertEqual(set(self.schema["properties"]["result"]["enum"]), emitted)

    def test_the_tool_signs_nothing_and_holds_no_signing_key(self):
        source = TOOL.read_text(encoding="utf-8")
        for forbidden in ("sign(", ".pem", "task-manifest-signing", "MINIFEST"):
            self.assertNotIn(forbidden, source, forbidden)
        # It authenticates with the key that already writes the bus, and no other.
        self.assertEqual(X.DEFAULT_KEY, "/etc/go-command-center/keys/github-tasks-writer")
        self.assertEqual(X.ACTION_ID, "CONTROL_PLANE_HEALTH")
        self.assertEqual(X.ENVIRONMENT, "HK-STAGING-01")

    def test_the_only_refs_it_can_move_are_the_two_declared_branches(self):
        source = TOOL.read_text(encoding="utf-8")
        # Prose in the docstring mentions refs/pull/*/head, so this checks what the
        # code can actually address rather than what the text happens to say.
        self.assertIn('"push", "--quiet", "origin"', source)
        self.assertIn("--force-with-lease", source)
        for ref in (X.TRANSPORT_REF, X.ARCHIVE_REF):
            # Both live under refs/heads/: the archive is nested, which is fine, but
            # nothing this tool pushes may be a pull request ref.
            self.assertTrue(ref.startswith("refs/heads/"), ref)
            self.assertFalse(ref.startswith("refs/pull/"), ref)
        # And the refs it addresses are built from its own branch constants, not
        # from anything a caller could hand in.
        self.assertEqual(X.TRANSPORT_REF, "refs/heads/" + X.TRANSPORT_BRANCH)
        self.assertEqual(X.ARCHIVE_REF, "refs/heads/" + X.ARCHIVE_BRANCH)


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="lrt-"))
        self.outbox = self.root / "outbox"
        self.outbox.mkdir()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def put(self, request_id, moment, **over):
        body = request_body(request_id, requested_at=X.iso(moment), **over)
        (self.outbox / (request_id + ".json")).write_bytes(X.canonical(body))

    def test_a_skipped_report_still_carries_the_bounds(self):
        self.put("liveness-control-plane-health-1", AT)
        report = X.relay(self.outbox, self.root, "unused", "unused",
                         AT + dt.timedelta(seconds=X.MAX_PUBLISH_AGE_SECONDS + 1))
        self.assertEqual(report["result"], "SKIPPED_STALE")
        self.assertEqual(report["bounds"], X.bounds())
        self.assertEqual(
            set(report) - {"bounds"},
            {"result", "request_id", "action_id", "environment", "age_seconds"})

    def test_an_empty_outbox_report_carries_the_bounds(self):
        report = X.relay(self.outbox, self.root, "unused", "unused", AT)
        self.assertEqual(report["result"], "SKIPPED_NO_REQUEST")
        self.assertEqual(report["bounds"]["requests_per_submission"], 1)

    def test_no_report_can_claim_an_authority(self):
        report = X.relay(self.outbox, self.root, "unused", "unused", AT)
        for key in ("grants_execution", "execution_authority", "signature", "task_id"):
            self.assertNotIn(key, report, key)


if __name__ == "__main__":
    unittest.main(verbosity=2)
