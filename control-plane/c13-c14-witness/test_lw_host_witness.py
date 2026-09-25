"""Host-runner tests: the part that only ever runs on CC or HK.

The two things that matter most here are procedural, not cryptographic:

* the runner re-derives the verification itself, so refusing a round that did not
  pass is its default behaviour rather than an option;
* nothing it writes may contain private-key material, because everything it writes
  is meant to leave the host.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import lw_paths  # noqa: E402

lw_paths.install()

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

import lite_fixtures  # noqa: E402
from lite_errors import Reject  # noqa: E402

import lw_chain  # noqa: E402
import lw_host_witness  # noqa: E402
import lw_witness  # noqa: E402

RUNNER = HERE / "lw_host_witness.py"


def key_file(directory, name, seed):
    private = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(seed.encode()).digest())
    path = pathlib.Path(directory) / name
    path.write_bytes(private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    return path


class HostRunnerTests(unittest.TestCase):
    def setUp(self):
        self.directory = pathlib.Path(tempfile.mkdtemp())
        candidate = {
            "sha": lite_fixtures.CANDIDATE_SHA,
            "application_tree": lite_fixtures.APPLICATION_TREE,
            "source": "synthetic-fixture",
            "is_real_commit": False,
        }
        self.package = lw_chain.build_task_package(lite_fixtures.make_round(), candidate=candidate)
        self.cc_key = key_file(self.directory, "cc.pem", "host-test-cc")
        self.hk_key = key_file(self.directory, "hk.pem", "host-test-hk")

    def test_the_runner_produces_a_verifiable_witness(self):
        record, report = lw_host_witness.run(role="cc", package=self.package,
                                             private_key_path=self.cc_key)
        lw_witness.verify_witness(record)
        self.assertEqual(report["verification_decision"], "ACCEPT")
        self.assertTrue(report["witness_signature_present"])
        self.assertEqual(report["key_id"], record["key_id"])
        self.assertEqual(report["witness_purpose"], lw_witness.CC_PURPOSE)

    def test_nothing_written_contains_private_key_material(self):
        record, report = lw_host_witness.run(role="cc", package=self.package,
                                             private_key_path=self.cc_key)
        for payload in (record, report):
            text = json.dumps(payload, ensure_ascii=False)
            self.assertNotIn("PRIVATE KEY", text)
            self.assertNotIn("PRIVATE_KEY", text)
            # The public half is expected — only the private half must be absent.
            self.assertNotIn("BEGIN PRIVATE", text)
        self.assertIs(report["private_key_recorded"], False)

    def test_the_report_carries_only_public_key_facts(self):
        _, report = lw_host_witness.run(role="cc", package=self.package,
                                        private_key_path=self.cc_key)
        self.assertIn("BEGIN PUBLIC KEY", report["public_key_pem"])
        self.assertRegex(report["key_id"], r"^[0-9a-f]{16}$")
        self.assertEqual(report["artifact_binding"],
                         {"c14": lw_witness.ARTIFACT_BINDING_NOT_APPLICABLE,
                          "c13": lw_witness.ARTIFACT_BINDING_NOT_APPLICABLE})

    def test_a_round_that_does_not_pass_is_refused_rather_than_signed(self):
        package = json.loads(json.dumps(self.package))
        package["artifacts"]["junit"] = "dGFtcGVyZWQ="
        record, report = lw_host_witness.run(role="cc", package=package,
                                             private_key_path=self.cc_key)
        self.assertIsNone(record)
        self.assertEqual(report["refused"], "verification_not_accepted")
        self.assertEqual(report["verification_decision"], "REJECT")
        self.assertFalse(report["witness_signature_present"])

    def test_hk_without_a_cc_witness_is_refused(self):
        with self.assertRaises(Reject) as ctx:
            lw_host_witness.run(role="hk", package=self.package,
                                private_key_path=self.hk_key)
        self.assertEqual(ctx.exception.reason, "hk_requires_the_cc_witness")

    def test_a_missing_key_is_a_loud_failure(self):
        with self.assertRaises(FileNotFoundError):
            lw_host_witness.run(role="cc", package=self.package,
                                private_key_path=self.directory / "absent.pem")

    def test_the_carrier_probe_is_absent_unless_requested(self):
        _, report = lw_host_witness.run(role="cc", package=self.package,
                                        private_key_path=self.cc_key)
        self.assertIsNone(report["carrier_probe"])

    def test_a_missing_credential_is_reported_not_raised(self):
        probe = lw_host_witness._carrier_probe(
            credential_path=self.directory / "absent.token", run_id=1,
            expected_head_sha="0" * 40, workflow_path="x.yml", candidate_sha="0" * 40)
        self.assertFalse(probe["performed"])
        self.assertIn("reason", probe)

    def test_the_cli_writes_what_it_prints_it_wrote(self):
        package_path = self.directory / "package.json"
        lw_chain.dump_package(self.package, package_path)
        witness_path = self.directory / "cc_witness.json"
        report_path = self.directory / "cc_report.json"
        completed = subprocess.run(
            [sys.executable, str(RUNNER),
             "--role", "cc",
             "--package", str(package_path),
             "--private-key", str(self.cc_key),
             "--out-witness", str(witness_path),
             "--out-report", str(report_path)],
            capture_output=True, text=True, cwd=str(self.directory),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        printed = json.loads(completed.stdout)
        self.assertTrue(printed["witness_written"])
        self.assertTrue(witness_path.is_file())
        self.assertTrue(report_path.is_file())
        record = json.loads(witness_path.read_text(encoding="utf-8"))
        lw_witness.verify_witness(record)
        self.assertNotIn("PRIVATE KEY", witness_path.read_text(encoding="utf-8"))
        self.assertNotIn("PRIVATE KEY", report_path.read_text(encoding="utf-8"))

    def test_the_cli_exits_nonzero_when_it_refuses(self):
        package = json.loads(json.dumps(self.package))
        package["c14_bundle"]["C14_ROOT"] = "0" * 64
        package_path = self.directory / "bad.json"
        lw_chain.dump_package(package, package_path)
        completed = subprocess.run(
            [sys.executable, str(RUNNER),
             "--role", "cc",
             "--package", str(package_path),
             "--private-key", str(self.cc_key),
             "--out-witness", str(self.directory / "none.json"),
             "--out-report", str(self.directory / "bad_report.json")],
            capture_output=True, text=True, cwd=str(self.directory),
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse((self.directory / "none.json").exists())
        report = json.loads((self.directory / "bad_report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["refused"], "verification_not_accepted")

    def test_hk_cli_consumes_the_cc_witness(self):
        package_path = self.directory / "package.json"
        lw_chain.dump_package(self.package, package_path)
        cc_witness_path = self.directory / "cc_witness.json"
        first = subprocess.run(
            [sys.executable, str(RUNNER), "--role", "cc",
             "--package", str(package_path), "--private-key", str(self.cc_key),
             "--out-witness", str(cc_witness_path),
             "--out-report", str(self.directory / "cc_report.json")],
            capture_output=True, text=True, cwd=str(self.directory))
        self.assertEqual(first.returncode, 0, first.stderr)

        hk_witness_path = self.directory / "hk_witness.json"
        second = subprocess.run(
            [sys.executable, str(RUNNER), "--role", "hk",
             "--package", str(package_path), "--private-key", str(self.hk_key),
             "--cc-witness", str(cc_witness_path),
             "--out-witness", str(hk_witness_path),
             "--out-report", str(self.directory / "hk_report.json")],
            capture_output=True, text=True, cwd=str(self.directory))
        self.assertEqual(second.returncode, 0, second.stderr)
        cc = json.loads(cc_witness_path.read_text(encoding="utf-8"))
        hk = json.loads(hk_witness_path.read_text(encoding="utf-8"))
        lw_witness.verify_witness(hk)
        self.assertNotEqual(cc["key_id"], hk["key_id"])
        self.assertEqual(hk["witness_purpose"], lw_witness.HK_PURPOSE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
