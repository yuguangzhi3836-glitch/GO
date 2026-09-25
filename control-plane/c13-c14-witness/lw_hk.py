"""Hong Kong lightweight AcceptanceWitness (task section 15).

HK does **not** run a C13/C14 AI, Docker, PostgreSQL, or any quality suite. It
reads the already-produced identities and metadata, recomputes what it can, and
signs its own witness record. The whole module is pure standard library plus
signature verification: there is no network call and no dependency on the HK
deploy executor, so nothing here can disturb the #245 executor target.

The HK witness key is a **dedicated** Ed25519 key (purpose
``c13c14-acceptance-witness-hk``). It must not be the existing HK evidence key:
deployment evidence signing and acceptance witness signing are different jobs.
As with CC, this module never installs a key.
"""
from __future__ import annotations

import lw_paths

lw_paths.install()

import lite_canonical  # noqa: E402
from lite_errors import Reject  # noqa: E402

import lw_witness  # noqa: E402

SCHEMA_VERSION = "go.c13c14.witness.hk_witness.v1"

#: What HK is allowed to do, recorded so the boundary is machine-readable.
HK_CAPABILITIES = (
    "read_bundle_identities",
    "read_github_run_and_artifact_metadata",
    "recompute_available_hashes",
    "verify_roots",
    "verify_candidate_identity",
    "compare_cc_witness",
    "persist_first_seen_record",
    "sign_hk_witness",
)

#: Explicitly refused, so an integration cannot quietly grow.
HK_REFUSALS = (
    "run_c13_or_c14_ai",
    "run_docker",
    "run_postgresql",
    "run_quality_suite",
    "sign_deployment_evidence",
    "authorize_any_action",
)


def witness(*, verification: dict, cc_witness: dict, key, first_seen: dict, issued_at: str) -> dict:
    """Produce the HK witness for a verification CC has already witnessed."""
    lw_witness.verify_witness(cc_witness)
    compare_with_cc(cc_witness, verification)
    record = lw_witness.build_witness(
        witness_role="HK",
        verification=verification,
        key=key,
        first_seen=first_seen,
        issued_at=issued_at,
        schema_version=SCHEMA_VERSION,
    )
    if record["witness_purpose"] != lw_witness.HK_PURPOSE:
        raise Reject("hk_witness_purpose_invalid")
    return record


#: witness field -> verification field. Spelled out rather than derived, because
#: guessing it from letter case produced a wrong comparison once already.
COMPARE_FIELDS = (
    ("candidate_sha", "candidate_sha"),
    ("application_tree", "application_tree"),
    ("C14_ROOT", "c14_root"),
    ("C13_ROOT", "c13_root"),
)


def compare_with_cc(cc_witness: dict, verification: dict) -> None:
    """HK must be able to re-derive CC's claims from the same verification record."""
    for witness_field, verification_field in COMPARE_FIELDS:
        if cc_witness.get(witness_field) != verification.get(verification_field):
            raise Reject("hk_cc_witness_disagreement", witness_field)
    for role in ("c14", "c13"):
        cc_meta = cc_witness["artifact_metadata"][role]
        verification_meta = verification["artifact"][role]
        if cc_meta.get("artifact_digest") != verification_meta["artifact"]["digest"]:
            raise Reject("hk_cc_artifact_digest_disagreement", role)
        if cc_meta.get("run_id") != verification_meta["run"]["id"]:
            raise Reject("hk_cc_run_id_disagreement", role)


def recompute_available_hashes(*, bundles: dict, first_seen: dict) -> dict:
    """Recompute the roots HK is able to check without any heavyweight tooling."""
    import lite_bundle

    result = {}
    for role in ("c14", "c13"):
        bundle = bundles.get(role)
        if bundle is None:
            result[role] = {"root_matches": False, "reason": "bundle_not_supplied"}
            continue
        lite_bundle.verify_root(bundle)
        root_field = lite_bundle.C14_ROOT_FIELD if role == "c14" else lite_bundle.C13_ROOT_FIELD
        expected = first_seen.get(f"{role}_root")
        result[role] = {
            "root_field": root_field,
            "recomputed_root": bundle[root_field],
            "root_matches": expected is None or bundle[root_field] == expected,
            "candidate_sha": bundle["candidate_sha"],
            "application_tree": bundle["application_tree"],
            "bundle_digest": lite_canonical.digest(bundle),
        }
    return result
