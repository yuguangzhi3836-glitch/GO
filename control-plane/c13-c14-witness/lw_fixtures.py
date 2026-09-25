"""Synthetic fixtures for the witness layer. Everything is derived from seeds.

Reuses ``lite_fixtures`` for the bundles, so the witness tests exercise the same
contract the backend produces rather than a parallel one.
"""
from __future__ import annotations

import hashlib
import pathlib

import lw_paths

lw_paths.install()

import lite_bundle  # noqa: E402
import lite_canonical  # noqa: E402
import lite_execution_record  # noqa: E402
import lite_fixtures as fx  # noqa: E402

import lw_verifier  # noqa: E402
import lw_witness  # noqa: E402

#: The workflow ref commit. Deliberately NOT the candidate sha: that confusion was
#: a real failure in PR #248 and is guarded here on purpose.
CANDIDATE_SHA = fx.CANDIDATE_SHA
APPLICATION_TREE = fx.APPLICATION_TREE
C14_TASK = fx.C14_TASK
C13_TASK = fx.C13_TASK
WORKFLOW_REF_SHA = fx.seed_sha("synthetic-workflow-ref-commit")
C14_RUN_ID = 900001
C13_RUN_ID = 900002
C14_WORKFLOW = fx.C14_WORKFLOW
C13_WORKFLOW = fx.C13_WORKFLOW
CC_ISSUED_AT = "2026-09-25T09:10:00Z"
HK_ISSUED_AT = "2026-09-25T09:12:00Z"


def bundles():
    return fx.make_round()


def artifact_bytes(role: str) -> bytes:
    return lite_canonical.canonical({"role": role, "synthetic": True})


def artifact_digest(role: str) -> str:
    return "sha256:" + hashlib.sha256(artifact_bytes(role)).hexdigest()


def run_payload(role: str, *, head_sha=WORKFLOW_REF_SHA):
    return {
        "id": C14_RUN_ID if role == "c14" else C13_RUN_ID,
        "status": "completed",
        "conclusion": "success",
        "head_sha": head_sha,
        "path": C14_WORKFLOW if role == "c14" else C13_WORKFLOW,
        "run_attempt": 1,
        "workflow_ref": (C14_WORKFLOW if role == "c14" else C13_WORKFLOW),
    }


def artifact_payload(role: str, *, digest=None, name=None, run_id=None, expired=False):
    run = C14_RUN_ID if role == "c14" else C13_RUN_ID
    return {
        "id": 501 if role == "c14" else 502,
        "name": name or lite_github_run_name(role, CANDIDATE_SHA),
        "digest": digest or artifact_digest(role),
        "expired": expired,
        "size_in_bytes": len(artifact_bytes(role)),
        "workflow_run": {"id": run if run_id is None else run_id},
    }


def lite_github_run_name(role: str, candidate_sha: str) -> str:
    import lite_github_run

    return lite_github_run.expected_artifact_name(role, candidate_sha)


def expectation(role: str, *, digest=None, run_id=None, head_sha=WORKFLOW_REF_SHA, name=None):
    return {
        "run_id": (C14_RUN_ID if role == "c14" else C13_RUN_ID) if run_id is None else run_id,
        "expected_head_sha": head_sha,
        "workflow_path": C14_WORKFLOW if role == "c14" else C13_WORKFLOW,
        "artifact_name": name or lite_github_run_name(role, CANDIDATE_SHA),
        "artifact_digest": digest,
    }


def execution_records(round_=None):
    round_ = round_ or bundles()
    c14 = lite_execution_record.build(
        round_["c14_bundle"],
        artifact={"name": lite_github_run_name("c14", CANDIDATE_SHA), "id": 501,
                  "digest": artifact_digest("c14")},
        evidence_path="evidence/c14_bundle.json",
    )
    c13 = lite_execution_record.build(
        round_["c13_bundle"],
        artifact={"name": lite_github_run_name("c13", CANDIDATE_SHA), "id": 502,
                  "digest": artifact_digest("c13")},
        evidence_path="evidence/c13_bundle.json",
    )
    return c14, c13


