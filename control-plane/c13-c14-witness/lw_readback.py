"""CC / HK witness readback: real GitHub facts, four separate artifact states.

This is the tool a witness host runs to answer, *from its own position*, whether the
C13/C14 claims about a remote GitHub run hold:

    run identity          id / status / conclusion / run_attempt / workflow path
    candidate binding     head_sha is the WORKFLOW REF commit, never the candidate
    artifact identity     name + GitHub-computed digest + not expired + same run
    artifact bytes        downloaded, re-hashed, compared

The four byte-level states are kept separate on purpose, because collapsing them is
how "we could not download it" turns into "verified":

    ARTIFACT_METADATA_VERIFIED    the API's own metadata agrees with the claim
    ARTIFACT_BYTES_AVAILABLE      the zip was actually received
    ARTIFACT_BYTES_HASHED         we computed a digest over those bytes
    ARTIFACT_BYTES_VERIFIED       that digest equals the claimed one

The credential is loaded from a file, used, and never rendered. The only token-shaped
thing any output may contain is ``Credential.summary()``.
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

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import lw_paths  # noqa: E402

lw_paths.install()

import lw_credential  # noqa: E402
import lite_artifact_fetch  # noqa: E402
import lite_github_run  # noqa: E402

API_ROOT = "https://api.github.com"
SCHEMA_VERSION = "go.c13c14.witness.readback.v1"


def _get_json(path: str, token: str, api_root: str = API_ROOT, timeout: int = 60):
    request = urllib.request.Request(
        api_root + path,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "go-c13c14-witness-readback",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def readback_role(*, repository: str, role: str, candidate_sha: str, workflow_path: str,
                  run_id: int, token: str, expected_head_sha: str | None = None,
                  expected_verdict: str | None = None, api_root: str = API_ROOT,
                  fetch_bytes: bool = True, timeout: int = 60) -> dict:
    """Verify one role's remote facts. Returns a record, never raises for a classified
    refusal, so a witness can record *why* it could not verify instead of crashing."""
    record = {
        "schema_version": SCHEMA_VERSION,
        "role": role,
        "repository": repository,
        "run_id": run_id,
        "candidate_sha": candidate_sha,
        "expected_head_sha": expected_head_sha or candidate_sha,
        "run_metadata_read": False,
        "artifact_metadata_read": False,
        "artifact_metadata_verified": False,
        "artifact_bytes_available": False,
        "artifact_bytes_hashed": False,
        "artifact_bytes_verified": False,
        "artifact_identity": None,
        "artifact_bytes_sha256": None,
        "artifact_zip_bytes": None,
        "bytes_failure_class": None,
        "redirect_host_category": None,
        "refusals": [],
        "authorizes_any_action": False,
        "read_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    try:
        run = _get_json(f"/repos/{repository}/actions/runs/{run_id}", token,
                        api_root=api_root, timeout=timeout)
    except urllib.error.HTTPError as error:
        record["refusals"].append(f"run_metadata_http_{error.code}")
        return record
    except (urllib.error.URLError, OSError, ValueError) as error:
        record["refusals"].append(f"run_metadata_transport_{type(error).__name__}")
        return record
    record["run_metadata_read"] = True
    record["run"] = {
        "id": run.get("id"),
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "run_attempt": run.get("run_attempt"),
        "head_sha": run.get("head_sha"),
        "head_branch": run.get("head_branch"),
        "path": run.get("path"),
        "repository": (run.get("repository") or {}).get("full_name"),
    }
    # The run head is the workflow ref commit; the candidate is bound by name and by
    # the sealed bundle. Comparing the two is the error this round exists to fix.
    if run.get("head_sha") != record["expected_head_sha"]:
        record["refusals"].append("run_head_sha_mismatch")
    if run.get("path") != workflow_path and workflow_path:
        record["refusals"].append("run_workflow_identity_mismatch")
    if run.get("status") != "completed":
        record["refusals"].append("run_not_completed")
    elif run.get("conclusion") != "success":
        record["refusals"].append("run_conclusion_not_success")

    try:
        listing = _get_json(f"/repos/{repository}/actions/runs/{run_id}/artifacts",
                            token, api_root=api_root, timeout=timeout)
    except urllib.error.HTTPError as error:
        record["refusals"].append(f"artifact_listing_http_{error.code}")
        return record
    except (urllib.error.URLError, OSError, ValueError) as error:
        record["refusals"].append(f"artifact_listing_transport_{type(error).__name__}")
        return record
    record["artifact_metadata_read"] = True
    record["artifact_count"] = listing.get("total_count")

    name = lite_github_run.expected_artifact_name(role, candidate_sha)
    match = None
    for artifact in listing.get("artifacts") or []:
        if artifact.get("name") == name:
            match = artifact
            break
    if match is None:
        record["refusals"].append("artifact_not_found")
        record["expected_artifact_name"] = name
        return record

    record["artifact_identity"] = {
        "id": match.get("id"),
        "name": match.get("name"),
        "digest": match.get("digest"),
        "size_in_bytes": match.get("size_in_bytes"),
        "expired": bool(match.get("expired")),
        "workflow_run_id": (match.get("workflow_run") or {}).get("id"),
    }
    try:
        lite_github_run.assert_artifact(match, run_id=run_id, name=name,
                                       digest=match.get("digest"))
    except lite_github_run.Reject as error:
        record["refusals"].append(f"artifact_{error.reason}")
        return record
    record["artifact_metadata_verified"] = True

    if not fetch_bytes:
        return record

    fetched = lite_artifact_fetch.fetch_artifact_bytes(
        repository=repository, artifact_id=match["id"], token=token,
        expected_digest=match.get("digest"), api_root=api_root, timeout=timeout,
    )
    record["artifact_bytes_available"] = fetched["available"]
    record["artifact_bytes_hashed"] = fetched["hashed"]
    record["artifact_bytes_verified"] = fetched["verified"]
    record["bytes_failure_class"] = fetched["failure_class"]
    record["redirect_host_category"] = fetched["redirect_host_category"]
    record["artifact_bytes_sha256"] = fetched["sha256"]
    record["artifact_zip_bytes"] = fetched["zip_bytes"]
    if not fetched["verified"] and fetched["failure_class"]:
        record["refusals"].append(f"bytes_{fetched['failure_class']}")
    return record


def capability_probe(*, repository: str, token: str, run_id: int | None = None,
                     api_root: str = API_ROOT, timeout: int = 30) -> dict:
    """The five reads a witness credential must be able to do, reported one by one.

    Deliberately reports per-endpoint status so "404 because the repo is not in the
    token's selection" is distinguishable from "the endpoint is missing".
    """
    checks = [
        ("user", "/user"),
        ("repository", f"/repos/{repository}"),
        ("actions_permissions", f"/repos/{repository}/actions/permissions"),
    ]
    if run_id:
        checks += [
            ("run", f"/repos/{repository}/actions/runs/{run_id}"),
            ("run_artifacts", f"/repos/{repository}/actions/runs/{run_id}/artifacts"),
        ]
    results = {}
    for label, path in checks:
        try:
            _get_json(path, token, api_root=api_root, timeout=timeout)
            results[label] = {"http": 200, "ok": True}
        except urllib.error.HTTPError as error:
            results[label] = {"http": error.code, "ok": False}
        except (urllib.error.URLError, OSError) as error:
            results[label] = {"http": None, "ok": False,
                              "transport": type(error).__name__}
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("cc", "hk"), required=True,
                        help="which credential path and custody to use")
    parser.add_argument("--role", choices=("c13", "c14"), required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--expected-head-sha")
    parser.add_argument("--workflow-path", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--repository", default=lw_credential.REPOSITORY)
    parser.add_argument("--credential-path",
                        help="override the credential path (used for testing)")
    parser.add_argument("--no-bytes", action="store_true",
                        help="metadata only; skips the zip download")
    parser.add_argument("--probe", action="store_true",
                        help="also run the five-endpoint capability probe")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    path = args.credential_path or lw_credential.CREDENTIAL_PATH[args.host]
    try:
        credential = lw_credential.load(path)
    except lw_credential.CredentialError as error:
        print(json.dumps({"error": str(error), "host": args.host, "path": path}))
        return 3

    record = readback_role(
        repository=args.repository, role=args.role, candidate_sha=args.candidate_sha,
        workflow_path=args.workflow_path, run_id=args.run_id, token=credential.token,
        expected_head_sha=args.expected_head_sha, fetch_bytes=not args.no_bytes,
    )
    record["host"] = args.host
    record["credential"] = credential.summary()
    if args.probe:
        record["capability_probe"] = capability_probe(
            repository=args.repository, token=credential.token, run_id=args.run_id)
        del record["credential"]["fingerprint"]  # keep evidence minimal

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                   encoding="utf-8")
    print(json.dumps({
        "host": args.host,
        "role": args.role,
        "run_metadata_read": record["run_metadata_read"],
        "artifact_metadata_verified": record["artifact_metadata_verified"],
        "artifact_bytes_verified": record["artifact_bytes_verified"],
        "refusals": record["refusals"],
    }))
    return 0 if record["artifact_metadata_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
