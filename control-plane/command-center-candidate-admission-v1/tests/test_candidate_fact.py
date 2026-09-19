"""WP-1 acceptance: the converged candidate fact, its digest, and legacy READ_OLD.

CCV1-83 / WP-1 + transition T1. Two things are being proven here:

1. **One candidate identity.** `go.release-candidate.v1` is the authoritative
   candidate fact, its digest has exactly one implementation
   (`candidate_fact.candidate_contract_sha256`), the digest is stable under key
   order and formatting, and it changes when any candidate fact changes. A
   candidate that declares the prohibited migration condition has no digest at all.

2. **The legacy contract is readable and nothing more.** The three Hong Kong
   candidate contracts can still be *read* so history stays interpretable, they can
   never be written, and a legacy digest can never be presented as a converged one.

Standard library only. No network, no Git, no subprocess, no runtime credential or
state path, no live Control Plane or Hong Kong contact.
"""
import importlib.machinery
import importlib.util
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import candidate_fact as cf  # noqa: E402
import legacy_candidate_contract as lg  # noqa: E402

loader = importlib.machinery.SourceFileLoader(
    "go_candidate_admission_wp1", str(ROOT / "command-center" / "go-candidate-admission"))
spec = importlib.util.spec_from_loader(loader.name, loader)
A = importlib.util.module_from_spec(spec)
loader.exec_module(A)

CONTRACT = ROOT / A.CONTRACT_FILE

COMMIT = "b" * 40
TREE = "c" * 40
FINGERPRINT = "d" * 64
ARTIFACT = "sha256:" + "e" * 64
OTHER_ARTIFACT = "sha256:" + "f" * 64
KNOWN_GOOD = "sha256:" + "2" * 64


def converged(**over):
    """The frozen candidate the digest vectors are computed over."""
    return {
        "schema": cf.SCHEMA,
        "candidate_id": "rc1-wp1-vector",
        "source_repository": cf.CANDIDATE_REPOSITORY,
        "source_commit": COMMIT,
        "application_tree": TREE,
        "source_fingerprint": FINGERPRINT,
        "migration_head": "0133_flight_change_plan",
        "migration_required": False,
        "build_definition": {
            "profile": "go-application-python-v1",
            "dockerfile": "Dockerfile.go-application-python-v2",
            "dockerfile_sha256": "f" * 64,
            "executor_version": "test-pr-v3",
            "builder_image_tag": "go-hotel:depth48-runtime-6d0fd905",
            "builder_image_id": "sha256:" + "1" * 64,
        },
        "artifact_digest": ARTIFACT,
        "required_services": ["api", "recovery-worker", "outbox-worker",
                              "mobile-push-receipt-worker", "reconciliation-worker",
                              "mobile-push-worker", "mobile-engagement-worker",
                              "judgment-worker"],
        "test_result_identity": {
            "action_id": "HK_STAGING_TEST_PR",
            "task_id": "go-boss-test-pr-99-wp1-vector",
            "evidence_id": "wp1-vector-evidence-commit",
            "source_pr_number": "99",
            "source_commit_sha": COMMIT,
            "artifact_digest": ARTIFACT,
            "executor_result": "TEST_PR_OK",
        },
        "rollback_relation": {
            "relation": "REPLACES_CURRENT_KNOWN_GOOD",
            "previous_known_good_image_id": KNOWN_GOOD,
        },
    } | over


# The frozen vector. If this changes, the identity every component agrees on has
# changed, which is a contract event and not a refactor.
FIXED_VECTOR_DIGEST = "7fa447e80f8a155f9d25fb751b158dfb52354818ab3383fbe1a2c44f6c3bb00d"
FIXED_VECTOR_BYTES = 1565