def materialise(directory, round_=None):
    """Write the sealed bundles and the machine evidence; return the relative paths."""
    round_ = round_ or bundles()
    root = pathlib.Path(directory)

    def write(relative, raw):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return relative

    return {
        "c14": write("evidence/c14_bundle.json", lite_canonical.canonical(round_["c14_bundle"])),
        "c13": write("evidence/c13_bundle.json", lite_canonical.canonical(round_["c13_bundle"])),
        "junit": write("evidence/junit.xml", round_["artifacts"]["junit"]),
        "stdout": write("evidence/stdout.txt", round_["artifacts"]["stdout"]),
        "manifest": write("evidence/manifest.json", round_["artifacts"]["manifest"]),
    }


def verify_round(round_=None, *, downloader=None, c14_run=None, c13_run=None,
                 c14_artifact=None, c13_artifact=None, c14_expectation=None, c13_expectation=None):
    """Run the CC ReviewVerifier over a synthetic round."""
    round_ = round_ or bundles()
    return lw_verifier.verify(
        c14_bundle=round_["c14_bundle"],
        c13_bundle=round_["c13_bundle"],
        c14_contract=round_["c14_contract"],
        c13_contract=round_["c13_contract"],
        dispatch=round_["dispatch"],
        implementation_execution_id=round_["implementation_execution_id"],
        artifacts=round_["artifacts"],
        c14_run=c14_run or run_payload("c14"),
        c14_artifact_payload=c14_artifact or artifact_payload("c14"),
        c14_expectation=c14_expectation or expectation("c14"),
        c13_run=c13_run or run_payload("c13"),
        c13_artifact_payload=c13_artifact or artifact_payload("c13"),
        c13_expectation=c13_expectation or expectation("c13"),
        artifact_downloader=downloader,
        now=round_["now"],
    )


def cc_key(seed="cc-witness-test-key"):
    return lw_witness.WitnessKey.generate_ephemeral(lw_witness.CC_PURPOSE, seed=seed)


def hk_key(seed="hk-witness-test-key"):
    return lw_witness.WitnessKey.generate_ephemeral(lw_witness.HK_PURPOSE, seed=seed)


def first_seen(round_=None, at=CC_ISSUED_AT):
    round_ = round_ or bundles()
    c14_record, c13_record = execution_records(round_)
    return lw_witness.first_seen_from_execution_records(c14_record, c13_record, at=at)


def cc_witness_record(verification=None, *, key=None, round_=None, at=CC_ISSUED_AT):
    verification = verification or verify_round(round_)
    key = key or cc_key()
    return lw_witness.build_witness(
        witness_role="CC",
        verification=verification,
        key=key,
        first_seen=first_seen(round_, at=at),
        issued_at=at,
        schema_version=lw_witness.SCHEMA_VERSION_CC if hasattr(lw_witness, "SCHEMA_VERSION_CC")
        else "go.c13c14.witness.cc_witness.v1",
    )


def hk_witness_record(verification=None, cc_record=None, *, key=None, round_=None, at=HK_ISSUED_AT):
    import lw_hk

    verification = verification or verify_round(round_)
    cc_record = cc_record or cc_witness_record(verification, round_=round_)
    key = key or hk_key()
    return lw_hk.witness(
        verification=verification,
        cc_witness=cc_record,
        key=key,
        first_seen=first_seen(round_, at=at),
        issued_at=at,
    )


def bundle_fields(bundle):
    return lite_bundle.C14_ROOT_FIELD if bundle["cell_id"] == "C14" else lite_bundle.C13_ROOT_FIELD


# --- clean aliases so tests never have to reach through two levels -------------
OTHER_CANDIDATE_SHA = fx.OTHER_CANDIDATE_SHA
ISSUE_NUMBER = fx.ISSUE_NUMBER


def make_round(**overrides):
    return fx.make_round(**overrides)


def synthetic_ledger(**overrides):
    return fx.synthetic_ledger(**overrides)


def bundle_copy(bundle, **overrides):
    """Copy a sealed bundle with changes applied and the root recomputed."""
    import copy as _copy

    clone = _copy.deepcopy(bundle)
    for key, value in overrides.items():
        clone[key] = value
    root_field = lite_bundle.C14_ROOT_FIELD if clone["cell_id"] == "C14" else lite_bundle.C13_ROOT_FIELD
    clone[root_field] = "0" * 64
    return lite_bundle.seal(clone)
