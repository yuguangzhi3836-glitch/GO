"""Command Center ReviewVerifier.

CC verifies; it does not run an AI model, Docker, PostgreSQL or candidate code.
This module adds the two things the backend deliberately left to the next layer:

1. the artifact levels (metadata always, bytes only with a capable credential);
2. a single, explicit verification record that a witness can sign.

Everything else — candidate binding, per-cell task binding, independence, the C14
prerequisite gate, root recomputation and tamper detection — is the backend's
``lite_chain.verify_round``, called here rather than re-implemented.
"""
from __future__ import annotations

import lw_paths

lw_paths.install()

import lite_chain  # noqa: E402
import lite_errors  # noqa: E402

import lw_artifact  # noqa: E402

SCHEMA_VERSION = "go.c13c14.witness.verification.v1"


def verify(
    *,
    c14_bundle,
    c13_bundle,
    c14_contract,
    c13_contract,
    dispatch,
    implementation_execution_id,
    artifacts=None,
    c14_run=None,
    c14_artifact_payload=None,
    c14_expectation=None,
    c13_run=None,
    c13_artifact_payload=None,
    c13_expectation=None,
    artifact_downloader=None,
    now=None,
) -> dict:
    """Verify a whole round and return one verification record.

    Raises ``Reject`` only when a *metadata* level check fails — that is hard
    evidence of tampering or a wrong identity. A bytes level failure is recorded,
    never raised: it is a credential capability boundary.
    """
    decision = lite_chain.verify_round(
        c14_bundle=c14_bundle,
        c13_bundle=c13_bundle,
        c14_contract=c14_contract,
        c13_contract=c13_contract,
        dispatch=dispatch,
        implementation_execution_id=implementation_execution_id,
        artifacts=artifacts,
        now=now,
    )

    record = {
        "schema_version": SCHEMA_VERSION,
        "decision": decision.decision,
        "ok": decision.ok,
        "rejects": decision.rejects,
        "blocks": decision.blocks,
        "c14_root": decision.c14_root,
        "c13_root": decision.c13_root,
        "eligibility": decision.eligibility,
        "independence": decision.independence,
        "candidate_sha": None,
        "application_tree": None,
        "artifact": {"c14": None, "c13": None},
        "artifact_metadata_verified": False,
        "artifact_bytes_verified": False,
        "authorizes_any_action": False,
    }
    if not decision.ok:
        # Nothing further can be asserted about an unaccepted round.
        return record

    record["candidate_sha"] = c14_bundle["candidate_sha"]
    record["application_tree"] = c14_bundle["application_tree"]

    for role, run, payload, expectation in (
        ("c14", c14_run, c14_artifact_payload, c14_expectation),
        ("c13", c13_run, c13_artifact_payload, c13_expectation),
    ):
        if run is None or payload is None or expectation is None:
            record["artifact"][role] = {
                "level_1": None,
                "metadata_verified": False,
                "bytes_verified": False,
                "bytes_failure_class": lw_artifact.ARTIFACT_BYTES_UNAVAILABLE,
                "bytes_reason": "artifact_payload_not_supplied",
            }
            continue
        record["artifact"][role] = lw_artifact.verify(
            run, payload, expectation=expectation, downloader=artifact_downloader
        )

    record["artifact_metadata_verified"] = all(
        record["artifact"][role]["metadata_verified"] for role in ("c14", "c13")
    )
    record["artifact_bytes_verified"] = all(
        record["artifact"][role]["bytes_verified"] for role in ("c14", "c13")
    )
    return record


def expectation_for(*, role: str, bundle, run_id: int, expected_head_sha: str, workflow_path: str,
                    artifact_digest=None) -> dict:
    """Build the artifact expectation for one role from the sealed bundle."""
    return {
        "run_id": run_id,
        "expected_head_sha": expected_head_sha,
        "workflow_path": workflow_path,
        "artifact_name": lite_github_run_expected_name(role, bundle["candidate_sha"]),
        "artifact_digest": artifact_digest,
    }


def lite_github_run_expected_name(role: str, candidate_sha: str) -> str:
    import lite_github_run

    return lite_github_run.expected_artifact_name(role, candidate_sha)


__all__ = ["SCHEMA_VERSION", "verify", "expectation_for", "lite_errors"]