# --------------------------------------------------------------------------- #
# the digest
# --------------------------------------------------------------------------- #
class DigestVectorTests(unittest.TestCase):
    def test_the_frozen_vector_is_unchanged(self):
        """The one value that must never move silently."""
        candidate = converged()
        self.assertEqual(cf.candidate_contract_sha256(candidate), FIXED_VECTOR_DIGEST)
        self.assertEqual(len(cf.canonical_candidate_bytes(candidate)), FIXED_VECTOR_BYTES)

    def test_good_vector_1_key_order_does_not_matter(self):
        candidate = converged()
        reordered = dict(reversed(list(candidate.items())))
        reordered["build_definition"] = dict(
            reversed(list(candidate["build_definition"].items())))
        self.assertEqual(cf.candidate_contract_sha256(candidate),
                         cf.candidate_contract_sha256(reordered))

    def test_good_vector_2_pretty_printed_and_compact_agree(self):
        candidate = converged()
        pretty = json.dumps(candidate, indent=4, sort_keys=False)
        compact = json.dumps(candidate, separators=(",", ":"), sort_keys=True)
        self.assertEqual(cf.candidate_contract_sha256(json.loads(pretty)),
                         cf.candidate_contract_sha256(json.loads(compact)))
        self.assertEqual(cf.candidate_contract_sha256(json.loads(pretty)),
                         FIXED_VECTOR_DIGEST)

    def test_insignificant_whitespace_does_not_matter(self):
        """Structural whitespace only: a naive string replace would land inside
        values such as `sha256:...` and change the candidate instead."""
        candidate = converged()
        padded = json.dumps(candidate, separators=("  ,  ", "  :  "), indent=3)
        self.assertEqual(cf.candidate_contract_sha256(json.loads(padded)),
                         FIXED_VECTOR_DIGEST)

    def test_bad_vector_1_a_source_commit_change_changes_the_digest(self):
        other = converged(source_commit="b" * 39 + "a")
        self.assertNotEqual(cf.candidate_contract_sha256(other), FIXED_VECTOR_DIGEST)

    def test_bad_vector_2_an_artifact_change_changes_the_digest(self):
        other = converged(artifact_digest=OTHER_ARTIFACT)
        self.assertNotEqual(cf.candidate_contract_sha256(other), FIXED_VECTOR_DIGEST)

    def test_bad_vector_3_a_migration_head_change_changes_the_digest(self):
        other = converged(migration_head="0134_other_head")
        self.assertNotEqual(cf.candidate_contract_sha256(other), FIXED_VECTOR_DIGEST)

    def test_the_optional_package_is_part_of_the_fact_when_present(self):
        """Present and absent are different facts, so they digest differently."""
        without = converged()
        with_package = converged(artifact_package={
            "durability": "PROVEN", "package_sha256": "a" * 64})
        self.assertNotEqual(cf.candidate_contract_sha256(without),
                            cf.candidate_contract_sha256(with_package))

    def test_the_digest_is_utf8_stable(self):
        candidate = converged(candidate_id="rc1-utf8-\u6d4b\u8bd5")
        raw = cf.canonical_candidate_bytes(candidate)
        self.assertIn("\u6d4b\u8bd5", raw.decode("utf-8"))
        self.assertEqual(len(cf.candidate_contract_sha256(candidate)), 64)

    def test_a_non_json_number_is_refused_rather_than_digested(self):
        """`allow_nan=False`: an unreadable byte form is never produced."""
        broken = converged()
        broken["migration_head"] = float("nan")
        with self.assertRaises(ValueError):
            cf.canonical_candidate_bytes(broken)


