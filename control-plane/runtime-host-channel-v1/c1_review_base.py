"""Verify the frozen PR base before paid review or candidate tests.

Runs from the trusted backend checkout, never imports candidate code. The same PR
base/ref already enters Lite's facts/input digest through review_brief.

The binding normally travels WITH the round: the ingress freezes the candidate's real base
(whatever branch the PR is aimed at) and the identity rides in the existing transport
envelope. When a payload carries no binding - a round admitted before the binding existed -
this gate re-freezes the base from the brief's own live pull-request facts and checks it the
same way, rather than demanding that somebody retype it. `main` is therefore a common value
of the frozen base, never a precondition for being reviewable.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

from c1_execution_contract import Refused, validate_frozen_review_base


def verify(brief, frozen_base, candidate_sha, candidate):
    pull = brief.get("pull_request") or {}
    if frozen_base is None:
        # No carried binding: fall back to the brief's OWN live PR facts, which are the same
        # GitHub values the ingress would have frozen. Fail closed on a brief that cannot
        # name a base rather than skipping the check for it.
        frozen_base = {"ref": pull.get("base_ref"), "sha": pull.get("base_sha"),
                       "pr_number": pull.get("number")}
    base = validate_frozen_review_base(frozen_base)
    if (brief.get("status") != "OK" or brief.get("candidate_sha") != candidate_sha
            or pull.get("head_sha") != candidate_sha or pull.get("number") != base["pr_number"]
            or pull.get("base_ref") != base["ref"] or pull.get("base_sha") != base["sha"]):
        raise Refused("REVIEW_FROZEN_BASE_BRIEF_MISMATCH")
    def git(*args):
        return subprocess.run(["git", "-C", str(candidate), *args],
                              capture_output=True, text=True, check=False)
    head = git("rev-parse", "HEAD")
    if head.returncode or head.stdout.strip() != candidate_sha:
        raise Refused("REVIEW_FROZEN_BASE_CANDIDATE_MISMATCH")
    if git("merge-base", "--is-ancestor", base["sha"], candidate_sha).returncode:
        raise Refused("REVIEW_FROZEN_BASE_NOT_ANCESTOR")
    delta = git("diff", "--name-only", base["sha"], candidate_sha)
    if delta.returncode or not delta.stdout.strip():
        raise Refused("REVIEW_FROZEN_BASE_EMPTY_DIFF")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--brief", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    try:
        transport = json.loads(os.environ.get("RUNTIME_TRANSPORT", "{}"))
        verify(json.loads(args.brief.read_text()), transport.get("frozen_base"),
               os.environ["CANDIDATE_SHA"], args.candidate)
    except (Refused, ValueError, KeyError, TypeError, AttributeError, OSError) as error:
        raise SystemExit(error.reason if isinstance(error, Refused)
                         else "REVIEW_FROZEN_BASE_INPUT_INVALID") from None


if __name__ == "__main__":
    main()
