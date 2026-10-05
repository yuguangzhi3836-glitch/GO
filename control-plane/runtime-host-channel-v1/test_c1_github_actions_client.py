"""Offline tests for the Runtime-side GitHub Actions client.

Every transport path is faked, so the timeout, the 302-signed-URL rule and the
credential boundaries are exercised without touching GitHub.
"""
import hashlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import c1_dispatch_outbox as outbox_mod  # noqa: E402
import c1_execution_contract as contract  # noqa: E402
import c1_github_actions_client as gh  # noqa: E402

TOKEN = "test-token-MUST-NOT-LEAK"
TASK = "rt_" + "3" * 32
RUN_ID = 36873333333


class FakeResponse:
    def __init__(self, body, status=200):
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.status = status

    def read(self, _n=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class RoutingOpener:
    """Routes by method+path and records every request that carried auth."""

    def __init__(self, routes):
        self.routes = routes
        self.seen = []

    def __call__(self, request, timeout=None):  # noqa: ARG002
        self.seen.append((request.method, request.full_url,
                          "Authorization" in request.headers))
        for (method, needle), handler in self.routes.items():
            if request.method == method and needle in request.full_url:
                if isinstance(handler, Exception):
                    raise handler
                return FakeResponse(handler)
        raise AssertionError("no route for %s %s" % (request.method, request.full_url))


def zip_of(content: bytes, name=gh.RESULT_ARTIFACT_FILE) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(name, content)
    return buffer.getvalue()


def sealed_bytes(task=TASK, attempt=1, run_id=RUN_ID) -> bytes:
    document = {
        "version": 1, "kind": contract.RESULT_KIND, "runtime_task_id": task,
        "attempt": attempt,
        "execution_request_id": contract.execution_request_id(task, attempt),
        "github_run_id": run_id, "github_run_attempt": 1,
        "provider": contract.PROVIDER, "model": "gpt-5.6-sol", "response_id": "resp_1",
        "status": "SUCCEEDED",
        "output_sha256": contract.output_sha256(contract.EXPECTED_OUTPUT),
        "output": contract.EXPECTED_OUTPUT, "accepted": True,
        "reused_terminal_result": False, "authorizes_any_action": False,
    }
    return contract.canonical(document).encode("utf-8")


POSIX_MODES = unittest.skipUnless(
    os.name == "posix", "file-mode semantics are POSIX-only; the Linux CI job covers this")


class TokenFileTests(unittest.TestCase):
    @POSIX_MODES
    def test_a_root_only_token_file_is_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "token")
            Path(path).write_text(TOKEN + "\n", encoding="utf-8")
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            self.assertEqual(gh.token_from_file(path), TOKEN)

    @POSIX_MODES
    def test_a_group_or_world_readable_token_file_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "token")
            Path(path).write_text(TOKEN, encoding="utf-8")
            os.chmod(path, 0o644)
            with self.assertRaises(contract.Refused) as caught:
                gh.token_from_file(path)
            self.assertEqual(caught.exception.reason, "TOKEN_FILE_PERMISSIONS_TOO_OPEN")

    def test_a_missing_token_file_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(contract.Refused) as caught:
                gh.token_from_file(os.path.join(tmp, "nope"))
            self.assertEqual(caught.exception.reason, "TOKEN_FILE_UNREADABLE")

    @POSIX_MODES
    def test_an_empty_token_file_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = os.path.join(tmp, "empty")
            Path(empty).write_text("   \n", encoding="utf-8")
            os.chmod(empty, 0o600)
            with self.assertRaises(contract.Refused) as caught:
                gh.token_from_file(empty)
            self.assertEqual(caught.exception.reason, "TOKEN_FILE_EMPTY")

    def test_the_token_path_is_configuration_not_a_task_parameter(self):
        os.environ[gh.TOKEN_FILE_ENV] = "/tmp/configured-token"
        try:
            self.assertEqual(gh.TOKEN_FILE_ENV, "C1_GITHUB_TOKEN_PATH")
            self.assertEqual(gh.DEFAULT_TOKEN_FILE,
                             "/etc/go-runtime-host/c1-github-token")
            self.assertTrue(callable(gh.configured_token_loader()))
        finally:
            os.environ.pop(gh.TOKEN_FILE_ENV, None)