# --------------------------------------------------------------------------- #
# the converged fact itself
# --------------------------------------------------------------------------- #
class ConvergedFactTests(unittest.TestCase):
    def test_a_complete_candidate_is_valid(self):
        self.assertIs(cf.validate_converged(converged()) is not None, True)

    def test_migration_required_false_is_the_only_accepted_value(self):
        self.assertIs(converged()["migration_required"], False)
        self.assertEqual(len(cf.candidate_contract_sha256(converged())), 64)

    def test_migration_required_true_is_refused_and_has_no_digest(self):
        """The fact layer reports the same public code as the admission layer.

        A caller must not be able to tell which layer noticed first, and must not have
        to match on two spellings of one condition.
        """
        for wrong in (True, 0, None, "false"):
            with self.assertRaises(cf.CandidateFactError) as caught:
                cf.candidate_contract_sha256(converged(migration_required=wrong))
            self.assertEqual(str(caught.exception), cf.E_DATABASE_MIGRATION_REQUIRED)
        self.assertEqual(cf.E_DATABASE_MIGRATION_REQUIRED, "E_DATABASE_MIGRATION_REQUIRED")
        self.assertEqual(cf.E_DATABASE_MIGRATION_GRAPH_MISMATCH,
                         "E_DATABASE_MIGRATION_GRAPH_MISMATCH")

    def test_an_unknown_field_is_refused(self):
        with self.assertRaises(cf.CandidateFactError) as caught:
            cf.validate_converged(converged(topology={"topology_version": 2}))
        self.assertTrue(str(caught.exception).startswith("candidate_fields_unknown:"))

    def test_a_missing_field_is_refused(self):
        broken = converged()
        del broken["rollback_relation"]
        with self.assertRaises(cf.CandidateFactError) as caught:
            cf.validate_converged(broken)
        self.assertTrue(str(caught.exception).startswith("candidate_fields_missing:"))

    def test_the_field_set_is_owned_by_one_place(self):
        self.assertEqual(set(cf.CONVERGED_REQUIRED_FIELDS),
                         set(A.RELEASE_CANDIDATE_FIELDS))
        self.assertEqual(tuple(cf.CONVERGED_OPTIONAL_FIELDS),
                         tuple(A.OPTIONAL_FIELDS))

    def test_the_admission_uses_the_shared_canonical_rule(self):
        value = {"b": 1, "a": [2, 3]}
        self.assertEqual(A.canonical(value), cf.canonical_bytes(value))

    def test_the_schema_pins_the_prohibited_condition_to_false(self):
        document = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(document["properties"]["migration_required"]["const"], False)
        self.assertIn("PROHIBITED_CONDITION_DECLARATION",
                      document["properties"]["migration_required"]["description"])
        self.assertIn("migration_required", document["required"])
        self.assertEqual(set(document["required"]), set(cf.CONVERGED_REQUIRED_FIELDS))


# --------------------------------------------------------------------------- #
# legacy READ_OLD
# --------------------------------------------------------------------------- #
def legacy_v1():
    return {
        "schema": lg.SCHEMA_V1,
        "environment": "HK-STAGING-01",
        "profile": "go-application-python-v2",
        "candidate": {
            "repository": cf.CANDIDATE_REPOSITORY,
            "source_commit": COMMIT,
            "application_git_tree": TREE,
            "source_tree_sha256": "9" * 64,
            "package_sha256": "8" * 64,
            "image_id": ARTIFACT,
        },
        "expected_current_image_id": KNOWN_GOOD,
        "baseline_revision": "0133_flight_change_plan",
        "target_revision": "0134_next_head",
        "rehearsal": {"schema": "go.hk-migration-rehearsal.v1", "status": "PASS_SCOPED"},
        "rehearsal_sha256": "7" * 64,
    }


def legacy_v2():
    value = {
        "schema": lg.SCHEMA_V2,
        "environment": "HK-STAGING-01",
        "profile": "go-application-python-v2",
        "candidate": {
            "repository": cf.CANDIDATE_REPOSITORY,
            "source_commit": COMMIT,
            "application_git_tree": TREE,
            "source_tree_sha256": "9" * 64,
            "package_sha256": "8" * 64,
            "image_id": ARTIFACT,
        },
        "expected_current_image_id": KNOWN_GOOD,
        "baseline_revision": "0133_flight_change_plan",
        "target_revision": "0133_flight_change_plan",
        "migration_required": False,
        "migration_source_digest": "6" * 64,
        "baseline_migration_source_digest": "6" * 64,
        "test_pr_evidence_sha256": "5" * 64,
    }
    return value


def legacy_v3():
    value = legacy_v2()
    value["schema"] = lg.SCHEMA_V3
    value["topology"] = {
        "topology_id": "HK_STAGING_BUSINESS_TOPOLOGY",
        "topology_version": 2,
        "topology_sha256": "3efa422ebcfeee97528e829228a5f1c78a91151c88c50c606bab95479f3fddb1",
        "baseline_topology_version": 1,
        "media_rollback_compatible": True,
    }
    return value


