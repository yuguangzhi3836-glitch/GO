"""Credential handling: custody, scope, and the promise that it is never rendered."""
from __future__ import annotations

import dataclasses
import pathlib
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import lw_paths  # noqa: E402

lw_paths.install()

import lw_credential  # noqa: E402

FAKE_TOKEN = "github_pat_" + "A1b2C3d4E5f6G7h8I9j0" * 4


class LoadTests(unittest.TestCase):
    def _write(self, body: str) -> str:
        handle = tempfile.NamedTemporaryFile("w", suffix=".token", delete=False,
                                             encoding="utf-8")
        handle.write(body)
        handle.close()
        self.addCleanup(lambda: pathlib.Path(handle.name).unlink(missing_ok=True))
        return handle.name

    def test_trailing_newline_is_stripped(self):
        path = self._write(FAKE_TOKEN + "\n")
        credential = lw_credential.load(path)
        self.assertEqual(credential.token, FAKE_TOKEN)
        self.assertEqual(credential.length, len(FAKE_TOKEN))

    def test_crlf_is_stripped(self):
        path = self._write(FAKE_TOKEN + "\r\n")
        self.assertEqual(lw_credential.load(path).token, FAKE_TOKEN)

    def test_empty_file_is_refused(self):
        path = self._write("\n  \n")
        with self.assertRaises(lw_credential.CredentialError) as ctx:
            lw_credential.load(path)
        self.assertEqual(str(ctx.exception), "credential_file_empty")

    def test_missing_file_is_refused(self):
        with self.assertRaises(lw_credential.CredentialError) as ctx:
            lw_credential.load("/nonexistent/path/to.token")
        self.assertEqual(str(ctx.exception), "credential_file_missing")

    def test_internal_whitespace_is_refused(self):
        # A file with a stray space would otherwise become a 401 that looks like a
        # permission problem; fail it at load time instead.
        path = self._write("github_pat_aaa bbb\n")
        with self.assertRaises(lw_credential.CredentialError) as ctx:
            lw_credential.load(path)
        self.assertEqual(str(ctx.exception), "credential_value_contains_whitespace")


class RedactionTests(unittest.TestCase):
    def test_repr_and_str_never_contain_the_value(self):
        credential = lw_credential.from_value(FAKE_TOKEN, source="test")
        self.assertNotIn(FAKE_TOKEN, repr(credential))
        self.assertNotIn(FAKE_TOKEN, str(credential))
        self.assertNotIn(FAKE_TOKEN[8:40], repr(credential))
        self.assertIn("<redacted>", repr(credential))

    def test_dataclass_asdict_is_not_accidentally_safe(self):
        # Documents the hazard: the raw field is the token, so nothing may dump the
        # object wholesale. summary() is the only sanctioned projection.
        credential = lw_credential.from_value(FAKE_TOKEN, source="test")
        raw = dataclasses.asdict(credential)
        self.assertEqual(raw["token"], FAKE_TOKEN)
        self.assertNotIn(FAKE_TOKEN, str(credential.summary()))

    def test_summary_has_a_fingerprint_but_no_value(self):
        credential = lw_credential.from_value(FAKE_TOKEN, source="/etc/x.token")
        summary = credential.summary()
        self.assertEqual(summary["class"], "github_pat_")
        self.assertEqual(summary["present"], True)
        self.assertTrue(summary["value_redacted"])
        self.assertNotIn(FAKE_TOKEN, str(summary))
        self.assertTrue(summary["fingerprint"].startswith("sha256:"))
        self.assertEqual(len(summary["fingerprint"]), len("sha256:") + 32)

    def test_fingerprint_is_stable_and_discriminating(self):
        one = lw_credential.token_fingerprint(FAKE_TOKEN)
        two = lw_credential.token_fingerprint(FAKE_TOKEN)
        other = lw_credential.token_fingerprint(FAKE_TOKEN + "X")
        self.assertEqual(one, two)
        self.assertNotEqual(one, other)


class ScopeTests(unittest.TestCase):
    def test_scope_is_actions_contents_metadata_read_only(self):
        self.assertEqual(lw_credential.REQUIRED_PERMISSIONS,
                         {"actions": "read", "contents": "read", "metadata": "read"})

    def test_every_write_scope_is_explicitly_forbidden(self):
        forbidden = lw_credential.FORBIDDEN_PERMISSIONS
        for scope in ("contents:write", "issues:write", "pull_requests:write",
                      "actions:write", "deployments:write", "secrets:write",
                      "workflows:write", "administration:write"):
            self.assertIn(scope, forbidden)

    def test_scope_statement_names_exactly_one_repository(self):
        statement = lw_credential.scope_statement()
        self.assertEqual(statement["repository"], "yuguangzhi3836-glitch/GO")
        self.assertIn("only_select_repositories", statement["repository_access"])

    def test_no_forbidden_scope_appears_in_the_required_set(self):
        for scope, level in lw_credential.REQUIRED_PERMISSIONS.items():
            self.assertEqual(level, "read", scope)


class InstallPlanTests(unittest.TestCase):
    def test_cc_and_hk_have_distinct_paths(self):
        cc = lw_credential.install_plan("cc")
        hk = lw_credential.install_plan("hk")
        self.assertNotEqual(cc["path"], hk["path"])
        self.assertNotIn("requests-reader", cc["path"])

    def test_plan_is_root_only_and_never_restarts_a_service(self):
        for host in ("cc", "hk"):
            plan = lw_credential.install_plan(host)
            self.assertEqual(plan["mode"], "0600")
            self.assertFalse(plan["restart_services"])
            self.assertTrue(plan["directory_permissions_unchanged"])

    def test_unknown_host_is_refused(self):
        with self.assertRaises(lw_credential.CredentialError) as ctx:
            lw_credential.install_plan("prod")
        self.assertEqual(str(ctx.exception), "unknown_host:prod")


class EndpointAllowListTests(unittest.TestCase):
    def test_allow_list_is_read_only(self):
        for endpoint in lw_credential.ALLOWED_ENDPOINTS:
            self.assertTrue(endpoint.startswith("GET "), endpoint)

    def test_allow_list_forbids_the_write_surfaces(self):
        joined = "\n".join(lw_credential.ALLOWED_ENDPOINTS)
        for forbidden in ("POST", "PUT", "PATCH", "DELETE", "issues", "pulls",
                          "dispatches", "merges"):
            self.assertNotIn(forbidden, joined)


if __name__ == "__main__":
    unittest.main(verbosity=2)
