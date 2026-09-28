import json
from pathlib import Path
import tempfile
import unittest

from writer import EvidenceError, canonical_json, verify_bundle, write_bundle


HERE = Path(__file__).resolve().parent
CASES = json.loads((HERE / "revalidation_cases.json").read_text())


class EvidenceWriterTests(unittest.TestCase):
    def source(self, root: Path, value: str = "source") -> list[str]:
        path = root / "application" / "identity.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
        return ["application/identity.txt"]

    def binding(self, **overrides):
        value = dict(CASES[0])
        value.update(overrides)
        return value

    def create(self, root: Path, binding=None):
        binding = binding or self.binding()
        return write_bundle(
            root / "bundle",
            source_root=root,
            source_paths=self.source(root, binding["cell"]),
            cell=binding["cell"],
            task_id=binding["task_id"],
            candidate_commit=binding["candidate_commit"],
            application_tree=binding["application_tree"],
            product_source_fingerprint_sha256=binding["product_source_fingerprint_sha256"],
            json_documents={"RESULT.json": {"cell": binding["cell"], "status": "PASS"}},
            payload_files={"raw.log": b"task-bound PASS\n"},
        )

    def test_strict_json_real_newline_atomic_bundle_and_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = self.create(root)
            bundle = root / "bundle"
            for path in bundle.glob("*.json"):
                data = path.read_bytes()
                self.assertTrue(data.endswith(bytes([10])))
                self.assertFalse(data.endswith(b"\\n"))
                self.assertEqual(data, canonical_json(json.loads(data)))
            self.assertEqual(report, verify_bundle(bundle) | {
                "pre_publish_sha256sums_sha256": report["sha256sums_sha256"]
            })

    def test_literal_backslash_n_json_fails_before_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(EvidenceError, "INVALID_JSON"):
                write_bundle(
                    root / "bundle",
                    source_root=root,
                    source_paths=self.source(root),
                    payload_files={"RESULT.json": b'{"status":"PASS"}\\n'},
                    json_documents={},
                    **{k: self.binding()[k] for k in (
                        "cell", "task_id", "candidate_commit", "application_tree",
                        "product_source_fingerprint_sha256"
                    )},
                )
            self.assertFalse((root / "bundle").exists())

    def test_existing_target_and_binding_mismatch_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create(root)
            with self.assertRaisesRegex(EvidenceError, "TARGET_ALREADY_EXISTS"):
                self.create(root)
            with self.assertRaisesRegex(EvidenceError, "SOURCE_BINDING_CANDIDATE_COMMIT_MISMATCH"):
                verify_bundle(root / "bundle", expected_candidate="0" * 40)

    def test_tamper_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create(root)
            (root / "bundle" / "raw.log").write_bytes(b"tampered\n")
            with self.assertRaisesRegex(EvidenceError, "SHA256_MISMATCH"):
                verify_bundle(root / "bundle")

    def test_c02_c07_c08_c04_unified_revalidation(self):
        for case in CASES:
            with self.subTest(cell=case["cell"]), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.create(root, case)
                report = verify_bundle(
                    root / "bundle",
                    expected_candidate=case["candidate_commit"],
                    expected_application_tree=case["application_tree"],
                    expected_cell=case["cell"],
                    expected_task_id=case["task_id"],
                )
                binding = json.loads((root / "bundle" / "SOURCE_BINDING.json").read_text())
                self.assertEqual(
                    binding["product_source_fingerprint_sha256"],
                    case["product_source_fingerprint_sha256"],
                )
                self.assertEqual(report["schema"], "go.shared-evidence.bundle.v1")


if __name__ == "__main__":
    unittest.main()