class LegacyReadTests(unittest.TestCase):
    def test_the_legacy_read_only_contract_is_declared(self):
        declared = lg.assert_legacy_is_read_only()
        self.assertIs(declared["legacy_read_only"], True)
        self.assertIs(declared["legacy_writes_allowed"], False)
        self.assertEqual(declared["retire_at"], "T10")
        self.assertEqual(tuple(declared["legacy_schemas"]), lg.LEGACY_SCHEMAS)

    def test_legacy_v1_v2_v3_are_readable(self):
        for document, kind in ((legacy_v1(), cf.CandidateDigestKind.LEGACY_V1),
                               (legacy_v2(), cf.CandidateDigestKind.LEGACY_V2),
                               (legacy_v3(), cf.CandidateDigestKind.LEGACY_V3)):
            view = lg.read_legacy(document)
            self.assertEqual(view["kind"], kind)
            self.assertEqual(view["schema"], document["schema"])
            self.assertIs(view["read_only"], True)
            self.assertEqual(view["retire_at"], "T10")

    def test_a_legacy_document_is_recognised_and_never_converged(self):
        document = legacy_v2()
        self.assertTrue(lg.is_legacy(document))
        self.assertFalse(lg.is_legacy(converged()))
        self.assertEqual(cf.classify_document(document),
                         cf.CandidateDigestKind.LEGACY_V2)
        self.assertEqual(cf.classify_document(converged()),
                         cf.CandidateDigestKind.CONVERGED)

    def test_a_malformed_legacy_document_is_refused_not_half_read(self):
        document = legacy_v2()
        document["surprise"] = 1
        with self.assertRaises(lg.LegacyContractError) as caught:
            lg.read_legacy(document)
        self.assertTrue(str(caught.exception).startswith("legacy_fields_unknown:"))

    def test_v1_without_its_rehearsal_is_refused(self):
        document = legacy_v1()
        del document["rehearsal"]
        with self.assertRaises(lg.LegacyContractError):
            lg.read_legacy(document)

    def test_v3_without_its_topology_is_refused(self):
        document = legacy_v3()
        del document["topology"]
        with self.assertRaises(lg.LegacyContractError):
            lg.read_legacy(document)

    def test_a_legacy_document_cannot_be_read_as_a_converged_fact(self):
        with self.assertRaises(cf.CandidateFactError):
            cf.validate_converged(legacy_v2())

    def test_the_mapping_table_is_explicit_and_uses_known_actions(self):
        actions = {"MAP", "MAP_TO_PACKAGE", "NOT_CANDIDATE_FACT", "GAP"}
        self.assertTrue(lg.LEGACY_FIELD_MAP)
        for entry in lg.LEGACY_FIELD_MAP:
            self.assertIn(entry["action"], actions, entry)
            self.assertTrue(entry["legacy"] or entry["converged"], entry)

    def test_the_known_mapping_gaps_are_reported(self):
        """Six identities a converged candidate must state that legacy cannot."""
        self.assertEqual(set(lg.LEGACY_MAPPING_GAPS),
                         {"source_fingerprint", "candidate_id", "build_definition",
                          "required_services", "test_result_identity",
                          "rollback_relation"})

    def test_source_tree_sha256_is_not_silently_mapped_to_source_fingerprint(self):
        entry = [e for e in lg.LEGACY_FIELD_MAP
                 if e["legacy"] == "candidate.source_tree_sha256"][0]
        self.assertEqual(entry["action"], "GAP")
        self.assertIn("NOT loss-free", entry["note"])

    def test_the_non_candidate_fields_are_kept_out_of_the_fact(self):
        shared = ("expected_current_image_id", "baseline_revision", "target_revision",
                  "environment", "profile")
        only_v1 = ("rehearsal", "rehearsal_sha256")
        only_v3 = ("topology", "migration_source_digest",
                   "baseline_migration_source_digest", "test_pr_evidence_sha256")
        for document, extra in ((legacy_v1(), only_v1), (legacy_v3(), only_v3)):
            view = lg.read_legacy(document)
            for name in shared + extra:
                self.assertIn(name, view["not_candidate_facts"], name)
                self.assertNotIn(name, view["facts"], name)

    def test_a_legacy_view_cannot_be_promoted(self):
        partial = lg.converged_partial(lg.read_legacy(legacy_v3()))
        self.assertFalse(partial["promotable"])
        self.assertEqual(set(partial["gaps"]), set(lg.LEGACY_MAPPING_GAPS))
        with self.assertRaises(cf.CandidateFactError):
            cf.candidate_contract_sha256(partial["supplied"])

    def test_a_v1_document_declares_the_prohibited_condition(self):
        view = lg.read_legacy(legacy_v1())
        self.assertIs(view["facts"]["migration_required"], True)