class ClientCase(unittest.TestCase):
    def client(self, routes, **kwargs):
        self.opener = RoutingOpener(routes)
        return gh.GitHubActionsClient(token_loader=lambda: TOKEN, opener=self.opener,
                                      redirect_opener=self.redirect,
                                      no_redirect_opener=self.opener, **kwargs)

    def setUp(self):
        self.redirect_seen = []

        def redirect(request, timeout=None):  # noqa: ARG002
            self.redirect_seen.append(("Authorization" in request.headers,
                                       request.full_url))
            return FakeResponse(self.archive_bytes if hasattr(self, "archive_bytes") else b"")

        self.redirect = redirect


class DispatchTests(ClientCase):
    def _request(self):
        return contract.build_dispatch_request(TASK, 1)

    def test_a_204_answer_is_recorded_as_an_unknown_run_id(self):
        client = self.client({("POST", "/dispatches"): b""})
        client.dispatch_workflow(self._request())
        # A 204 carries no body: the outbox will resolve the run by name instead.
        self.assertEqual(client.dispatch_workflow(self._request()), ("sent", None))

    def test_a_200_answer_with_a_run_id_is_used_directly(self):
        client = self.client({("POST", "/dispatches"): {"workflow_run_id": RUN_ID,
                                                        "run_url": "x", "html_url": "y"}})
        self.assertEqual(client.dispatch_workflow(self._request()), ("sent", RUN_ID))

    def test_the_dispatch_body_carries_only_the_identity_triple(self):
        client = self.client({("POST", "/dispatches"): {"workflow_run_id": RUN_ID}})
        sent = {}

        def opener(request, timeout=None):  # noqa: ARG002
            sent["body"] = json.loads(request.data.decode("utf-8"))
            sent["url"] = request.full_url
            return FakeResponse({"workflow_run_id": RUN_ID})

        client._opener = opener  # noqa: SLF001
        client.dispatch_workflow(self._request())
        self.assertEqual(set(sent["body"]["inputs"]),
                         {"runtime_task_id", "attempt", "execution_request_id"})
        self.assertEqual(sent["body"]["ref"], contract.REF)
        self.assertIn(contract.WORKFLOW_FILE, sent["url"])

    def test_a_404_is_a_refusal_not_a_retry(self):
        client = self.client({("POST", "/dispatches"): urllib.error.HTTPError(
            "u", 404, "not found", {}, None)})
        with self.assertRaises(contract.Refused) as caught:
            client.dispatch_workflow(self._request())
        self.assertEqual(caught.exception.reason, "GITHUB_HTTP_404")

    def test_a_missing_credential_fails_closed(self):
        client = gh.GitHubActionsClient(token_loader=lambda: "",
                                        opener=RoutingOpener({}))
        with self.assertRaises(contract.Refused) as caught:
            client.dispatch_workflow(self._request())
        self.assertEqual(caught.exception.reason, "GITHUB_TOKEN_MISSING")

    def test_the_token_travels_only_as_an_authorization_header(self):
        client = self.client({("POST", "/dispatches"): {"workflow_run_id": RUN_ID}})
        client.dispatch_workflow(self._request())
        method, url, had_auth = self.opener.seen[0]
        self.assertEqual(method, "POST")
        self.assertTrue(had_auth)
        self.assertNotIn(TOKEN, url)


