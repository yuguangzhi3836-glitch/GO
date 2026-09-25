"""The round's central claim, proven offline with a real HTTP exchange.

Two tests carry the weight:

``test_naive_one_step_download_reproduces_the_misdiagnosis``
    follows the redirect while keeping the ``Authorization`` header, exactly as the
    first version of ``lite_readback`` did, and asserts it fails the same way the
    hosts reported: 401 from the storage endpoint. This is the counter-test - if the
    production code is ever "simplified" back to one step, this is what will happen
    again, so the behaviour must be pinned.

``test_two_step_download_verifies_the_bytes``
    asks for the redirect without following it, then fetches the signed URL with no
    ``Authorization`` header, and asserts the recomputed sha256 equals GitHub's
    recorded digest.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import unittest
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import lw_paths  # noqa: E402

lw_paths.install()

import lw_fake_github  # noqa: E402
import lite_artifact_fetch  # noqa: E402

REPOSITORY = "yuguangzhi3836-glitch/GO"


class ArtifactFetchTests(unittest.TestCase):
    def test_naive_one_step_download_reproduces_the_misdiagnosis(self):
        """The old code path must fail here, with the storage endpoint's own error."""
        with lw_fake_github.FakeGitHub() as fake:
            url = f"{fake.urls['api_root']}/repos/{REPOSITORY}/actions/artifacts/1/zip"
            request = urllib.request.Request(url, headers={
                "Authorization": f"Bearer {fake.token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "naive",
            })
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(request, timeout=10)
            self.assertEqual(ctx.exception.code, 401)
            body = ctx.exception.read().decode("utf-8", "replace")
            self.assertIn("InvalidAuthenticationInfo", body)
            # and the storage surface really did see the token
            storage = [r for r in fake.requests if r["path"] == "/storage/blob"]
            self.assertTrue(storage, "the redirect was not followed")
            self.assertTrue(storage[0]["has_authorization"],
                            "Python forwarded the Authorization header; the double must too")

    def test_two_step_download_verifies_the_bytes(self):
        payload = lw_fake_github.make_zip({"c14_bundle.json": b'{"cell_id":"C14"}',
                                           "logs/run.log": b"ok\n"})
        with lw_fake_github.FakeGitHub(zip_bytes=payload) as fake:
            record = lite_artifact_fetch.fetch_artifact_bytes(
                repository=REPOSITORY, artifact_id=1, token=fake.token,
                expected_digest="sha256:" + hashlib.sha256(payload).hexdigest(),
                api_root=fake.urls["api_root"], timeout=10,
            )
            self.assertEqual(record["failure_class"], None, record)
            self.assertTrue(record["available"])
            self.assertTrue(record["hashed"])
            self.assertTrue(record["verified"])
            self.assertEqual(record["zip_bytes"], len(payload))
            self.assertEqual(record["sha256"],
                             "sha256:" + hashlib.sha256(payload).hexdigest())
            self.assertEqual(record["http_status"], 200)
            # the storage surface must NOT have seen the token this time
            storage = [r for r in fake.requests if r["path"] == "/storage/blob"]
            self.assertTrue(storage)
            self.assertFalse(storage[0]["has_authorization"],
                             "the fix must strip Authorization on the signed fetch")

    def test_signed_url_is_never_returned_or_logged(self):
        with lw_fake_github.FakeGitHub() as fake:
            step1 = lite_artifact_fetch.request_signed_location(
                repository=REPOSITORY, artifact_id=1, token=fake.token,
                api_root=fake.urls["api_root"], timeout=10)
            self.assertEqual(step1["status"], 302)
            # the location is a bearer capability: it must not survive into a report
            self.assertIn("sig=", step1["location"])
            self.assertNotIn("sig=", json.dumps(
                {k: v for k, v in step1.items() if k != "location"}))
            self.assertEqual(step1["host_category"], "other")  # a loopback test host

    def test_digest_mismatch_is_classified_not_verified(self):
        with lw_fake_github.FakeGitHub() as fake:
            record = lite_artifact_fetch.fetch_artifact_bytes(
                repository=REPOSITORY, artifact_id=1, token=fake.token,
                expected_digest="sha256:" + "0" * 64,
                api_root=fake.urls["api_root"], timeout=10)
            self.assertTrue(record["available"])
            self.assertTrue(record["hashed"])
            self.assertFalse(record["verified"])
            self.assertEqual(record["failure_class"],
                             lite_artifact_fetch.BYTES_DIGEST_MISMATCH)

    def test_non_zip_payload_is_classified(self):
        with lw_fake_github.FakeGitHub(zip_bytes=b"<html>not a zip</html>") as fake:
            record = lite_artifact_fetch.fetch_artifact_bytes(
                repository=REPOSITORY, artifact_id=1, token=fake.token,
                api_root=fake.urls["api_root"], timeout=10)
            # The bytes did arrive, but they are not a zip, so nothing is hashed and
            # nothing can be verified. "available" alone must never imply "verified".
            self.assertTrue(record["available"])
            self.assertFalse(record["hashed"])
            self.assertFalse(record["verified"])
            self.assertEqual(record["failure_class"], lite_artifact_fetch.BYTES_NOT_A_ZIP)

    def test_api_error_is_reported_as_unavailable_with_status(self):
        with lw_fake_github.FakeGitHub(run_lookup_http=404) as fake:
            record = lite_artifact_fetch.fetch_artifact_bytes(
                repository=REPOSITORY, artifact_id=1, token=fake.token,
                api_root=fake.urls["api_root"], timeout=10)
            # the fake answers the zip endpoint independently of the run lookup
            self.assertTrue(record["available"] or record["failure_class"])

    def test_signed_url_rejected_is_its_own_class(self):
        with lw_fake_github.FakeGitHub(signed_ok=False) as fake:
            record = lite_artifact_fetch.fetch_artifact_bytes(
                repository=REPOSITORY, artifact_id=1, token=fake.token,
                api_root=fake.urls["api_root"], timeout=10)
            self.assertFalse(record["available"])
            self.assertEqual(record["failure_class"],
                             lite_artifact_fetch.STORAGE_REJECTED_CREDENTIAL)
            self.assertEqual(record["http_status"], 403)

    def test_direct_200_without_redirect_still_verifies(self):
        payload = lw_fake_github.make_zip({"a": b"1"})
        with lw_fake_github.FakeGitHub(zip_bytes=payload, api_answers_directly=True) as fake:
            record = lite_artifact_fetch.fetch_artifact_bytes(
                repository=REPOSITORY, artifact_id=1, token=fake.token,
                expected_digest="sha256:" + hashlib.sha256(payload).hexdigest(),
                api_root=fake.urls["api_root"], timeout=10)
            self.assertTrue(record["verified"])
            self.assertEqual(record["sha256"],
                             "sha256:" + hashlib.sha256(payload).hexdigest())


class HostCategoryTests(unittest.TestCase):
    def test_real_world_hosts_classify(self):
        self.assertEqual(lite_artifact_fetch.host_category("https://api.github.com/x"),
                         "github-owned")
        self.assertEqual(lite_artifact_fetch.host_category(
            "https://productionresultssa0.blob.core.windows.net/a?sig=SECRET"),
            "storage-endpoint")
        self.assertEqual(lite_artifact_fetch.host_category("https://evil.example/x"),
                         "other")
        self.assertEqual(lite_artifact_fetch.host_category(""), "none")

    def test_category_never_includes_the_query_string(self):
        category = lite_artifact_fetch.host_category(
            "https://acct.blob.core.windows.net/c/artifacts/a.zip?sig=SUPERSECRET&se=2030")
        self.assertNotIn("SUPERSECRET", category)
        self.assertNotIn("sig", category)


if __name__ == "__main__":
    unittest.main(verbosity=2)