# --------------------------------------------------------------------------- #
# no legacy writer on the new path
# --------------------------------------------------------------------------- #
class NoLegacyWriterTests(unittest.TestCase):
    def _sources(self):
        return sorted(p for p in ROOT.rglob("*.py")
                      if "tests" not in p.parts and "__pycache__" not in p.parts) + [
            ROOT / "command-center" / "go-candidate-admission"]

    # Exactly two files may name a legacy schema: the reader, and the classifier
    # that has to recognise one in order to tag its kind. Nothing else may.
    SCHEMA_NAMERS = {"legacy_candidate_contract.py", "candidate_fact.py"}

    def test_only_the_reader_and_the_classifier_name_a_legacy_schema(self):
        namers = set()
        for path in self._sources():
            text = path.read_text(encoding="utf-8")
            if any(schema in text for schema in lg.LEGACY_SCHEMAS):
                namers.add(path.name)
        self.assertEqual(namers, self.SCHEMA_NAMERS)

    def test_the_classifier_only_classifies(self):
        """Recognising a legacy schema must not mean being able to write one."""
        text = (ROOT / "candidate_fact.py").read_text(encoding="utf-8")
        self.assertIn("LEGACY_SCHEMA_TO_KIND", text)
        for forbidden in ("open(", ".write", "pathlib", "os.replace", "os.rename"):
            self.assertNotIn(forbidden, text, forbidden)

    def test_the_new_path_does_not_import_the_legacy_reader(self):
        for name in ("command-center/go-candidate-admission", "candidate_fact.py"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("import legacy_candidate_contract", text, name)

    def test_nothing_writes_a_legacy_store(self):
        for path in self._sources():
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("candidate-contracts-v1", text, path.name)
            self.assertNotIn("active-candidate-v1", text, path.name)


# --------------------------------------------------------------------------- #
# the Hong Kong side check
# --------------------------------------------------------------------------- #
class CandidateDigestVerificationTests(unittest.TestCase):
    def test_hk_accepts_the_digest_of_the_candidate_it_was_given(self):
        candidate = converged()
        parameters = {"candidate_contract_sha256":
                      cf.candidate_contract_sha256(candidate)}
        result = cf.verify_task_candidate_digest(parameters, candidate)
        self.assertEqual(result["kind"], cf.CandidateDigestKind.CONVERGED)
        self.assertEqual(result["candidate_contract_sha256"],
                         cf.candidate_contract_sha256(candidate))

    def test_hk_rejects_an_altered_candidate(self):
        parameters = {"candidate_contract_sha256":
                      cf.candidate_contract_sha256(converged())}
        with self.assertRaises(cf.CandidateFactError) as caught:
            cf.verify_task_candidate_digest(
                parameters, converged(source_commit="b" * 39 + "a"))
        self.assertEqual(str(caught.exception), "candidate_digest_mismatch")

    def test_hk_rejects_an_absent_or_malformed_digest(self):
        for parameters in ({}, {"candidate_contract_sha256": None},
                           {"candidate_contract_sha256": "not-a-digest"},
                           {"candidate_contract_sha256": "A" * 64}):
            with self.assertRaises(cf.CandidateFactError) as caught:
                cf.verify_task_candidate_digest(parameters, converged())
            self.assertEqual(str(caught.exception), "candidate_digest_absent")

    def test_a_legacy_digest_cannot_masquerade_as_a_converged_one(self):
        """The whole point of tagging the kind."""
        legacy = legacy_v3()
        legacy_digest = cf.legacy_document_digest(legacy)["legacy_document_sha256"]
        with self.assertRaises(cf.CandidateFactError) as caught:
            cf.verify_task_candidate_digest(
                {"candidate_contract_sha256": legacy_digest}, legacy)
        self.assertTrue(str(caught.exception)
                        .startswith("candidate_digest_legacy_not_converged:"))

    def test_a_legacy_digest_is_always_tagged_with_its_kind(self):
        for document in (legacy_v1(), legacy_v2(), legacy_v3()):
            tagged = cf.legacy_document_digest(document)
            self.assertIn(tagged["kind"], cf.CandidateDigestKind.LEGACY)
            self.assertEqual(len(tagged["legacy_document_sha256"]), 64)

    def test_the_legacy_digest_helper_refuses_a_converged_document(self):
        with self.assertRaises(cf.CandidateFactError):
            cf.legacy_document_digest(converged())

    def test_a_converged_document_is_never_read_as_legacy(self):
        with self.assertRaises(lg.LegacyContractError):
            lg.read_legacy(converged())


# --------------------------------------------------------------------------- #
# the admission produces the digest
# --------------------------------------------------------------------------- #
class AdmissionDigestTests(unittest.TestCase):
    def _admit(self, block):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "candidate.json"
            path.write_text(json.dumps({"release_candidate_v1": block}), encoding="utf-8")
            return A.admit(CONTRACT, path, None, None, None)

    def test_a_candidate_that_admits_carries_the_converged_digest(self):
        result = self._admit(converged())
        admitted = result["verdict"]["admission"] == "ACCEPT"
        self.assertEqual(result["candidate_contract_sha256"] is not None, admitted)
        if admitted:
            self.assertEqual(result["candidate_contract_sha256"], FIXED_VECTOR_DIGEST)

    def test_a_candidate_declaring_the_prohibited_condition_carries_no_digest(self):
        result = self._admit(converged(migration_required=True))
        self.assertEqual(result["verdict"]["admission"], "REJECT")
        self.assertIn(cf.E_DATABASE_MIGRATION_REQUIRED, result["verdict"]["rejected"])
        self.assertIsNone(result["candidate_contract_sha256"])

    def test_a_candidate_without_a_graph_carries_no_digest(self):
        """The other side of the pair: no usable head is a graph refusal, not a third code."""
        result = self._admit(converged(migration_head=None))
        self.assertEqual(result["verdict"]["admission"], "REJECT")
        self.assertIn(cf.E_DATABASE_MIGRATION_GRAPH_MISMATCH, result["verdict"]["rejected"])
        self.assertIsNone(result["candidate_contract_sha256"])

    def test_the_legacy_migration_tokens_are_aliases_and_are_not_emitted(self):
        """Read old, write new, at this layer too."""
        self.assertEqual(cf.LEGACY_MIGRATION_REASON_ALIAS,
                         {"candidate_migration_required": cf.E_DATABASE_MIGRATION_REQUIRED,
                          "candidate_migration_head": cf.E_DATABASE_MIGRATION_GRAPH_MISMATCH})
        self.assertEqual(cf.public_migration_reason("candidate_migration_required"),
                         cf.E_DATABASE_MIGRATION_REQUIRED)
        self.assertEqual(cf.public_migration_reason("something_else"), "something_else")

    def test_the_two_layers_declare_the_same_two_codes(self):
        """Cross-layer agreement without a cross-layer import.

        The admission component and the plan derivation must refuse migration in the
        same two words. They deliberately do not import each other -- a component
        reaching into another component's source would be a new coupling -- so the
        agreement is pinned here by reading both sources, the way the request
        visibility component pins the Bridge's refusal vocabulary.
        """
        plan = (ROOT.parents[0] / "boss-deploy-request-v1" / "plan_derivation.py")
        self.assertTrue(plan.is_file(), plan)
        source = plan.read_text(encoding="utf-8")
        for name in ("E_DATABASE_MIGRATION_REQUIRED",
                     "E_DATABASE_MIGRATION_GRAPH_MISMATCH"):
            self.assertIn("%s = '" % name, source, name)
        self.assertEqual(
            cf.E_DATABASE_MIGRATION_REQUIRED,
            cf.public_migration_reason("candidate_migration_required"))
        self.assertEqual(
            cf.E_DATABASE_MIGRATION_GRAPH_MISMATCH,
            cf.public_migration_reason("candidate_migration_head"))
        # The plan derivation's own pre-convergence token maps into the same pair.
        self.assertIn(
            "'migration_required_not_supported': E_DATABASE_MIGRATION_REQUIRED", source)

    def test_a_refused_candidate_carries_no_digest(self):
        result = self._admit(converged(source_commit="main"))
        self.assertEqual(result["verdict"]["admission"], "REJECT")
        self.assertIsNone(result["candidate_contract_sha256"])


if __name__ == "__main__":
    unittest.main()
