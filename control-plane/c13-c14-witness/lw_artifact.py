"""Two-level artifact verification, with the bytes level told honestly.

Measured in PR #248 and carried over verbatim as a constraint:

* a normal credential CAN read ``run`` metadata, ``artifact`` metadata and the
  GitHub-computed ``artifact.digest``;
* the artifact ZIP (and the job log) redirect to a storage endpoint that rejects
  that credential — from inside a run with the default token and from a
  workstation with the account token alike.

So there are two levels. ``metadata`` is always attempted. ``bytes`` is attempted
only when the caller supplies a downloader that can actually read the endpoint, and
a failure is recorded as ``ARTIFACT_BYTES_UNAVAILABLE`` with the reason. A bytes
failure is never reported as a pass, and never turned into a REJECT: it is a
**capability boundary**, not evidence of tampering.
"""
from __future__ import annotations

import lw_paths

lw_paths.install()

import lite_github_run  # noqa: E402

from lw_paths import LITE_DIR  # noqa: E402  (re-exported for callers that log it)

ARTIFACT_METADATA_VERIFIED = "ARTIFACT_METADATA_VERIFIED"
ARTIFACT_BYTES_VERIFIED = "ARTIFACT_BYTES_VERIFIED"
ARTIFACT_BYTES_UNAVAILABLE = "ARTIFACT_BYTES_UNAVAILABLE"

FIELDS = (
    "run_id",
    "expected_head_sha",
    "workflow_path",
    "artifact_name",
    "artifact_digest",
)


def verify(run, artifact, *, expectation, downloader=None) -> dict:
    """Verify one artifact at both levels.

    ``expectation`` must contain the four ``FIELDS``; ``artifact_digest`` may be
    None when the caller has no independent value to compare against (in which
    case the GitHub-computed digest is recorded, not asserted).
    """
    for field in FIELDS:
        if field not in expectation:
            raise lite_github_run.Reject("artifact_expectation_incomplete", field)

    # Level 1 - metadata. The run head is the workflow ref commit; the reviewed
    # candidate is bound elsewhere and must NOT be compared here.
    lite_github_run.assert_run_identity(
        run,
        run_id=expectation["run_id"],
        head_sha=expectation["expected_head_sha"],
        workflow_path=expectation["workflow_path"],
    )
    digest = artifact.get("digest")
    lite_github_run.assert_artifact(
        artifact,
        run_id=expectation["run_id"],
        name=expectation["artifact_name"],
        digest=digest,
    )
    expected_digest = expectation.get("artifact_digest")
    if expected_digest is not None and digest != expected_digest:
        raise lite_github_run.Reject("artifact_digest_altered", f"{digest} != {expected_digest}")

    record = {
        "level_1": ARTIFACT_METADATA_VERIFIED,
        "metadata_verified": True,
        "level_2": None,
        "bytes_verified": False,
        "bytes_failure_class": None,
        "bytes_reason": None,
        "run": {
            "id": run.get("id"),
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "head_sha": run.get("head_sha"),
            "path": run.get("path"),
            "workflow_ref": run.get("workflow_ref") or run.get("path"),
        },
        "artifact": {
            "id": artifact.get("id"),
            "name": artifact.get("name"),
            "digest": digest,
            "expired": bool(artifact.get("expired")),
            "size_in_bytes": artifact.get("size_in_bytes"),
            "workflow_run_id": (artifact.get("workflow_run") or {}).get("id"),
        },
        "authorizes_any_action": False,
    }

    # Level 2 - bytes. Only if this caller can actually read the endpoint.
    if downloader is None:
        record["level_2"] = ARTIFACT_BYTES_UNAVAILABLE
        record["bytes_failure_class"] = ARTIFACT_BYTES_UNAVAILABLE
        record["bytes_reason"] = "no_downloader_supplied_for_this_credential"
        return record
    try:
        raw = downloader(artifact)
        lite_github_run.assert_downloaded_bytes(raw, digest=digest)
    except Exception as error:  # noqa: BLE001 - the failure class is the point
        record["level_2"] = ARTIFACT_BYTES_UNAVAILABLE
        record["bytes_failure_class"] = ARTIFACT_BYTES_UNAVAILABLE
        record["bytes_reason"] = f"{type(error).__name__}: {str(error)[:160]}"
        return record
    record["level_2"] = ARTIFACT_BYTES_VERIFIED
    record["bytes_verified"] = True
    record["bytes_failure_class"] = None
    record["bytes_reason"] = None
    record["recomputed_digest"] = lite_github_run.local_digest(raw)
    return record
