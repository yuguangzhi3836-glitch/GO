"""Read an independent C13 AI opinion before admitting a C14 retest.

The trusted recorder supplies actual review provenance and original artifacts.
AI opinions need no signature or reviewer key. Machine bus signing is separate.
"""
from __future__ import annotations

import hashlib
import json
import io
import zipfile
from xml.etree import ElementTree

from evidence_time import utc_epoch
from acceptance_gate import Refusal


CANDIDATE = "d4376d6ae9a58eca3c7c32968ec96dffc5574122"
TREE = "bee89f356a43bf3445d2da3f60f64f7db02a28cd"
SCOPE = "e13e181efccfc394171cb46e8c057e2f3c88c6f29893302c922da8061510a118"
ARTIFACT_SHA256 = "44b1dca3444296ff4f9ad52c323c3bb325ca3d143efb022b6785ac07047ad777"
RUN_ID = 35993187797
ARTIFACT_ID = 10805227694
FIELDS = {"contract", "candidate_sha", "application_tree", "test_scope_sha256",
          "artifact_sha256", "run_id", "artifact_id", "junit_tests", "junit_failures",
          "pg_cases", "pg_failures", "reviewer_id", "reviewer_independent",
          "verdict", "issued_at", "review_execution_id", "review_reference", "opinion"}


def canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def inspect_artifact(artifact_zip: bytes) -> dict:
    if type(artifact_zip) is not bytes or hashlib.sha256(artifact_zip).hexdigest() != ARTIFACT_SHA256:
        raise Refusal("c13_artifact_integrity")
    try:
        with zipfile.ZipFile(io.BytesIO(artifact_zip)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if (len(entries) != 72 or len(set(names)) != len(names) or
                    any(entry.is_dir() or entry.file_size > 2_000_000 or
                        entry.filename.startswith("/") or ".." in entry.filename.split("/")
                        for entry in entries) or sum(entry.file_size for entry in entries) > 8_000_000):
                raise Refusal("c13_artifact_structure")
            binding = json.loads(archive.read("C13_SOURCE_BINDING.json"))
            if (binding.get("candidate_sha"), binding.get("application_tree"),
                    binding.get("test_scope_sha256")) != (CANDIDATE, TREE, SCOPE):
                raise Refusal("c13_artifact_binding")
            file_hashes = binding.get("files")
            if (type(file_hashes) is not dict or set(file_hashes) != set(names) - {"C13_SOURCE_BINDING.json"} or
                    any(hashlib.sha256(archive.read(name)).hexdigest() != file_hashes[name]
                        for name in file_hashes)):
                raise Refusal("c13_artifact_manifest")
            junit = ElementTree.fromstring(archive.read("JUNIT.xml"))
            suite = junit if junit.tag == "testsuite" else junit.find("testsuite")
            pg_junit = ElementTree.fromstring(archive.read("junit.xml"))
            execution = json.loads(archive.read("execution.json"))
            results = json.loads(archive.read("results.json"))
            if (suite is None or int(suite.get("tests", -1)) != 61 or
                    any(int(suite.get(k, -1)) != 0 for k in ("failures", "errors")) or
                    len(suite.findall("testcase")) != 61 or
                    pg_junit.tag != "testsuite" or int(pg_junit.get("tests", -1)) != 10 or
                    int(pg_junit.get("failures", -1)) != 0 or
                    len(pg_junit.findall("testcase")) != 10 or
                    type(results) is not list or len(results) != 10 or
                    any(row.get("status") != "PASS" for row in results) or
                    execution.get("source_commit") != CANDIDATE or
                    execution.get("status") != "EVIDENCE_READY" or
                    execution.get("hard_death_auto_recovery") != "PASS" or
                    not str(execution.get("postgres_server_version", "")).startswith("18.4")):
                raise Refusal("c13_artifact_results")
    except (zipfile.BadZipFile, KeyError, ValueError, TypeError, ElementTree.ParseError, RuntimeError) as exc:
        if isinstance(exc, Refusal):
            raise
        raise Refusal("c13_artifact_parse") from exc
    return {"junit_tests": 61, "pg_cases": 10, "artifact_sha256": ARTIFACT_SHA256}


def verify(raw: bytes, artifact_zip: bytes, reviewer_id: str,
           review_execution_id: str) -> dict:
    """Return facts accepted by ``acceptance_gate.c14_admission`` or fail closed.

    The host supplies the independent AI group/execution from actual review
    records, not a caller's self-declaration, and the exact original artifact.
    This is a source/evidence/opinion check, not a digital signature check.
    """
    if type(raw) is not bytes or len(raw) > 16384 or not raw.endswith(b"\n"):
        raise Refusal("c13_record_bytes")
    try:
        record = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise Refusal("c13_record_json") from exc
    if type(record) is not dict or set(record) != FIELDS or raw != canonical(record) + b"\n":
        raise Refusal("c13_record_schema")
    expected = {"contract": "GO_C13_INDEPENDENT_OPINION_V2",
                "candidate_sha": CANDIDATE, "application_tree": TREE,
                "test_scope_sha256": SCOPE, "artifact_sha256": ARTIFACT_SHA256,
                "run_id": RUN_ID, "artifact_id": ARTIFACT_ID,
                "junit_tests": 61, "junit_failures": 0,
                "pg_cases": 10, "pg_failures": 0,
                "verdict": "PASS_SCOPED", "reviewer_independent": True}
    if any(type(record.get(k)) is not type(v) or record.get(k) != v for k, v in expected.items()):
        raise Refusal("c13_fixed_binding")
    if (type(reviewer_id) is not str or not reviewer_id or record["reviewer_id"] != reviewer_id or
            type(review_execution_id) is not str or not review_execution_id or
            record["review_execution_id"] != review_execution_id):
        raise Refusal("c13_reviewer")
    for key in ("opinion", "review_reference"):
        if type(record[key]) is not str or not record[key].strip():
            raise Refusal("c13_review_opinion")
    utc_epoch(record["issued_at"], "c13_time")
    inspect_artifact(artifact_zip)
    return {"candidate_sha": CANDIDATE, "application_tree": TREE,
            "test_scope_sha256": SCOPE, "verdict": "PASS_SCOPED",
            "actor_id": reviewer_id, "verified": True,
            "evidence_sha256": hashlib.sha256(raw).hexdigest()}
