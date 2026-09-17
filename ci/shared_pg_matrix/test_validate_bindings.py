import copy
import json
import pathlib
import unittest

from validate_bindings import validate

HERE = pathlib.Path(__file__).resolve().parent

class BindingTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((HERE / "bindings.json").read_text(encoding="utf-8"))

    def test_exact_manifest_passes(self):
        result = validate(self.data)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["distinct_candidates"], 4)

    def test_original_shared_sha_regression_fails(self):
        broken = copy.deepcopy(self.data)
        c07 = broken["cells"]["C07"]["candidate_sha"]
        for cell in ("C09", "C10", "C11"):
            broken["cells"][cell]["candidate_sha"] = c07
        with self.assertRaisesRegex(ValueError, "DUPLICATE_CELL_CANDIDATE_SHA"):
            validate(broken)

    def test_passed_cell_cannot_be_scheduled_for_retest(self):
        broken = copy.deepcopy(self.data)
        broken["cells"]["C09"]["status"] = "RETEST_REQUIRED"
        with self.assertRaisesRegex(ValueError, "PASSED_CELL_MUST_BE_INHERITED:C09"):
            validate(broken)

    def test_resume_scope_is_c07_only(self):
        broken = copy.deepcopy(self.data)
        broken["policy"]["resume_only"] = ["C07", "C09"]
        with self.assertRaisesRegex(ValueError, "WRONG_RESUME_SCOPE"):
            validate(broken)

    def test_c07_fingerprint_must_be_gate_computed(self):
        broken = copy.deepcopy(self.data)
        broken["cells"]["C07"]["source_tree_fingerprint"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "C07_FINGERPRINT_MUST_BE_GATE_COMPUTED"):
            validate(broken)

if __name__ == "__main__":
    unittest.main()