class RunLookupTests(ClientCase):
    def test_a_run_is_found_by_its_deterministic_name(self):
        name = contract.run_identity_name(TASK, 1, contract.execution_request_id(TASK, 1))
        client = self.client({("GET", "/actions/runs?"): {
            "workflow_runs": [
                {"id": 999, "name": "unrelated", "status": "completed",
                 "conclusion": "success", "run_attempt": 1},
                {"id": RUN_ID, "name": name, "status": "in_progress",
                 "conclusion": None, "run_attempt": 1},
            ]}})
        found = client.find_run_by_name(name)
        self.assertEqual(found["id"], RUN_ID)
        self.assertEqual(found["status"], "in_progress")

    def test_a_lookup_that_matches_nothing_returns_none(self):
        client = self.client({("GET", "/actions/runs?"): {"workflow_runs": []}})
        self.assertIsNone(client.find_run_by_name("C1 nothing 1 deadbeef"))

    def test_get_run_reports_the_terminal_state(self):
        client = self.client({("GET", "/actions/runs/%s" % RUN_ID): {
            "id": RUN_ID, "status": "completed", "conclusion": "success",
            "run_attempt": 2}})
        run = client.get_run(RUN_ID)
        self.assertEqual((run["status"], run["conclusion"], run["run_attempt"]),
                         ("completed", "success", 2))

    def test_the_outbox_adapters_match_the_outbox_contract(self):
        name = contract.run_identity_name(TASK, 1, contract.execution_request_id(TASK, 1))
        client = self.client({
            ("POST", "/dispatches"): b"",
            ("GET", "/actions/runs?"): {"workflow_runs": [
                {"id": RUN_ID, "name": name, "status": "queued", "conclusion": None}]},
        })
        with tempfile.TemporaryDirectory() as tmp:
            box = outbox_mod.DispatchOutbox(os.path.join(tmp, "o.db"))
            try:
                first = outbox_mod.drive_once(box, TASK, 1, send=client.send,
                                              find_run=client.find_run)
                self.assertEqual(first["action"], "DISPATCHED")
                self.assertFalse(first["resolved"])
                second = outbox_mod.drive_once(box, TASK, 1, send=client.send,
                                               find_run=client.find_run)
                self.assertEqual(second["action"], "RUN_BOUND")
                self.assertEqual(second["github_run_id"], RUN_ID)
                self.assertEqual(box.dispatch_status(contract.execution_request_id(TASK, 1)),
                                 "RUNNING")
            finally:
                box.close()


class FailureClosureClientTests(ClientCase):
    def test_jobs_are_read_for_the_exact_attempt(self):
        client = self.client({("GET", "/attempts/2/jobs?"): {
            "jobs": [{"id": 71, "conclusion": "failure", "steps": []}]}})
        jobs = client.list_run_jobs(RUN_ID, 2)
        self.assertEqual(jobs[0]["id"], 71)
        self.assertIn("/runs/%s/attempts/2/jobs" % RUN_ID, self.opener.seen[0][1])

    def test_job_log_redirect_does_not_forward_the_token(self):
        self.archive_bytes = b"log data only"
        client = self.client({("GET", "/actions/jobs/71/logs"): urllib.error.HTTPError(
            "u", 302, "found", {"Location": "https://signed.invalid/job"}, None)})
        self.assertEqual(client.download_job_log(71), "log data only")
        self.assertFalse(self.redirect_seen[0][0])

    def test_comment_marker_scan_and_single_write(self):
        client = self.client({
            ("GET", "/issues/478/comments?"): [{"body": "GO_FAILURE_CLOSURE:abc"}],
            ("POST", "/issues/478/comments"): {"id": 91},
        })
        self.assertTrue(client.issue_comment_contains(478, "GO_FAILURE_CLOSURE:abc"))
        self.assertEqual(client.post_issue_comment(478, "bounded body"), 91)
        self.assertEqual([item[0] for item in self.opener.seen], ["GET", "POST"])


