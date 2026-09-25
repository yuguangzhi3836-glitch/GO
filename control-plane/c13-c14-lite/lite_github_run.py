"""GitHub run / artifact identity assertions (task section 6, V1 hard gate).

The V1 binding is *not* "the run id string the submitter wrote into the bundle".
It is: the bundle and root are uploaded as an Actions artifact, and the reviewer
re-reads, through the GitHub API only:

    GET /repos/{owner}/{repo}/actions/runs/{run_id}
    GET /repos/{owner}/{repo}/actions/artifacts/{artifact_id}
    GET /repos/{owner}/{repo}/actions/artifacts/{artifact_id}/zip

and recomputes the digest of the downloaded bytes instead of trusting the
recorded one. The precedent already exists in this repository
(``.github/workflows/c01-02-c13-independent.yml``). These helpers are pure
functions so they can be unit-tested against synthetic API payloads.
"""
from __future__ import annotations

import hashlib

from lite_errors import Reject


def local_digest(raw: bytes) -> str:
    """GitHub reports artifact digests as ``sha256:<hex>``."""
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def assert_run_identity(run, *, run_id: int, head_sha: str, workflow_path: str) -> None:
    """The identity assertions that hold even while the run is still in flight."""
    if not isinstance(run, dict):
        raise Reject("run_payload_not_an_object")
    if run.get("id") != run_id:
        raise Reject("run_id_mismatch")
    if run.get("head_sha") != head_sha:
        raise Reject("run_head_sha_mismatch")
    if run.get("path") != workflow_path:
        raise Reject("run_workflow_identity_mismatch", str(run.get("path")))


def assert_run(
    run,
    *,
    run_id: int,
    head_sha: str,
    workflow_path: str,
    conclusion: str = "success",
) -> None:
    """Terminal form: used by a reviewer reading back a *finished* run."""
    assert_run_identity(run, run_id=run_id, head_sha=head_sha, workflow_path=workflow_path)
    if run.get("status") != "completed":
        raise Reject("run_not_completed")
    if run.get("conclusion") != conclusion:
        raise Reject("run_conclusion_mismatch", str(run.get("conclusion")))


def assert_artifact(artifact, *, run_id: int, name: str, digest: str, expired: bool = False) -> None:
    if not isinstance(artifact, dict):
        raise Reject("artifact_payload_not_an_object")
    workflow_run = artifact.get("workflow_run")
    if not isinstance(workflow_run, dict) or workflow_run.get("id") != run_id:
        raise Reject("artifact_run_identity_mismatch")
    if artifact.get("name") != name:
        raise Reject("artifact_name_mismatch", str(artifact.get("name")))
    if artifact.get("digest") != digest:
        raise Reject("artifact_digest_mismatch")
    if bool(artifact.get("expired")) is not expired:
        raise Reject("artifact_expiry_mismatch")


def assert_downloaded_bytes(raw: bytes, *, digest: str) -> None:
    """Never trust the recorded digest: recompute it from the downloaded zip."""
    if local_digest(raw) != digest:
        raise Reject("artifact_bytes_digest_mismatch")


def expected_artifact_name(role: str, candidate_sha: str) -> str:
    """Deterministic artifact name: role + candidate, so a name cannot be reused
    for a different candidate without being detected."""
    if role not in ("c13", "c14"):
        raise Reject("artifact_role_invalid")
    return f"c13c14-lite-{role}-{candidate_sha}"
