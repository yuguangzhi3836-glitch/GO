"""Scoped retention runner, NOT the 18-group pre-external-payment gate.

Run with pytest to execute existing tests with their original fixture lifecycle.
Run as a script for the full readiness check: missing groups exit 2. Historical
PASS is never copied to main; no missing group is replaced with a weaker test.
"""
import ast
import importlib
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MATRIX = json.loads(Path(__file__).with_name("preexternal_retention_v87_matrix.json").read_text())


def node_exists(node):
    path, *symbols = node.split("::")
    source = ROOT / path
    if not source.is_file():
        return False
    children = ast.parse(source.read_text()).body
    for symbol in symbols:
        found = next(
            (
                n for n in children
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and n.name == symbol
            ),
            None,
        )
        if found is None:
            return False
        children = found.body
    return bool(symbols)


def missing_groups():
    return {
        g["id"]: [n for n in g["historical_nodes"] if not node_exists(n)]
        for g in MATRIX["groups"]
        if g["in_scope"] and any(not node_exists(n) for n in g["historical_nodes"])
    }


@pytest.mark.no_db
def test_matrix_preserves_full_denominator_and_missing_evidence():
    assert MATRIX["historical_baseline"]["matrix_denominator"] == 18
    assert MATRIX["historical_baseline"]["pass_transferred"] is False
    assert [g["id"] for g in MATRIX["groups"][:18]] == [f"R8-{i:02}" for i in range(1, 19)]
    assert MATRIX["full_acceptance"] == "BLOCKED_INTEGRATION_REQUIRED"
    actual = missing_groups()
    assert actual, "Baseline changed: reassess the complete matrix, do not silently grant PASS"
    for group in MATRIX["groups"]:
        if group["in_scope"]:
            assert group["missing_nodes"] == actual.get(group["id"], [])
            assert group["independent_review"] == "UNPROVEN_FOR_CURRENT_MAIN"
            assert group["execution"] == "NOT_RUN"


if __name__ == "__main__":
    print(json.dumps({
        "status": "BLOCKED",
        "historical_denominator": 18,
        "missing_groups": missing_groups(),
        "remaining": "PostgreSQL, omitted groups, unmerged fixes and independent full-scope review remain UNPROVEN",
    }, indent=2))
    raise SystemExit(2)
else:
    # Re-export exact existing functions: pytest supplies/reset fixtures for each
    # case, including original parametrization. Do not call two helpers in one DB
    # lifecycle; the recovered draft caused EMAIL_ALREADY_REGISTERED that way.
    _seen = set()
    for _group in MATRIX["groups"]:
        if not _group["in_scope"] or _group["missing_nodes"]:
            continue
        for _node in _group["historical_nodes"]:
            if _node in _seen:
                continue
            _path, _name = _node.split("::")
            if not _path.startswith("tests/test_") or not _path.endswith(".py") or ".." in _path:
                raise ValueError("Unsafe retention test path")
            if not _name.startswith("test_") or not node_exists(_node):
                raise ValueError("Missing retention test node")
            _module = importlib.import_module(_path[:-3].replace("/", "."))
            globals()["test_v87_" + _group["id"].replace("-", "_") + "_" + _name[5:]] = getattr(_module, _name)
            _seen.add(_node)
