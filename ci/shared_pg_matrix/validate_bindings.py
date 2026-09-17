"""Fail-closed validation for the issue-168 per-Cell PostgreSQL matrix."""
from __future__ import annotations
import json
import pathlib
import re
import sys

SHA1 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CELLS = ("C07", "C09", "C10", "C11")

def validate(data: dict) -> dict:
    if data.get("schema") != "go.shared-pg-matrix-bindings.v1":
        raise ValueError("WRONG_SCHEMA")
    cells = data.get("cells")
    if not isinstance(cells, dict) or tuple(sorted(cells)) != tuple(sorted(CELLS)):
        raise ValueError("WRONG_CELL_SET")
    shas = []
    for cell in CELLS:
        row = cells[cell]
        sha = row.get("candidate_sha", "")
        tree = row.get("application_tree", "")
        fingerprint = row.get("source_tree_fingerprint")
        if not SHA1.fullmatch(sha):
            raise ValueError(f"INVALID_CANDIDATE_SHA:{cell}")
        if not SHA1.fullmatch(tree):
            raise ValueError(f"INVALID_APPLICATION_TREE:{cell}")
        if cell == "C07":
            if fingerprint is not None:
                raise ValueError("C07_FINGERPRINT_MUST_BE_GATE_COMPUTED")
            if row.get("status") != "RETEST_REQUIRED":
                raise ValueError("C07_MUST_RETEST")
        else:
            if not SHA256.fullmatch(fingerprint or ""):
                raise ValueError(f"INVALID_SOURCE_FINGERPRINT:{cell}")
            if row.get("status") != "INHERIT_SUCCESS":
                raise ValueError(f"PASSED_CELL_MUST_BE_INHERITED:{cell}")
        if not row.get("entrypoint"):
            raise ValueError(f"MISSING_ENTRYPOINT:{cell}")
        shas.append(sha)
    if len(set(shas)) != len(shas):
        raise ValueError("DUPLICATE_CELL_CANDIDATE_SHA")
    policy = data.get("policy", {})
    if policy.get("inherit_success_without_rerun") != ["C09", "C10", "C11"]:
        raise ValueError("WRONG_INHERITANCE_SCOPE")
    if policy.get("resume_only") != ["C07"]:
        raise ValueError("WRONG_RESUME_SCOPE")
    return {"status": "PASS", "cells": list(CELLS), "distinct_candidates": len(shas)}

def main() -> None:
    path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path(__file__).with_name("bindings.json"))
    result = validate(json.loads(path.read_text(encoding="utf-8")))
    print(json.dumps(result, sort_keys=True))

if __name__ == "__main__":
    main()
