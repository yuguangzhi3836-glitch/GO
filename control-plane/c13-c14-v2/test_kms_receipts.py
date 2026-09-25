"""Fake cloud transport + ephemeral EC keys; no cloud call or real receipt."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

from acceptance_gate import Refusal
from c14_isolated_runner import execute
from control_receipt_route import ControlReceiptRoute, ReceiptStore
from house_bridge import canonical, issue, receive_evidence
from kms_receipts import KmsReceiptSigner, crc32c
from test_c14_isolated_runner import PINNED_REQUEST, RunnerHost

VERSION = "projects/test-only/locations/test/keyRings/test/cryptoKeys/test/cryptoKeyVersions/1"


class FakeKms:
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        public = self.key.public_key()
        self.pem = public.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        der = public.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        self.fingerprint = hashlib.sha256(der).hexdigest()
        self.public_changes, self.signature_changes = {}, {}
        self.sign_calls = 0

    def get_public_key(self, *, request, retry, timeout):
        assert request == {"name": VERSION} and retry is None and timeout == 10
        result = dict(name=VERSION, pem=self.pem.decode(), pem_crc32c=crc32c(self.pem),
                      algorithm="EC_SIGN_P256_SHA256", protection_level="HSM")
        return SimpleNamespace(**(result | self.public_changes))

    def asymmetric_sign(self, *, request, retry, timeout):
        assert request["name"] == VERSION and retry is None and timeout == 10
        digest = request["digest"]["sha256"]
        assert request["digest_crc32c"] == crc32c(digest)
        self.sign_calls += 1
        signature = self.key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        result = dict(name=VERSION, protection_level="HSM", verified_digest_crc32c=True,
                      signature=signature, signature_crc32c=crc32c(signature))
        return SimpleNamespace(**(result | self.signature_changes))


class KmsReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cloud = FakeKms()
        self.signer = KmsReceiptSigner(self.cloud, VERSION, self.cloud.fingerprint)
        self.store = ReceiptStore(Path(self.tmp.name))
        self.route = ControlReceiptRoute(self.signer, self.store)
        self.host = RunnerHost()
        for name in ("sign_control_receipt", "verify_control_receipt", "read_control_receipt", "publish_control_receipt"):
            setattr(self.host, name, getattr(self.route, name))
        self.task = issue(PINNED_REQUEST, "C14", 100, self.host)
        execute(self.task, 101, self.host)

    def receipt(self):
        return receive_evidence(self.task, 101, self.host)["receipt"]

    def test_crc32c_known_vector(self):
        self.assertEqual(crc32c(b"123456789"), 0xE3069283)
        self.assertEqual(crc32c(b""), 0)

    def test_verified_crypto_receipt_persisted_and_reused_without_resigning(self):
        receipt = self.receipt()
        self.assertEqual(receipt["verdict"], "PASS_SCOPED")  # synthetic runner only
        self.assertEqual(self.cloud.sign_calls, 1)
        self.assertEqual(self.receipt(), receipt)
        self.assertEqual(self.cloud.sign_calls, 1)
        reopened = ReceiptStore(Path(self.tmp.name))
        self.assertEqual(reopened.read(self.task["task_id"], self.task["nonce"]), canonical(receipt) + b"\n")
        self.assertEqual(len(list(Path(self.tmp.name).iterdir())), 1)

    def test_public_key_version_algorithm_hsm_crc_and_fingerprint_refused(self):
        for changes in ({"name": VERSION + "0"}, {"algorithm": "EC_SIGN_P384_SHA384"},
                        {"protection_level": "SOFTWARE"}, {"pem_crc32c": 0}, {"pem": "bad"}):
            self.cloud.public_changes = changes
            with self.subTest(changes=changes), self.assertRaises(Refusal):
                self.receipt()
        self.cloud.public_changes = {}
        self.signer.fingerprint = "0" * 64
        with self.assertRaisesRegex(Refusal, "fingerprint"):
            self.receipt()
        self.assertEqual(self.cloud.sign_calls, 0)

    def test_sign_response_integrity_failure_never_publishes(self):
        for changes in ({"name": VERSION + "0"}, {"protection_level": "SOFTWARE"},
                        {"verified_digest_crc32c": False}, {"signature_crc32c": 0},
                        {"signature": b"invalid", "signature_crc32c": crc32c(b"invalid")}):
            self.cloud.signature_changes = changes
            with self.subTest(changes=changes), self.assertRaisesRegex(Refusal, "kms_signature_response"):
                self.receipt()
            self.assertIsNone(self.route.read_control_receipt(self.task["task_id"], self.task["nonce"]))

    def test_valid_checksum_cannot_hide_wrong_signing_key(self):
        other = ec.generate_private_key(ec.SECP256R1())
        self.cloud.key = other
        with self.assertRaisesRegex(Refusal, "kms_signature_response"):
            self.receipt()

    def test_cloud_unavailable_is_hold_not_software_fallback(self):
        def unavailable(**kwargs):
            raise TimeoutError("test transport timeout")
        self.cloud.asymmetric_sign = unavailable
        with self.assertRaisesRegex(Refusal, "kms_sign_unavailable"):
            self.receipt()
        self.assertIsNone(self.route.read_control_receipt(self.task["task_id"], self.task["nonce"]))

    def test_arbitrary_payload_and_mutable_version_refused(self):
        with self.assertRaisesRegex(Refusal, "kms_host_binding"):
            KmsReceiptSigner(self.cloud, VERSION.rsplit("/", 1)[0] + "/primary", self.cloud.fingerprint)
        for raw in (b"sign this", canonical({"action_id": "HK_STAGING_DEPLOY"})):
            with self.assertRaisesRegex(Refusal, "kms_receipt_schema"):
                self.signer.sign_control_receipt(raw)
        self.assertEqual(self.cloud.sign_calls, 0)

    def test_receipt_tamper_and_path_rebinding_refused(self):
        receipt = self.receipt()
        with self.assertRaisesRegex(Refusal, "receipt_route_binding"):
            self.route.publish_control_receipt("different-task", self.task["nonce"], canonical(receipt) + b"\n")
        receipt["verified_at"] = "1970-01-01T00:01:42Z"
        with self.assertRaisesRegex(Refusal, "receipt_route_signature"):
            self.route.publish_control_receipt(self.task["task_id"], self.task["nonce"], canonical(receipt) + b"\n")

    def test_conflicting_publication_does_not_overwrite(self):
        self.receipt()
        task, nonce = self.task["task_id"], self.task["nonce"]
        original = self.store.read(task, nonce)
        with self.assertRaisesRegex(Refusal, "receipt_store_conflict"):
            self.store.publish(task, nonce, b"different")
        self.assertEqual(self.store.read(task, nonce), original)

    def test_missing_or_insecure_directory_fails_closed(self):
        missing = Path(self.tmp.name) / "missing"
        with self.assertRaisesRegex(Refusal, "receipt_store_io"):
            ReceiptStore(missing).read("task", "nonce")
        self.assertFalse(missing.exists())
        Path(self.tmp.name).chmod(0o755)
        with self.assertRaisesRegex(Refusal, "receipt_store_permissions"):
            self.store.read("task", "nonce")

    def test_concurrent_publish_has_one_immutable_winner(self):
        def publish(number):
            raw = str(number).encode()
            try:
                self.store.publish("competing-task", "same-nonce", raw)
                return raw
            except Refusal as exc:
                self.assertEqual(str(exc), "receipt_store_conflict")
                return None
        with ThreadPoolExecutor(max_workers=8) as workers:
            results = list(workers.map(publish, range(8)))
        winners = [raw for raw in results if raw is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(self.store.read("competing-task", "same-nonce"), winners[0])

    def test_stored_receipt_corruption_and_symlink_cannot_be_accepted(self):
        self.receipt()
        path = next(Path(self.tmp.name).glob("*.json"))
        original = path.read_bytes()
        path.write_bytes(b"corrupted")
        with self.assertRaisesRegex(Refusal, "receipt_readback"):
            self.receipt()
        path.unlink()
        other = Path(self.tmp.name) / "other"
        other.write_bytes(original)
        path.symlink_to(other)
        with self.assertRaisesRegex(Refusal, "receipt_store_io"):
            self.receipt()


if __name__ == "__main__":
    unittest.main()
