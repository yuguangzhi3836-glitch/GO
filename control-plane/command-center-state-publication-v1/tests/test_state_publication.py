#!/usr/bin/env python3
"""Isolated tests for the CC V1-04 derived-state publication target.

No network, no subprocess, no key, no live system.  They load the publisher by
path (it ships without a `.py` suffix, like the other Command Center binaries)
and assert the four properties Issue #99 fixes:

  * deterministic rebuild => same projection for the same inputs/time contract
  * the publication artifact is traceable to its source refs and heads
  * a stale or failed publication has an explicit status
  * a reader has a stable, read-only path to a bounded status contract

and the four things that are forbidden:

  * the derived state is not execution authority
  * a status file cannot trigger the executor
  * a hand-edited snapshot cannot pass as a projection result
  * no Production access is implied anywhere
"""
import datetime as dt
import importlib.machinery
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
PUBLISHER_PATH = ROOT / "command-center" / "go-state-publication"
CONTRACT_PATH = ROOT / "contracts" / "state_publication_v1.schema.json"
STATE_LAYER = ROOT.parent / "command-center-state-v1"
REAL_PROJECTION = STATE_LAYER / "evidence" / "PROJECTION_20260914"


def load_publisher():
    loader = importlib.machinery.SourceFileLoader("go_state_publication", str(PUBLISHER_PATH))
    spec = importlib.util.spec_from_loader("go_state_publication", loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules["go_state_publication"] = module
    spec.loader.exec_module(module)
    return module


P = load_publisher()

GENERATED_AT = "2026-09-14T12:00:00Z"
PUBLISHED_AT = "2026-09-14T13:00:00Z"
AT = P.parse_time("2026-09-14T14:00:00Z", "at")
PROJECTOR = "c" * 40
SOURCE = {"tasks": {"ref": "main", "head": "a" * 40},
          "evidence": {"ref": "permission-test", "head": "b" * 40},
          "go": {"ref": "main", "head": None}}


def documents(seed="base"):
    return {
        "CURRENT_CONTROL_STATE.json": {"generated_at": GENERATED_AT, "counts": {"tasks": 1}, "seed": seed},
        "CONTROL_STATUS_V1.json": {"generated_at": GENERATED_AT, "answers": {}},
        "TASK_INDEX.json": {"tasks": []},
        "LATEST_EVIDENCE.json": {"by_action": {}},
    }


def manifest_for(docs, published_at=PUBLISHED_AT):
    return P.build_manifest(docs, SOURCE, PROJECTOR, published_at)


def write_projection(directory, docs):
    directory = pathlib.Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, payload in docs.items():
        (directory / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return directory


class TestProjectionIntake(unittest.TestCase):
    def test_a_complete_projection_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = write_projection(pathlib.Path(tmp) / "proj", documents())
            read = P.read_projection(source)
            self.assertEqual(sorted(read), sorted(P.PROJECTION_DOCS))

    def test_a_missing_document_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = documents()
            del docs["TASK_INDEX.json"]
            with self.assertRaises(P.Reject):
                P.read_projection(write_projection(pathlib.Path(tmp) / "proj", docs))

    def test_a_malformed_document_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = write_projection(pathlib.Path(tmp) / "proj", documents())
            (source / "CONTROL_STATUS_V1.json").write_text("{not json", encoding="utf-8")
            with self.assertRaises(P.Reject):
                P.read_projection(source)

    def test_a_document_without_generated_at_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = documents()
            docs["CURRENT_CONTROL_STATE.json"] = {"counts": {}}
            with self.assertRaises(P.Reject):
                P.read_projection(write_projection(pathlib.Path(tmp) / "proj", docs))

    def test_a_machine_specific_path_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = documents()
            docs["LATEST_EVIDENCE.json"] = {"by_action": {}, "out": "D:/Code/Workbuddy/GO"}
            with self.assertRaises(P.Reject):
                P.read_projection(write_projection(pathlib.Path(tmp) / "proj", docs))


class TestDeterminism(unittest.TestCase):
    def test_identical_inputs_produce_an_identical_manifest(self):
        docs = documents()
        self.assertEqual(manifest_for(docs), manifest_for(docs))

    def test_identical_inputs_produce_an_identical_run_id(self):
        docs = documents()
        self.assertEqual(P.run_id_for(GENERATED_AT, docs), P.run_id_for(GENERATED_AT, docs))

    def test_different_content_produces_a_different_run_id(self):
        self.assertNotEqual(P.run_id_for(GENERATED_AT, documents("one")),
                            P.run_id_for(GENERATED_AT, documents("two")))

    def test_the_run_id_matches_its_grammar(self):
        self.assertRegex(P.run_id_for(GENERATED_AT, documents()), P.RUN_ID_RE)

    def test_the_manifest_covers_every_projection_document(self):
        manifest = manifest_for(documents())
        self.assertEqual(sorted(entry["name"] for entry in manifest["documents"]),
                         sorted(P.PROJECTION_DOCS))
        for entry in manifest["documents"]:
            self.assertRegex(entry["sha256"], P.SHA256_RE)


class TestProvenance(unittest.TestCase):
    def test_the_manifest_records_every_source_head(self):
        manifest = manifest_for(documents())
        self.assertEqual(manifest["source"], SOURCE)

    def test_the_manifest_records_the_projector_revision(self):
        self.assertEqual(manifest_for(documents())["projector_revision"], PROJECTOR)

    def test_an_unpinned_publication_is_refused(self):
        class Args:
            tasks_ref, evidence_ref, go_ref = "main", "permission-test", "main"
            tasks_head = evidence_head = go_head = None
            projector_revision = PROJECTOR
        with self.assertRaises(P.Reject):
            P.normalise_source(Args())

    def test_a_head_that_is_not_a_sha_is_refused(self):
        class Args:
            tasks_ref, evidence_ref, go_ref = "main", "permission-test", "main"
            tasks_head, evidence_head, go_head = "main", None, None
            projector_revision = PROJECTOR
        with self.assertRaises(P.Reject):
            P.normalise_source(Args())

    def test_a_missing_projector_revision_is_refused(self):
        class Args:
            tasks_ref, evidence_ref, go_ref = "main", "permission-test", "main"
            tasks_head, evidence_head, go_head = "a" * 40, None, None
            projector_revision = ""
        with self.assertRaises(P.Reject):
            P.normalise_source(Args())


class TestPublicationPhases(unittest.TestCase):
    def test_publishing_the_same_content_twice_does_not_rewrite_the_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = P.Target(tmp)
            docs = documents()
            manifest = manifest_for(docs)
            run_id = P.run_id_for(GENERATED_AT, docs)
            _, first = target.write_snapshot(run_id, docs, manifest)
            _, second = target.write_snapshot(run_id, docs, manifest)
            self.assertTrue(first)
            self.assertFalse(second)
            self.assertEqual(len(list(target.runs.iterdir())), 1)

    def test_the_same_run_id_with_different_content_is_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = P.Target(tmp)
            run_id = P.run_id_for(GENERATED_AT, documents())
            target.write_snapshot(run_id, documents(), manifest_for(documents()))
            other = documents("other")
            with self.assertRaises(P.Reject):
                target.write_snapshot(run_id, other, manifest_for(other))

    def test_a_failed_attempt_leaves_the_pointer_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = P.Target(tmp)
            docs = documents()
            manifest = manifest_for(docs)
            run_id = P.run_id_for(GENERATED_AT, docs)
            target.write_snapshot(run_id, docs, manifest)
            target.advance_pointer(run_id, manifest)
            before = target.read_pointer()
            other = documents("other")
            with self.assertRaises(P.Reject):
                target.write_snapshot(run_id, other, manifest_for(other))
            self.assertEqual(before, target.read_pointer())

    def test_a_failure_is_recorded_and_says_the_pointer_was_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = P.Target(tmp)
            record = target.record_failure("snapshot_digest_mismatch", PUBLISHED_AT, "run", SOURCE)
            self.assertEqual(record["status"], P.POINTER_STATUS_FAILED)
            self.assertIs(record["current_pointer_untouched"], True)
            self.assertIs(record["execution_authority"], False)

    def test_a_successful_publication_clears_the_previous_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = P.Target(tmp)
            target.record_failure("earlier", PUBLISHED_AT, "run", SOURCE)
            self.assertIsNotNone(target.read_failure())
            target.clear_failure()
            self.assertIsNone(target.read_failure())

    def test_the_index_is_append_only_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = P.Target(tmp)
            docs = documents()
            manifest = manifest_for(docs)
            run_id = P.run_id_for(GENERATED_AT, docs)
            target.write_snapshot(run_id, docs, manifest)
            target.advance_pointer(run_id, manifest)
            target.append_index(run_id, manifest)
            target.append_index(run_id, manifest)
            index = json.loads(target.index.read_text(encoding="utf-8"))
            self.assertEqual(len(index["publications"]), 1)


class TestSnapshotIntegrity(unittest.TestCase):
    def test_a_tampered_snapshot_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = P.Target(tmp)
            docs = documents()
            manifest = manifest_for(docs)
            run_id = P.run_id_for(GENERATED_AT, docs)
            target.write_snapshot(run_id, docs, manifest)
            directory = target.run_dir(run_id)
            (directory / "TASK_INDEX.json").write_text(
                json.dumps({"tasks": [{"hand_edited": True}]}), encoding="utf-8")
            with self.assertRaises(P.Reject):
                P.verify_snapshot(directory, P.read_manifest(directory))

    def test_a_removed_document_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = P.Target(tmp)
            docs = documents()
            manifest = manifest_for(docs)
            run_id = P.run_id_for(GENERATED_AT, docs)
            target.write_snapshot(run_id, docs, manifest)
            directory = target.run_dir(run_id)
            (directory / "LATEST_EVIDENCE.json").unlink()
            with self.assertRaises(P.Reject):
                P.verify_snapshot(directory, P.read_manifest(directory))

    def test_an_untampered_snapshot_verifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = P.Target(tmp)
            docs = documents()
            manifest = manifest_for(docs)
            run_id = P.run_id_for(GENERATED_AT, docs)
            target.write_snapshot(run_id, docs, manifest)
            P.verify_snapshot(target.run_dir(run_id), P.read_manifest(target.run_dir(run_id)))


class TestPublicationStatus(unittest.TestCase):
    def test_no_publication_at_all_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(P.publication_status(P.Target(tmp), AT, 3600)["status"],
                             P.POINTER_STATUS_UNKNOWN)

    def test_a_fresh_publication_is_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = P.Target(tmp)
            docs = documents()
            manifest = manifest_for(docs)
            run_id = P.run_id_for(GENERATED_AT, docs)
            target.write_snapshot(run_id, docs, manifest)
            target.advance_pointer(run_id, manifest)
            self.assertEqual(P.publication_status(target, AT, 7200)["status"],
                             P.POINTER_STATUS_CURRENT)

    def test_an_old_publication_is_stale_not_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = P.Target(tmp)
            docs = documents()
            manifest = manifest_for(docs)
            run_id = P.run_id_for(GENERATED_AT, docs)
            target.write_snapshot(run_id, docs, manifest)
            target.advance_pointer(run_id, manifest)
            result = P.publication_status(target, AT, 60)
            self.assertEqual(result["status"], P.POINTER_STATUS_STALE)
            self.assertEqual(result["last_success"], PUBLISHED_AT)

    def test_a_failure_after_the_last_success_reads_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = P.Target(tmp)
            docs = documents()
            manifest = manifest_for(docs)
            run_id = P.run_id_for(GENERATED_AT, docs)
            target.write_snapshot(run_id, docs, manifest)
            target.advance_pointer(run_id, manifest)
            target.record_failure("snapshot_digest_mismatch", "2026-09-14T13:30:00Z", run_id, SOURCE)
            self.assertEqual(P.publication_status(target, AT, 7200)["status"],
                             P.POINTER_STATUS_FAILED)

    def test_stale_is_reported_before_failed_when_the_failure_is_older(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = P.Target(tmp)
            docs = documents()
            manifest = manifest_for(docs)
            run_id = P.run_id_for(GENERATED_AT, docs)
            target.write_snapshot(run_id, docs, manifest)
            target.advance_pointer(run_id, manifest)
            target.record_failure("older", "2026-09-14T12:30:00Z", run_id, SOURCE)
            result = P.publication_status(target, AT, 60)
            self.assertEqual(result["status"], P.POINTER_STATUS_STALE)

    def test_status_never_re_derives_control_state(self):
        """The publication status is about the publication, not about the agent."""
        with tempfile.TemporaryDirectory() as tmp:
            result = P.publication_status(P.Target(tmp), AT, 3600)
            self.assertEqual(set(result), {"status", "detail", "last_success", "age_seconds"})


class TestConsumerContract(unittest.TestCase):
    """A reader gets a stable path and nothing executable."""

    def test_the_pointer_declares_it_is_not_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = P.Target(tmp)
            docs = documents()
            manifest = manifest_for(docs)
            run_id = P.run_id_for(GENERATED_AT, docs)
            target.write_snapshot(run_id, docs, manifest)
            pointer = target.advance_pointer(run_id, manifest)
            self.assertIs(pointer["execution_authority"], False)
            self.assertIs(pointer["read_only_for_consumers"], True)

    def test_no_publication_file_carries_an_authority_shaped_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = P.Target(tmp)
            docs = documents()
            manifest = manifest_for(docs)
            run_id = P.run_id_for(GENERATED_AT, docs)
            target.write_snapshot(run_id, docs, manifest)
            target.advance_pointer(run_id, manifest)
            target.append_index(run_id, manifest)
            target.record_failure("x", PUBLISHED_AT, run_id, SOURCE)
            for path in (target.pointer, target.index, target.failure,
                         target.run_dir(run_id) / P.MANIFEST_NAME):
                payload = json.loads(path.read_text(encoding="utf-8"))
                P.assert_no_authority(payload, path.name)

    def test_authority_shaped_keys_are_refused_wherever_they_hide(self):
        for payload in ({"signature": "x"}, {"nested": {"nonce": "y"}}, {"action_id": "z"},
                        {"parameters": {}}, {"grants_execution": True}):
            with self.assertRaises(P.Reject):
                P.assert_no_authority(payload, "test")

    def test_the_read_path_is_stable_and_named(self):
        self.assertEqual(P.POINTER_NAME, "CURRENT.json")
        self.assertEqual(P.RUN_DIR_NAME, "runs")


class TestAuthorityBoundary(unittest.TestCase):
    def test_the_publisher_never_signs_or_invokes_anything(self):
        """No signing capability and no way to reach another process.

        The checks are for real capability tokens, not loose substrings: the
        forbidden-key list legitimately contains names such as
        `executor_command`, which is a key it *refuses*, not one it uses.
        """
        source = PUBLISHER_PATH.read_text(encoding="utf-8")
        for forbidden in ("load_pem_private_key", "import cryptography", "from cryptography",
                          "import subprocess", "from subprocess", "subprocess.",
                          "os.system", "os.exec", "popen", "request_channel",
                          ".sign(", "Ed25519"):
            self.assertNotIn(forbidden, source)

    def test_the_publisher_never_reaches_production(self):
        source = PUBLISHER_PATH.read_text(encoding="utf-8")
        self.assertNotIn("PRODU" + "CTION", source)
        self.assertNotIn("HK_" + "STAGING_", source)

    def test_the_contract_declares_the_boundary(self):
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        boundary = contract["properties"]["authority_boundary"]["properties"]
        for key in ("is_execution_authority", "can_trigger_executor", "holds_private_key",
                    "accepts_hand_edited_state", "touches_production",
                    "may_edit_a_projection_document"):
            self.assertIs(boundary[key]["const"], False)

    def test_the_contract_declares_all_four_pointer_states(self):
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        states = contract["properties"]["pointer"]["properties"]["status_reported_by_reader"]
        self.assertEqual(sorted(states["enum"]),
                         sorted([P.POINTER_STATUS_CURRENT, P.POINTER_STATUS_STALE,
                                 P.POINTER_STATUS_FAILED, P.POINTER_STATUS_UNKNOWN]))


class TestAgainstTheRealProjection(unittest.TestCase):
    """The publisher must work on the projection this repository actually holds."""

    def setUp(self):
        if not REAL_PROJECTION.is_dir():
            self.skipTest("no committed projection available")

    def test_the_committed_projection_is_accepted_and_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = P.read_projection(REAL_PROJECTION)
            target = P.Target(tmp)
            manifest = manifest_for(docs)
            run_id = P.run_id_for(docs["CURRENT_CONTROL_STATE.json"]["generated_at"], docs)
            target.write_snapshot(run_id, docs, manifest)
            target.advance_pointer(run_id, manifest)
            verified = P.verify_snapshot(target.run_dir(run_id), P.read_manifest(target.run_dir(run_id)))
            self.assertEqual(sorted(verified), sorted(P.PROJECTION_DOCS))
            # published_at is PUBLISHED_AT and AT is one hour later
            self.assertEqual(P.publication_status(target, AT, 604800)["status"],
                             P.POINTER_STATUS_CURRENT)
            self.assertEqual(P.publication_status(target, AT, 60)["status"],
                             P.POINTER_STATUS_STALE)

    def test_the_committed_projection_digest_is_stable_across_reads(self):
        first = P.content_digest(P.read_projection(REAL_PROJECTION))
        second = P.content_digest(P.read_projection(REAL_PROJECTION))
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