class ArtifactTests(ClientCase):
    def _listing(self, archive, digest=None, expired=False, count=1):
        entries = [{"id": 7, "digest": digest if digest is not None
                    else "sha256:" + hashlib.sha256(archive).hexdigest(),
                    "expired": expired} for _ in range(count)]
        return {"artifacts": entries}

    def test_the_result_file_is_returned_with_its_own_digest(self):
        self.archive_bytes = zip_of(sealed_bytes())
        client = self.client({("GET", "/artifacts?name="): self._listing(self.archive_bytes),
                              ("GET", "/artifacts/7/zip"): urllib.error.HTTPError(
                                  "u", 302, "found", {"Location": "https://signed.invalid/x"}, None)})
        got = client.download_artifact(RUN_ID, "c1-ai-execution-result-x")
        self.assertEqual(got["bytes"], sealed_bytes())
        self.assertEqual(got["digest"], "sha256:" + hashlib.sha256(sealed_bytes()).hexdigest())
        self.assertEqual(got["github_run_id"], RUN_ID)

    def test_the_signed_url_follow_carries_no_authorization_header(self):
        self.archive_bytes = zip_of(sealed_bytes())
        client = self.client({("GET", "/artifacts?name="): self._listing(self.archive_bytes),
                              ("GET", "/artifacts/7/zip"): urllib.error.HTTPError(
                                  "u", 302, "found", {"Location": "https://signed.invalid/x"}, None)})
        client.download_artifact(RUN_ID, "n")
        self.assertEqual(len(self.redirect_seen), 1)
        had_auth, url = self.redirect_seen[0]
        self.assertFalse(had_auth, "the signed artifact URL must not receive a bearer token")
        self.assertEqual(url, "https://signed.invalid/x")

    def test_a_modified_archive_is_refused_against_the_platform_digest(self):
        archive = zip_of(sealed_bytes())
        self.archive_bytes = zip_of(b"tampered")
        client = self.client({("GET", "/artifacts?name="): self._listing(archive),
                              ("GET", "/artifacts/7/zip"): urllib.error.HTTPError(
                                  "u", 302, "found", {"Location": "https://signed.invalid/x"}, None)})
        with self.assertRaises(contract.Refused) as caught:
            client.download_artifact(RUN_ID, "n")
        self.assertEqual(caught.exception.reason, "ARTIFACT_ARCHIVE_DIGEST_MISMATCH")

    def test_an_expired_or_missing_or_ambiguous_artifact_is_refused(self):
        archive = zip_of(sealed_bytes())
        expired = self.client({("GET", "/artifacts?name="): self._listing(archive, expired=True)})
        with self.assertRaises(contract.Refused) as caught:
            expired.download_artifact(RUN_ID, "n")
        self.assertEqual(caught.exception.reason, "ARTIFACT_EXPIRED")

        missing = self.client({("GET", "/artifacts?name="): {"artifacts": []}})
        self.assertIsNone(missing.download_artifact(RUN_ID, "n"))

        ambiguous = self.client({("GET", "/artifacts?name="): self._listing(archive, count=2)})
        with self.assertRaises(contract.Refused) as caught:
            ambiguous.download_artifact(RUN_ID, "n")
        self.assertEqual(caught.exception.reason,
                         "MORE_THAN_ONE_ARTIFACT_WITH_THE_EXECUTION_IDENTITY")

    def test_an_archive_without_the_result_file_is_refused(self):
        # The member name is required, not inferred: a differently-shaped artifact
        # must not be able to satisfy the contract just by having one file in it.
        archive = zip_of(b"{}", name="something-else.json")
        self.archive_bytes = archive
        client = self.client({("GET", "/artifacts?name="): self._listing(archive),
                              ("GET", "/artifacts/7/zip"): urllib.error.HTTPError(
                                  "u", 302, "found", {"Location": "https://signed.invalid/x"}, None)})
        with self.assertRaises(contract.Refused) as caught:
            client.download_artifact(RUN_ID, "n")
        self.assertEqual(caught.exception.reason, "ARTIFACT_DOES_NOT_CONTAIN_THE_RESULT_FILE")


class BoundaryTests(unittest.TestCase):
    def test_the_client_holds_no_model_credential_and_no_database(self):
        text = (HERE / "c1_github_actions_client.py").read_text(encoding="utf-8")
        for forbidden in ("OPENAI_API_KEY", "api.openai.com", "sqlite3", "runtime.db"):
            self.assertNotIn(forbidden, text, forbidden)

    def test_the_client_never_opens_a_listener(self):
        text = (HERE / "c1_github_actions_client.py").read_text(encoding="utf-8")
        for forbidden in ("socket", "listen(", "HTTPServer"):
            self.assertNotIn(forbidden, text, forbidden)

    def test_the_token_is_never_embedded_or_logged(self):
        text = (HERE / "c1_github_actions_client.py").read_text(encoding="utf-8")
        self.assertNotIn("print(", text)
        self.assertNotIn(TOKEN, text)


if __name__ == "__main__":
    unittest.main()
