"""Locate the Lite V2 contract modules and put them on the import path.

The witness layer consumes the backend's contracts; it never re-implements them.
A single place does the wiring so the modules below can just
``import lw_paths; lw_paths.install()`` and then import ``lite_*`` normally.
"""
from __future__ import annotations

import pathlib
import sys

WITNESS_DIR = pathlib.Path(__file__).resolve().parent
LITE_DIR = WITNESS_DIR.parent / "c13-c14-lite"

REQUIRED_LITE_MODULES = (
    "lite_canonical",
    "lite_errors",
    "lite_candidate",
    "lite_identity",
    "lite_bundle",
    "lite_prerequisite",
    "lite_execution_record",
    "lite_github_run",
    "lite_artifact_fetch",
    "lite_ledger_binding",
    "lite_aggregate",
    "lite_chain",
)


def install() -> pathlib.Path:
    """Make ``lite_*`` importable and fail loudly if the backend is missing."""
    if not LITE_DIR.is_dir():
        raise RuntimeError(f"c13-c14-lite backend not found at {LITE_DIR}")
    if str(LITE_DIR) not in sys.path:
        sys.path.insert(0, str(LITE_DIR))
    return LITE_DIR
