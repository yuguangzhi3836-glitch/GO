"""JSON Schemas for the witness layer, generated from the enforcing modules."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lw_paths  # noqa: E402

lw_paths.install()

import lw_aggregate  # noqa: E402
import lw_witness  # noqa: E402

SCHEMA_DIR = ROOT / "schemas"

SHA256 = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
GIT_SHA = {"type": "string", "pattern": "^[0-9a-f]{40}$"}
NONEMPTY = {"type": "string", "minLength": 1}
AUTHORIZES_FALSE = {"const": False}


def _object(title, fields, properties, description=""):
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://go.local/c13c14-witness/{title}.schema.json",
        "title": title,
        "description": description,
        "type": "object",
        "additionalProperties": False,
        "required": sorted(fields),
        "properties": properties,
    }


def witness_schema(*, title, role, schema_version, purpose):
    props = {
        "schema_version": {"const": schema_version},
        "witness_role": {"const": role},
        "witness_purpose": {"const": purpose},
        "key_id": NONEMPTY,
        "public_key_pem": NONEMPTY,
        "candidate_sha": GIT_SHA,
        "application_tree": GIT_SHA,
        "C14_ROOT": SHA256,
        "C13_ROOT": SHA256,
        "artifact_metadata": {"type": "object"},
        "verification": {"type": "object"},
        "first_seen": {"type": "object"},
        "issued_at": {"type": "string", "format": "date-time"},
        "authorizes_any_action": AUTHORIZES_FALSE,
        "signature": NONEMPTY,
    }
    return _object(title, lw_witness.WITNESS_FIELDS, props,
                   description="Signed witness record. It can never authorise an action.")


def cc_witness_schema():
    return witness_schema(title="go.c13c14.witness.cc_witness.v1", role="CC",
                          schema_version="go.c13c14.witness.cc_witness.v1",
                          purpose=lw_witness.CC_PURPOSE)


def hk_witness_schema():
    return witness_schema(title="go.c13c14.witness.hk_witness.v1", role="HK",
                          schema_version="go.c13c14.witness.hk_witness.v1",
                          purpose=lw_witness.HK_PURPOSE)


def first_seen_ledger_schema():
    props = {
        "schema_version": {"const": lw_witness.LEDGER_SCHEMA_VERSION},
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "required": sorted(lw_witness.FIRST_SEEN_IDENTITY_FIELDS + ("first_seen_at", "verification_status")),
                "properties": {
                    "candidate_sha": GIT_SHA, "application_tree": GIT_SHA,
                    "c14_task_id": NONEMPTY, "c14_run_id": {"type": "integer"},
                    "c14_execution_id": NONEMPTY, "c14_root": SHA256,
                    "c14_artifact_digest": NONEMPTY,
                    "c13_task_id": NONEMPTY, "c13_run_id": {"type": "integer"},
                    "c13_execution_id": NONEMPTY, "c13_root": SHA256,
                    "c13_artifact_digest": NONEMPTY,
                    "first_seen_at": {"type": "string", "format": "date-time"},
                    "verification_status": NONEMPTY,
                },
            },
        },
        "LEDGER_ROOT": SHA256,
    }
    return _object("go.c13c14.witness.first_seen_ledger.v1", lw_witness.LEDGER_FIELDS, props,
                   description="Append-only first-seen ledger. The key is the execution identity; "
                               "roots and digests are content, so a rewrite is a CONFLICT.")


def final_acceptance_schema():
    props = {
        "schema_version": {"const": lw_aggregate.SCHEMA_VERSION},
        "status": {"enum": [lw_aggregate.ACCEPTED, lw_aggregate.BLOCKED, lw_aggregate.REJECTED]},
        "gate": {"type": "string"},
        "candidate_sha": {"type": ["string", "null"]},
        "application_tree": {"type": ["string", "null"]},
        "C14_ROOT": {"type": ["string", "null"]},
        "C13_ROOT": {"type": ["string", "null"]},
        "CC_WITNESS": {"type": ["object", "null"]},
        "HK_WITNESS": {"type": ["object", "null"]},
        "artifact_metadata_verified": {"type": "boolean"},
        "artifact_bytes_verified": {"type": "boolean"},
        "human_authorization_required": {"const": True},
        "authorizes_any_action": AUTHORIZES_FALSE,
        "auto_deploy": AUTHORIZES_FALSE,
        "FINAL_ROOT": {"type": ["string", "null"]},
    }
    return _object("go.c13c14.witness.final_acceptance.v1", lw_aggregate.FIELDS, props,
                   description="An ACCEPTED result stops at READY_FOR_HUMAN_AUTHORIZATION and "
                               "structurally cannot deploy.")


SCHEMAS = {
    "cc_witness_v1.schema.json": cc_witness_schema,
    "hk_witness_v1.schema.json": hk_witness_schema,
    "first_seen_ledger_v1.schema.json": first_seen_ledger_schema,
    "final_acceptance_v1.schema.json": final_acceptance_schema,
}


def render(name: str) -> str:
    return json.dumps(SCHEMAS[name](), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def write_all(directory=SCHEMA_DIR):
    path = pathlib.Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    for name in SCHEMAS:
        (path / name).write_text(render(name), encoding="utf-8")
    return sorted(SCHEMAS)


def check(directory=SCHEMA_DIR):
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
