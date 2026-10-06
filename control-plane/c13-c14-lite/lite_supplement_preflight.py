"""Read-only prerequisite for reusing C13 evidence in a PostgreSQL supplement.

No admission, network, queue, retry or verdict mutation. `expected` must come
from a separately verified transport record, not from the supplied bundle.
Passing this check grants no execution authority. The caller still has to verify
artifact origin, admission, the new machine part, and the independent reseal.
"""
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET

import lite_bundle
from lite_errors import Block, Reject


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(raw, name):
    try:
        doc = json.loads(raw)
    except (ValueError, TypeError, UnicodeError):
        raise Reject("supplement_invalid_json", name) from None
    if type(doc) is not dict:
        raise Reject("supplement_not_object", name)
    return doc


def check_prior(bundle_raw, members, *, expected):
    """Validate prior raw bytes; service-image metadata is never database proof.

    A future producing backend must bind its database observation in the sealed
    manifest as database_sha256. An unbound sidecar cannot upgrade old evidence.
    In particular #533's legacy manifest cannot pass by adding database.json later.
    """
    bundle = _json(bundle_raw, "c13_bundle.json")
    lite_bundle.validate(bundle)
    lite_bundle.verify_root(bundle)
    if bundle["cell_id"] != "C13":
        raise Reject("supplement_prior_not_c13")
    for name in ("C13_ROOT", "candidate_sha", "application_tree", "issue_number",
                 "github_run_id", "github_run_attempt", "task_id", "ledger_reference"):
        if name not in expected or bundle[name] != expected[name]:
            raise Reject("supplement_prior_binding_mismatch", name)
    if bundle["c14_prerequisite"]["c14_root"] != expected.get("c14_root"):
        raise Reject("supplement_c14_root_mismatch")
    if (bundle["c14_prerequisite"]["c14_candidate_sha"] != bundle["candidate_sha"]
            or bundle["c14_prerequisite"]["c14_verdict"] != "PASS_SCOPED"):
        raise Reject("supplement_c14_not_same_candidate_pass")
    if (bundle["verdict"] != "BLOCKED" or bundle["failure_class"] is not None
            or {f.get("id") for f in bundle["quality_findings"]} != {"C13-EVIDENCE-001"}):
        raise Block("supplement_not_inventory_only_block")

    for filename, field in (("manifest.json", "manifest_sha256"),
                            ("junit.xml", "junit_sha256"),
                            ("stdout.txt", "stdout_sha256"),
                            ("test_inventory.txt", "test_inventory_sha256")):
        if filename not in members:
            raise Reject("supplement_missing_machine_member", filename)
        if digest(members[filename]) != bundle["machine_job"][field]:
            raise Reject("supplement_machine_digest_mismatch", filename)
    manifest = _json(members["manifest.json"], "manifest.json")
    for name in ("candidate_sha", "application_tree"):
        if manifest.get(name) != bundle[name]:
            raise Reject("supplement_manifest_binding_mismatch", name)
    for name, filename in (("junit_sha256", "junit.xml"), ("stdout_sha256", "stdout.txt")):
        if manifest.get(name) != digest(members[filename]):
            raise Reject("supplement_manifest_digest_mismatch", name)
    if (type(manifest.get("exit_code")) is not int or manifest["exit_code"] != 0
            or manifest.get("step_outcome") != "success"
            or manifest.get("docker_used") is not True):
        raise Block("supplement_prior_machine_not_success")
    try:
        inventory = members["test_inventory.txt"].decode("utf-8").strip()
    except UnicodeError:
        raise Reject("supplement_inventory_not_utf8") from None
    if not inventory or inventory != manifest.get("inventory"):
        raise Reject("supplement_inventory_mismatch")

    # A postgres service running beside pytest does not tell us the engine pytest
    # selected. Do not infer this from DATABASE_URL or the manifest's old literal.
    if not manifest.get("database_sha256") or "database.json" not in members:
        raise Block("supplement_prior_database_unproven")
    if digest(members["database.json"]) != manifest["database_sha256"]:
        raise Reject("supplement_database_digest_mismatch")
    database = _json(members["database.json"], "database.json")
    if database.get("candidate_sha") != bundle["candidate_sha"]:
        raise Reject("supplement_database_candidate_mismatch")
    if (database.get("dialect") != "postgresql"
            or type(database.get("server_version_num")) is not int
            or database["server_version_num"] != 180004):
        raise Block("supplement_prior_not_postgresql_18_4")

    try:
        raw = members["junit.xml"]
        if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
            raise ValueError("external entities forbidden")
        root = ET.fromstring(raw)
        cases = list(root.iter("testcase"))
        identities = [(case.get("classname"), case.get("name")) for case in cases]
        if (not cases or len(identities) != len(set(identities))
                or any(not all(identity) for identity in identities)
                or any(list(case.iter(tag)) for case in cases
                       for tag in ("failure", "error", "skipped"))):
            raise ValueError("incomplete testcases")
        # Count actual cases, never trust a green-looking suite summary alone.
        if root.tag not in ("testsuites", "testsuite"):
            raise ValueError("unexpected root")
        suites = list(root.iter("testsuite"))
        if not suites or any(list(root.iter(tag)) for tag in ("failure", "error", "skipped")):
            raise ValueError("failed or missing suites")
        for suite in suites:
            if int(suite.get("tests", "-1")) != len(list(suite.iter("testcase"))):
                raise ValueError("inconsistent suite counts")
            if any(int(suite.get(name, "-1")) != 0 for name in ("failures", "errors", "skipped")):
                raise ValueError("nonpassing suite counts")
    except (ET.ParseError, ValueError):
        raise Block("supplement_prior_junit_not_all_pass") from None
    return {"status": "PRIOR_BYTES_VALIDATED", "authorizes_any_action": False,
            "candidate_sha": bundle["candidate_sha"], "prior_c13_root": bundle["C13_ROOT"],
            "prior_run_id": bundle["github_run_id"],
            "prior_run_attempt": bundle["github_run_attempt"],
            "prior_inventory": inventory, "prior_passed_cases": len(cases)}
