"""The key battery must be able to say NO.

A tool like this is only worth running at rotation time if its failure modes actually
fire, so every test below either proves a check passes on a correct key or proves the
check trips on a deliberately broken one.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import lw_paths  # noqa: E402

lw_paths.install()

import lite_errors  # noqa: E402
import lw_keycheck  # noqa: E402

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: E402
    Ed25519PrivateKey,
)
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key  # noqa: E402

WITNESS_PRIVATE = "c13-c14-witness-ed25519.pem"
WITNESS_PUBLIC = "c13-c14-witness-ed25519.pub"


def write_key_pair(directory: pathlib.Path, basename: str, *, seed: str):
    """Write a deterministic Ed25519 key pair in the layout the hosts use."""
    private = Ed25519PrivateKey.from_private_bytes(
        hashlib.sha256(seed.encode("utf-8")).digest())
    (directory / f"{basename}.pem").write_bytes(private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    (directory / f"{basename}.pub").write_bytes(
        private.public_key().public_bytes(
            serialization.Encoding.OpenSSH,
            serialization.PublicFormat.OpenSSH) + b"\n")
    return private


class KeycheckTests(unittest.TestCase):
    def setUp(self):
        self.directory = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.directory, True))

    def check(self, **kwargs):
        options = dict(key_dir=self.directory,
                       private_path=self.directory / WITNESS_PRIVATE,
                       public_path=self.directory / WITNESS_PUBLIC)
        options.update(kwargs)
        return lw_keycheck.keycheck("cc", **options)

    def install_good_pair(self, *, seed="witness-key-cc"):
        write_key_pair(self.directory, "c13-c14-witness-ed25519", seed=seed)
        # An unrelated pre-existing key, exactly as the hosts have one.
        write_key_pair(self.directory, "task-manifest-signing", seed="cc-task-key")

    def test_a_correct_key_passes_every_check(self):
        self.install_good_pair()
        report = self.check()
        failing = [name for name, ok in report["checks"].items() if not ok]
        self.assertEqual(failing, [], report)
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(report["purpose"], "c13c14-acceptance-witness")
        self.assertEqual(len(report["key_id"]), 16)
        self.assertTrue(report["fingerprint"].startswith("sha256:"))
        self.assertTrue(report["public_key_openssh"].startswith("ssh-ed25519 "))

    def test_both_signature_rejections_are_exercised(self):
        self.install_good_pair()
        checks = self.check()["checks"]
        self.assertTrue(checks["witness_sign_verify_positive"])
        self.assertTrue(checks["witness_verify_rejects_modified_payload"])
        self.assertTrue(checks["witness_verify_rejects_modified_signature"])
        self.assertTrue(checks["openssl_verifies_our_signature"])
        self.assertTrue(checks["openssl_rejects_modified_payload"])

    def test_the_algorithm_is_confirmed_by_both_toolchains(self):
        self.install_good_pair()
        checks = self.check()["checks"]
        self.assertTrue(checks["cryptography_sees_ed25519_private"])
        self.assertTrue(checks["openssl_sees_ed25519"])
        self.assertTrue(checks["openssl_oid_is_ed25519"])
        self.assertTrue(checks["public_key_is_ed25519"])

    def test_a_mismatched_public_key_on_disk_fails(self):
        self.install_good_pair()
        other = Ed25519PrivateKey.from_private_bytes(b"\x01" * 32)
        (self.directory / WITNESS_PUBLIC).write_bytes(
            other.public_key().public_bytes(
                serialization.Encoding.OpenSSH,
                serialization.PublicFormat.OpenSSH) + b"\n")
        report = self.check()
        self.assertEqual(report["verdict"], "FAIL")
        self.assertFalse(report["checks"]["derived_public_matches_disk"])

    def test_reuse_of_an_existing_key_is_detected(self):
        """The same key under two names is exactly what 'no reuse' forbids."""
        write_key_pair(self.directory, "c13-c14-witness-ed25519", seed="shared-seed")
        write_key_pair(self.directory, "task-manifest-signing", seed="shared-seed")
        report = self.check()
        self.assertEqual(report["verdict"], "FAIL")
        self.assertFalse(report["checks"]["no_reuse_of_an_existing_key"])
        self.assertEqual(report["reused_from"], ["task-manifest-signing.pub"])

    def test_a_distinct_key_is_not_flagged_as_reuse(self):
        self.install_good_pair()
        report = self.check()
        self.assertTrue(report["checks"]["no_reuse_of_an_existing_key"])
        self.assertEqual(report["reused_from"], [])
        self.assertIn("task-manifest-signing.pub", report["other_public_keys"])

    def test_the_other_hosts_key_is_compared_by_fingerprint_only(self):
        self.install_good_pair()
        own = self.check()["fingerprint"]
        report = self.check(other_host_fingerprints={"hk-other": own})
        self.assertFalse(report["checks"]["differs_from_the_other_host"])
        report2 = self.check(other_host_fingerprints={"hk-other": "sha256:" + "0" * 64})
        self.assertTrue(report2["checks"]["differs_from_the_other_host"])

    def test_a_non_ed25519_key_is_refused(self):
        rsa = generate_private_key(public_exponent=65537, key_size=1024)
        (self.directory / WITNESS_PRIVATE).write_bytes(rsa.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))
        (self.directory / WITNESS_PUBLIC).write_bytes(b"ssh-rsa AAAA\n")
        with self.assertRaises(lite_errors.Reject) as ctx:
            self.check()
        self.assertEqual(ctx.exception.reason, "witness_key_wrong_algorithm")

    def test_a_missing_key_is_a_failure_not_a_crash(self):
        report = self.check()
        self.assertEqual(report["verdict"], "FAIL")
        self.assertFalse(report["checks"]["private_exists"])

    @unittest.skipUnless(os.name == "posix", "permission bits are POSIX-only")
    def test_a_loose_private_mode_is_refused(self):
        self.install_good_pair()
        (self.directory / WITNESS_PRIVATE).chmod(0o644)
        report = self.check()
        self.assertEqual(report["verdict"], "FAIL")
        self.assertFalse(report["checks"]["private_mode_is_0600"])
        self.assertFalse(report["checks"]["private_not_group_or_world_accessible"])

    def test_the_report_never_carries_the_private_key(self):
        self.install_good_pair()
        report = self.check()
        serialised = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("PRIVATE KEY", serialised)
        private_pem = (self.directory / WITNESS_PRIVATE).read_text(encoding="utf-8")
        body = private_pem.splitlines()[1]
        self.assertNotIn(body, serialised)

    def test_a_private_key_file_is_never_opened_as_an_existing_public_key(self):
        """Only .pub and -public.pem are read; a .pem or .token is left alone."""
        self.install_good_pair()
        (self.directory / "some-token.token").write_text("github_pat_" + "x" * 30,
                                                         encoding="utf-8")
        report = self.check()
        self.assertNotIn("some-token.token", report["other_public_keys"])
        self.assertNotIn("task-manifest-signing.pem", report["other_public_keys"])

    def test_custody_check_is_gated_on_a_posix_host(self):
        self.install_good_pair()
        report = self.check()
        if os.name == "posix":
            self.assertTrue(report["custody_checked"])
            self.assertIn("private_mode_is_0600", report["checks"])
        else:
            self.assertFalse(report["custody_checked"])
            self.assertNotIn("private_mode_is_0600", report["checks"])
            self.assertIn("custody_check_skipped", report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
