"""PG533 backend boundary and mixed-database evidence assembly. No paid execution."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime-host-channel-v1"))
import c1_c13_supplement_contract as fixed
import lite_bundle


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def write_aggregate(path, data):
    """Publish runner-owned derived bytes without opening Docker's output for write.

    The machine directory is runner-owned; a container-created JUnit can be
    readable but not writable by that runner. Source bytes are already retained
    in parts/. Replace the directory entry, never chmod/chown the source inode.
    A failed write/replace leaves the old file intact and still fails the step.
    """
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".pg533-", delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def expected_selection(nodeids):
    require(len(nodeids) == 15 and len(set(nodeids)) == 15, "PG533_EXPECTED_EXACTLY_15_CASES")
    counts = {path: 0 for path in fixed.CASE_COUNTS}
    for node in nodeids:
        matching = [p for p in counts if node == p or node.startswith(p + "::")]
        require(len(matching) == 1, "PG533_UNAUTHORIZED_TEST_NODE")
        counts[matching[0]] += 1
    require(counts == fixed.CASE_COUNTS, "PG533_FILE_CASE_COUNTS_MISMATCH")


def prepare(env):
    transport = json.loads(env["RUNTIME_TRANSPORT"])
    if "supplement" not in transport:
        return False
    require(json.dumps(transport["supplement"], sort_keys=True) == json.dumps(fixed.ENVELOPE, sort_keys=True),
            "PG533_UNKNOWN_SUPPLEMENT")
    require(env.get("GITHUB_RUN_ATTEMPT") == "1", "PG533_RERUN_NOT_AUTHORIZED")
    require(transport["owner_c"] == "C13" and type(transport["attempt"]) is int and transport["attempt"] == 1
            and transport["runtime_task_id"] != fixed.C13_RUNTIME
            and transport["c14_run_id"] == fixed.C14_RUN, "PG533_TRANSPORT_MISMATCH")
    for key, value in {"CANDIDATE_SHA": fixed.CANDIDATE, "APPLICATION_TREE": fixed.APPLICATION_TREE,
                       "ISSUE_NUMBER": str(fixed.ISSUE), "ROUND_ID": fixed.ROUND,
                       "C13_TASK_ID": fixed.C13_TASK, "C14_TASK_ID": fixed.C14_TASK,
                       "MACHINE_INVENTORY": fixed.INVENTORY}.items():
        require(env.get(key) == value, "PG533_INPUT_MISMATCH:" + key)
    return True


def cases(raw):
    require(b"<!DOCTYPE" not in raw and b"<!ENTITY" not in raw, "PG533_UNSAFE_XML")
    root = ET.fromstring(raw)
    result = list(root.iter("testcase"))
    require(result and root.tag in ("testsuites", "testsuite"), "PG533_EMPTY_JUNIT")
    require(not any(list(root.iter(tag)) for tag in ("failure", "error", "skipped")), "PG533_NONPASS_JUNIT")
    suites = list(root.iter("testsuite"))
    require(bool(suites), "PG533_NO_TEST_SUITE")
    for suite in suites:
        require(int(suite.get("tests", -1)) == len(list(suite.iter("testcase")))
                and all(int(suite.get(k, -1)) == 0 for k in ("failures", "errors", "skipped")),
                "PG533_JUNIT_COUNTS_MISMATCH")
    ids = [(c.get("classname"), c.get("name")) for c in result]
    require(all(all(pair) for pair in ids) and len(set(ids)) == len(ids), "PG533_DUPLICATE_CASE")
    return result


def assemble(prior, prior_review, c14_dir, fresh, *, run_id, run_attempt):
    require(type(run_id) is int and run_id > 0 and run_id not in (fixed.C13_RUN, fixed.C14_RUN)
            and type(run_attempt) is int and run_attempt == 1, "PG533_NEW_RUN_BINDING_REQUIRED")
    bundle = json.loads((prior_review / "c13_bundle.json").read_bytes())
    c14 = json.loads((c14_dir / "c14_bundle.json").read_bytes())
    for document in (bundle, c14):
        lite_bundle.validate(document)
        lite_bundle.verify_root(document)
    require(bundle["C13_ROOT"] == fixed.C13_ROOT and c14["C14_ROOT"] == fixed.C14_ROOT,
            "PG533_ORIGINAL_ROOT_MISMATCH")
    require(bundle["github_run_id"] == fixed.C13_RUN and bundle["github_run_attempt"] == 1
            and c14["github_run_id"] == fixed.C14_RUN and c14["github_run_attempt"] == 1
            and c14["verdict"] == "PASS_SCOPED" and bundle["verdict"] == "BLOCKED",
            "PG533_ORIGINAL_RUN_OR_VERDICT_MISMATCH")
    for document in (bundle, c14):
        require(document["candidate_sha"] == fixed.CANDIDATE
                and document["application_tree"] == fixed.APPLICATION_TREE
                and document["issue_number"] == fixed.ISSUE, "PG533_ORIGINAL_CANDIDATE_MISMATCH")
    prior_bytes = {name: (prior / name).read_bytes() for name in
                   ("manifest.json", "junit.xml", "stdout.txt", "test_inventory.txt")}
    for name, field in (("manifest.json", "manifest_sha256"), ("junit.xml", "junit_sha256"),
                        ("stdout.txt", "stdout_sha256"), ("test_inventory.txt", "test_inventory_sha256")):
        require(sha(prior_bytes[name]) == bundle["machine_job"][field], "PG533_PRIOR_DIGEST_MISMATCH")
    old = cases(prior_bytes["junit.xml"])
    retained = [c for c in old if c.get("classname") == "tests.test_depth25_migration_history"]
    require(len(old) == 20 and len(retained) == 9, "PG533_PRIOR_CASE_COUNTS_MISMATCH")
    manifest = json.loads((fresh / "manifest.json").read_bytes())
    require(manifest.get("candidate_sha") == fixed.CANDIDATE
            and manifest.get("application_tree") == fixed.APPLICATION_TREE
            and manifest.get("inventory") == fixed.INVENTORY
            and type(manifest.get("exit_code")) is int and manifest["exit_code"] == 0
            and manifest.get("step_outcome") == "success"
            and manifest.get("docker_used") is True, "PG533_FRESH_MANIFEST_MISMATCH")
    for name, field in (("junit.xml", "junit_sha256"), ("stdout.txt", "stdout_sha256"),
                        ("database.json", "database_sha256")):
        require(sha((fresh / name).read_bytes()) == manifest.get(field), "PG533_FRESH_DIGEST_MISMATCH")
    db = json.loads((fresh / "database.json").read_bytes())
    require(db.get("candidate_sha") == fixed.CANDIDATE
            and db.get("application_tree") == fixed.APPLICATION_TREE
            and db.get("profile") == fixed.PROFILE
            and type(db.get("pytest_exit_code")) is int and db["pytest_exit_code"] == 0,
            "PG533_DATABASE_BINDING_MISMATCH")
    new = cases((fresh / "junit.xml").read_bytes())
    nodeids = [c.get("classname").replace(".", "/") + ".py::" + c.get("name") for c in new]
    # Validate inventory/counts without importing pytest in the reviewer process.
    expected_selection(nodeids)
    require(set(db.get("observed_cases", {})) == set(nodeids), "PG533_MISSING_PER_CASE_DB_OBSERVATION")
    observation = {"dialect": "postgresql", "server_version_num": 180004, "database": "c13_lite"}
    for node in nodeids:
        require(db["observed_cases"][node] == {"before": observation, "after": observation},
                "PG533_CASE_NOT_OBSERVED_ON_POSTGRES")
    # Preserve source parts byte-for-byte BEFORE producing an aggregate. The prior
    # eleven business cases are superseded, never represented as PostgreSQL passes.
    parts = fresh / "parts"
    parts.mkdir(exist_ok=True)
    for name in ("manifest.json", "junit.xml", "stdout.txt", "database.json", "test_inventory.txt"):
        shutil.copyfile(fresh / name, parts / ("postgres-" + name))
    for name, value in prior_bytes.items():
        (parts / ("prior-" + name)).write_bytes(value)
    (parts / "prior-c13_bundle.json").write_bytes((prior_review / "c13_bundle.json").read_bytes())
    (parts / "prior-c14_bundle.json").write_bytes((c14_dir / "c14_bundle.json").read_bytes())
    suite = ET.Element("testsuite", name="PG533 mixed database evidence", tests="24",
                       failures="0", errors="0", skipped="0")
    for case in retained + new:
        suite.append(copy.deepcopy(case))
    write_aggregate(fresh / "junit.xml", ET.tostring(suite, encoding="utf-8", xml_declaration=True))
    output = (b"RETAINED SOURCE: prior run 37484199333; only 9 SQLite migration cases retained.\n"
              + prior_bytes["stdout.txt"]
              + b"\nFRESH SOURCE: 15 PostgreSQL business cases; prior 11 business cases superseded.\n"
              + (parts / "postgres-stdout.txt").read_bytes())
    write_aggregate(fresh / "stdout.txt", output)
    write_aggregate(fresh / "test_inventory.txt", (fixed.FULL_INVENTORY + "\n").encode("utf-8"))
    manifest.update(inventory=fixed.FULL_INVENTORY,
                    junit_sha256=sha((fresh / "junit.xml").read_bytes()),
                    stdout_sha256=sha(output), github_run_id=run_id, github_run_attempt=run_attempt,
                    database_observation=db,
                    evidence_parts=[
                        {"source_run_id": fixed.C13_RUN, "source_run_attempt": 1,
                         "dialect": "sqlite", "retained_cases": 9, "superseded_business_cases": 11,
                         "inventory": fixed.MIGRATION, "c13_root": fixed.C13_ROOT},
                        {"source_run_id": run_id, "source_run_attempt": run_attempt,
                         "dialect": "postgresql", "server_version_num": 180004,
                         "fresh_cases": 15, "inventory": fixed.INVENTORY}],
                    part_sha256={p.name: sha(p.read_bytes()) for p in parts.iterdir()},
                    authorizes_any_action=False)
    write_aggregate(fresh / "manifest.json", (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8"))
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "assemble"))
    parser.add_argument("--prior")
    parser.add_argument("--prior-review")
    parser.add_argument("--c14")
    parser.add_argument("--fresh")
    args = parser.parse_args()
    if args.action == "prepare":
        print("supplement=" + ("true" if prepare(os.environ) else "false"))
    else:
        assemble(Path(args.prior), Path(args.prior_review), Path(args.c14), Path(args.fresh),
                 run_id=int(os.environ["GITHUB_RUN_ID"]), run_attempt=int(os.environ["GITHUB_RUN_ATTEMPT"]))


if __name__ == "__main__":
    main()
