"""Read back GitHub run and artifact identity through the API (task section 6).

V1's binding is a *read-only API readback*, never a run id string copied out of a
document. Two modes:

``in-run``   used inside the producing run: the run is not finished yet, so the
             identity fields are asserted but ``conclusion`` is recorded, not
             required. The artifact digest is still recomputed from the downloaded
             zip, which is the part an attacker cannot self-report.
``terminal`` used by a later reviewer (next round: CC / HK witness) against a
             finished run: ``completed`` + ``success`` are required.

The token is read from the environment and never written to any output file.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lite_github_run  # noqa: E402

API_ROOT = "https://api.github.com"


def _get(path: str, token: str, *, raw: bool = False):
    request = urllib.request.Request(
        API_ROOT + path,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "go-c13c14-lite-readback",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = response.read()
    return payload if raw else json.loads(payload.decode("utf-8"))


def _find_artifact(repository: str, run_id: int, name: str, token: str) -> dict:
    listing = _get(f"/repos/{repository}/actions/runs/{run_id}/artifacts", token)
    for artifact in listing.get("artifacts", []) or []:
        if artifact.get("name") == name:
            return artifact
    raise lite_github_run.Reject("artifact_not_found", name)


def readback(*, repository: str, role: str, candidate_sha: str, workflow_path: str,
             run_id: int, token: str, mode: str = "in-run", expected_head_sha=None) -> dict:
    """Read back the run and artifact identity of one execution.

    ``expected_head_sha`` is the commit the **workflow ref** was at when the run was
    created (``${{ github.sha }}``), which is what the API reports as
    ``run.head_sha``. It is deliberately a separate parameter from
    ``candidate_sha``: a review run checks the frozen candidate out into a
    subdirectory, so the run head is the workflow ref commit, not the reviewed
    candidate. The candidate is bound elsewhere, by the in-run
    ``git rev-parse HEAD`` check, by the artifact name, and by the sealed bundle.
    """
    expected_head_sha = expected_head_sha or candidate_sha
    run = _get(f"/repos/{repository}/actions/runs/{run_id}", token)
    if mode == "terminal":
        lite_github_run.assert_run(run, run_id=run_id, head_sha=expected_head_sha, workflow_path=workflow_path)
    else:
        lite_github_run.assert_run_identity(run, run_id=run_id, head_sha=expected_head_sha, workflow_path=workflow_path)

    name = lite_github_run.expected_artifact_name(role, candidate_sha)
    artifact = _find_artifact(repository, run_id, name, token)
    digest = artifact.get("digest")
    lite_github_run.assert_artifact(artifact, run_id=run_id, name=name, digest=digest)

    raw = _get(f"/repos/{repository}/actions/artifacts/{artifact['id']}/zip", token, raw=True)
    lite_github_run.assert_downloaded_bytes(raw, digest=digest)

    return {
        "schema_version": "go.c13c14.lite.readback.v1",
        "mode": mode,
        "repository": repository,
        "role": role,
        "run_id": run_id,
        "run_attempt": run.get("run_attempt"),
        "run_status": run.get("status"),
        "run_conclusion": run.get("conclusion"),
        "head_sha": run.get("head_sha"),
        "expected_head_sha": expected_head_sha,
        "candidate_sha": candidate_sha,
        "workflow_path": run.get("path"),
        "artifact": {
            "id": artifact["id"],
            "name": name,
            "digest": digest,
            "expired": bool(artifact.get("expired")),
        },
        "recomputed_digest": lite_github_run.local_digest(raw),
        "zip_bytes": len(raw),
        "verified_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "authorizes_any_action": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, choices=("c13", "c14"))
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--expected-head-sha",
                        help="the workflow ref commit the run was created from (${{ github.sha }}); "
                             "defaults to the candidate sha")
    parser.add_argument("--workflow-path", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--mode", choices=("in-run", "terminal"), default="in-run")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", "yuguangzhi3836-glitch/GO"))
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print(json.dumps({"error": "no_token"}))
        return 2
    try:
        record = readback(
            repository=args.repository,
            role=args.role,
            candidate_sha=args.candidate_sha,
            workflow_path=args.workflow_path,
            run_id=args.run_id,
            token=token,
            mode=args.mode,
            expected_head_sha=args.expected_head_sha,
        )
    except lite_github_run.Reject as error:
        print(json.dumps({"refused": error.reason, "detail": error.detail}))
        return 1
    path = pathlib.Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"artifact_id": record["artifact"]["id"], "digest": record["artifact"]["digest"], "match": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
