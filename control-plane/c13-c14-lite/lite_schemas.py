"""JSON Schema documents, generated from the single source of truth.

The field tuples live in the modules that enforce them (``lite_candidate``,
``lite_bundle``, ``lite_execution_record``), so a schema file can never silently
drift away from the validator. ``check`` is asserted by the test suite.

These schemas describe shape. They are deliberately *not* the acceptance rule: the
binding, independence and prerequisite rules live in the verifier, because a schema
cannot express "this root must be recomputable from the received bytes".
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lite_bundle  # noqa: E402
import lite_candidate  # noqa: E402
import lite_errors  # noqa: E402
import lite_execution_record  # noqa: E402

SCHEMA_DIR = ROOT / "schemas"

GIT_SHA = {"type": "string", "pattern": "^[0-9a-f]{40}$"}
SHA256 = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
NONEMPTY = {"type": "string", "minLength": 1}
NONCE = {"type": "string", "minLength": 16}
TIMESTAMP = {"type": "string", "format": "date-time"}
LEDGER_REFERENCE = {
    "type": ["object", "null"],
    "additionalProperties": False,
    "required": ["round_id", "cell_id", "task_id"],
    "properties": {"round_id": NONEMPTY, "cell_id": {"enum": ["C13", "C14"]}, "task_id": NONEMPTY},
}
FINDING = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "severity", "statement"],
    "properties": {
        "id": NONEMPTY,
        "severity": {"enum": list(lite_bundle.SEVERITIES)},
        "statement": NONEMPTY,
    },
}
AUTHORIZES_FALSE = {"const": False}
ARTIFACT = {
    "type": "object",
    "additionalProperties": False,
    "required": list(lite_execution_record.ARTIFACT_FIELDS),
    "properties": {
        "name": NONEMPTY,
        "id": {"type": "integer", "minimum": 1},
        "digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    },
}


def _object(title, fields, properties, *, description=""):
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://go.local/c13c14-lite/{title}.schema.json",
        "title": title,
        "description": description,
        "type": "object",
        "additionalProperties": False,
        "required": sorted(fields),
        "properties": properties,
    }


def candidate_schema() -> dict:
    props = {
        "schema_version": {"const": lite_candidate.SCHEMA_VERSION},
        "repository": NONEMPTY,
        "candidate_commit_sha": GIT_SHA,
        "application_tree": GIT_SHA,
        "cell_id": {"enum": ["C13", "C14"]},
        "task_id": NONEMPTY,
        "issue_number": {"type": ["integer", "null"], "minimum": 1},
        "ledger_reference": LEDGER_REFERENCE,
        "request_id": NONEMPTY,
        "nonce": NONCE,
        "issued_at": TIMESTAMP,
        "expires_at": TIMESTAMP,
        "workflow_identity": NONEMPTY,
        "workflow_sha": GIT_SHA,
        "review_scope_sha256": SHA256,
        "prompt_sha256": SHA256,
    }
    return _object(
        "frozen-candidate-v1",
        lite_candidate.FIELDS,
        props,
        description="Frozen candidate contract. Never a branch head; always an exact commit.",
    )


def _common_props(cell, schema_version, scope_field, root_field):
    return {
        "schema_version": {"const": schema_version},
        "cell_id": {"const": cell},
        "task_id": NONEMPTY,
        "issue_number": {"type": ["integer", "null"], "minimum": 1},
        "ledger_reference": LEDGER_REFERENCE,
        "candidate_sha": GIT_SHA,
        "application_tree": GIT_SHA,
        "nonce": NONCE,
        scope_field: SHA256,
        "github_run_id": {"type": "integer", "minimum": 1},
        "github_run_attempt": {"type": "integer", "minimum": 1},
        "workflow_ref": NONEMPTY,
        "workflow_sha": GIT_SHA,
        "ai_provider": NONEMPTY,
        "ai_model": NONEMPTY,
        "ai_execution_id": NONEMPTY,
        "principal_id": NONEMPTY,
        "review_execution_id": NONEMPTY,
        "prompt_sha256": SHA256,
        "input_sha256": SHA256,
        "opinion_sha256": SHA256,
        "verdict": {"enum": list(lite_errors.C14_VERDICTS if cell == "C14" else lite_errors.C13_VERDICTS)},
        "failure_class": {"type": ["string", "null"], "enum": [*lite_errors.FAILURE_CLASSES, None]},
        "issued_at": TIMESTAMP,
        "authorizes_any_action": AUTHORIZES_FALSE,
        root_field: SHA256,
    }


def c14_bundle_schema() -> dict:
    props = _common_props("C14", lite_bundle.SCHEMA_VERSION_C14, "rule_review_scope_sha256", lite_bundle.C14_ROOT_FIELD)
    props.update({
        "applicable_rules": {"type": "array", "items": NONEMPTY, "minItems": 1},
        "applicable_rule_versions": {"type": "object", "patternProperties": {"^.+$": NONEMPTY}},
        "not_applicable": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": list(lite_bundle.NOT_APPLICABLE_FIELDS),
            "properties": {name: NONEMPTY for name in lite_bundle.NOT_APPLICABLE_FIELDS},
        },
        "findings": {"type": "array", "items": FINDING},
        "blocking_issues": {"type": "array", "items": NONEMPTY},
        "remediation_status": {"enum": list(lite_bundle.REMEDIATION_STATUSES)},
    })
    return _object(
        lite_bundle.SCHEMA_VERSION_C14,
        lite_bundle.C14_FIELDS,
        props,
        description="Sealed C14 rule / compliance record. NOT_APPLICABLE is a recorded terminal state, never a skip.",
    )


def c14_na_record_schema() -> dict:
    schema = c14_bundle_schema()
    schema["$id"] = "https://go.local/c13c14-lite/c14_na_record_v1.schema.json"
    schema["title"] = "go.c13c14.lite.c14_na_record.v1"
    schema["description"] = (
        "The NOT_APPLICABLE variant of the C14 record: same record type, verdict fixed to "
        "NOT_APPLICABLE, and the scope / basis / rule-version stanza mandatory."
    )
    schema["properties"] = dict(schema["properties"], verdict={"const": "NOT_APPLICABLE"})
    schema["properties"]["not_applicable"] = {
        "type": "object",
        "additionalProperties": False,
        "required": list(lite_bundle.NOT_APPLICABLE_FIELDS),
        "properties": {name: NONEMPTY for name in lite_bundle.NOT_APPLICABLE_FIELDS},
    }
    return schema


def c13_bundle_schema() -> dict:
    props = _common_props("C13", lite_bundle.SCHEMA_VERSION_C13, "quality_test_scope_sha256", lite_bundle.C13_ROOT_FIELD)
    props.update({
        "c14_prerequisite": {
            "type": "object",
            "additionalProperties": False,
            "required": list(lite_bundle.PREREQUISITE_FIELDS),
            "properties": {
                "c14_root": SHA256,
                "c14_verdict": {"enum": list(lite_errors.C14_VERDICTS)},
                "c14_candidate_sha": GIT_SHA,
                "c14_rule_scope_sha256": SHA256,
                "c14_remediation_closed": {"type": "boolean"},
            },
        },
        "machine_job": {
            "type": "object",
            "additionalProperties": False,
            "required": list(lite_bundle.MACHINE_JOB_FIELDS),
            "properties": {
                "runner": NONEMPTY,
                "runner_os": NONEMPTY,
                "postgres_version": NONEMPTY,
                "docker_used": {"type": "boolean"},
                "test_inventory_sha256": SHA256,
                "junit_sha256": SHA256,
                "stdout_sha256": SHA256,
                "manifest_sha256": SHA256,
            },
        },
        "junit_sha256": SHA256,
        "stdout_sha256": SHA256,
        "manifest_sha256": SHA256,
        "quality_findings": {"type": "array", "items": FINDING},
        "remaining_risks": {"type": "array", "items": NONEMPTY},
    })
    return _object(
        lite_bundle.SCHEMA_VERSION_C13,
        lite_bundle.C13_FIELDS,
        props,
        description="Sealed C13 quality acceptance: machine-test evidence plus one fresh AI review.",
    )


def execution_record_schema() -> dict:
    props = {
        "schema_version": {"const": lite_execution_record.SCHEMA_VERSION},
        "cell_id": {"enum": ["C13", "C14"]},
        "task_id": NONEMPTY,
        "issue_number": {"type": ["integer", "null"], "minimum": 1},
        "ledger_reference": LEDGER_REFERENCE,
        "candidate_sha": GIT_SHA,
        "application_tree": GIT_SHA,
        "github_run_id": {"type": "integer", "minimum": 1},
        "github_run_attempt": {"type": "integer", "minimum": 1},
        "workflow_ref": NONEMPTY,
        "workflow_sha": GIT_SHA,
        "ai_execution_id": NONEMPTY,
        "principal_id": NONEMPTY,
        "review_execution_id": NONEMPTY,
        "verdict": {"enum": [*lite_errors.C14_VERDICTS]},
        "failure_class": {"type": ["string", "null"], "enum": [*lite_errors.FAILURE_CLASSES, None]},
        "root_hash": SHA256,
        "artifact": ARTIFACT,
        "evidence_path": NONEMPTY,
        "issued_at": TIMESTAMP,
        "authorizes_any_action": AUTHORIZES_FALSE,
    }
    return _object(
        lite_execution_record.SCHEMA_VERSION,
        lite_execution_record.FIELDS,
        props,
        description="How one execution of a cell task is identified: cell + existing task + this GitHub run.",
    )


def final_root_schema() -> dict:
    props = {
        "schema_version": {"const": "go.c13c14.lite.final_root.v1"},
        "FINAL_ROOT": SHA256,
        "body": {
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "candidate_sha", "application_tree", "C14", "C13", "ledger_binding", "CC_WITNESS", "HK_WITNESS", "authorizes_any_action"],
            "properties": {
                "schema_version": {"const": "go.c13c14.lite.final_root.v1"},
                "candidate_sha": GIT_SHA,
                "application_tree": GIT_SHA,
                "C14": {"type": "object"},
                "C13": {"type": "object"},
                "ledger_binding": {"type": "object"},
                # Reserved for the next round: CC witness / HK witness. Null now.
                "CC_WITNESS": {"type": ["object", "null"]},
                "HK_WITNESS": {"type": ["object", "null"]},
                "authorizes_any_action": AUTHORIZES_FALSE,
            },
        },
    }
    return _object(
        "go.c13c14.lite.final_root.v1",
        ("schema_version", "FINAL_ROOT", "body"),
        props,
        description="Aggregate root over both sealed bundles and the ledger binding; witness slots reserved.",
    )


SCHEMAS = {
    "frozen_candidate_v1.schema.json": candidate_schema,
    "c14_bundle_v1.schema.json": c14_bundle_schema,
    "c14_na_record_v1.schema.json": c14_na_record_schema,
    "c13_bundle_v1.schema.json": c13_bundle_schema,
    "execution_record_v1.schema.json": execution_record_schema,
    "final_root_v1.schema.json": final_root_schema,
}


def render(name: str) -> str:
    return json.dumps(SCHEMAS[name](), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def write_all(directory=SCHEMA_DIR) -> list:
    path = pathlib.Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    written = []
    for name in SCHEMAS:
        (path / name).write_text(render(name), encoding="utf-8")
        written.append(name)
    return written


def check(directory=SCHEMA_DIR) -> list:
    """Return the schema files that are missing or out of date."""
    path = pathlib.Path(directory)
    stale = []
    for name in SCHEMAS:
        target = path / name
        if not target.is_file() or target.read_text(encoding="utf-8") != render(name):
            stale.append(name)
    return stale


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=str(SCHEMA_DIR))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        stale = check(args.out_dir)
        print(json.dumps({"schemas": len(SCHEMAS), "stale": stale}, ensure_ascii=False))
        return 0 if not stale else 1
    print(json.dumps({"written": write_all(args.out_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
