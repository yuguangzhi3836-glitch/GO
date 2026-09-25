"""Fold per-host probe results into the CCV1-144A verdict.

The task's pass condition is four booleans. Deciding them in prose is how a
"blocked" round quietly becomes a "ready" round, so the decision lives here and is
unit-tested. Its rules:

* a host is *credential-ready* only when it can read the repository's Actions
  surface, not merely authenticate (an authenticated token that cannot see the
  repository answers 404 on every Actions read - the actual CC symptom);
* metadata verification requires both the run read and the artifact read, per host,
  and one host's success never substitutes for the other's;
* byte states are reported verbatim and never inferred from metadata;
* if the four host booleans are not all true, the round result is BLOCKED and the
  next round is blocked too, with the missing grant named.
"""
from __future__ import annotations

RESULT_READY = "WITNESS_GITHUB_READBACK_READY"
RESULT_METADATA_ONLY = "METADATA_WITNESS_READY_BYTES_UNAVAILABLE"
RESULT_BLOCKED = "BLOCKED_CREDENTIAL_PERMISSION"

ROUND_RESULTS = (RESULT_READY, RESULT_METADATA_ONLY, RESULT_BLOCKED)


def host_readiness(probe: dict, *, host: str) -> dict:
    """Normalise one host's probe report into the per-host booleans."""
    endpoints = probe.get("endpoints") or {}
    credential = probe.get("credential") or {}

    # A host with no credential cannot have completed any read. Gating on ``present``
    # makes the verdict immune to a self-contradictory probe report instead of
    # trusting whichever field happens to be checked first.
    present = bool(credential.get("present", False))
    authenticates = present and endpoints.get("user") == 200
    sees_repository = present and endpoints.get("repository") == 200
    run_read = present and endpoints.get("run") == 200
    artifact_read = present and endpoints.get("run_artifacts") == 200

    if not present:
        blocked_by = "no_github_api_credential_on_host"
    elif not authenticates:
        blocked_by = "credential_does_not_authenticate"
    elif not sees_repository:
        blocked_by = "credential_repository_scope"
    elif not run_read:
        blocked_by = "actions_read_not_granted"
    else:
        blocked_by = None

    return {
        "host": host,
        "credential_path": credential.get("path"),
        "credential_class": credential.get("class"),
        "credential_value_redacted": True,
        "authenticates": authenticates,
        "sees_repository": sees_repository,
        f"{host.upper()}_RUN_METADATA_READ": run_read,
        f"{host.upper()}_ARTIFACT_METADATA_READ": artifact_read,
        f"{host.upper()}_ARTIFACT_METADATA_VERIFIED": bool(run_read and artifact_read),
        f"{host.upper()}_GITHUB_API_CREDENTIAL_READY": bool(run_read and artifact_read),
        "blocked_by": blocked_by,
    }


def round_verdict(*, cc: dict, hk: dict, byte_states: dict | None = None) -> dict:
    """Combine both hosts into the round result and the next-round gate."""
    cc_ready = cc["CC_GITHUB_API_CREDENTIAL_READY"]
    hk_ready = hk["HK_GITHUB_API_CREDENTIAL_READY"]
    metadata_ready = bool(cc_ready and hk_ready)

    bytes_state = dict(byte_states or {})
    bytes_verified = bool(bytes_state.get("ARTIFACT_BYTES_VERIFIED", False))

    if not metadata_ready:
        result = RESULT_BLOCKED
    elif bytes_verified:
        result = RESULT_READY
    else:
        result = RESULT_METADATA_ONLY

    missing = []
    for label, data in (("cc", cc), ("hk", hk)):
        if data["blocked_by"]:
            missing.append({"host": label, "blocked_by": data["blocked_by"]})

    return {
        "schema_version": "go.c13c14.witness.credential_readiness.v1",
        "RESULT": result,
        "CC_GITHUB_API_CREDENTIAL_READY": cc_ready,
        "HK_GITHUB_API_CREDENTIAL_READY": hk_ready,
        "CC_RUN_METADATA_READ": cc["CC_RUN_METADATA_READ"],
        "HK_RUN_METADATA_READ": hk["HK_RUN_METADATA_READ"],
        "CC_ARTIFACT_METADATA_VERIFIED": cc["CC_ARTIFACT_METADATA_VERIFIED"],
        "HK_ARTIFACT_METADATA_VERIFIED": hk["HK_ARTIFACT_METADATA_VERIFIED"],
        "METADATA_WITNESS_READY": metadata_ready,
        "BYTE_LEVEL_WITNESS_READY": bytes_verified,
        "OWNER_ACTION_REQUIRED": bool(missing),
        "blocked": missing,
        "CCV1_145_FULL_CHAIN_SIMULATION": ("READY" if metadata_ready
                                           else "BLOCKED_CREDENTIAL_PERMISSION"),
        "authorizes_any_action": False,
    }
