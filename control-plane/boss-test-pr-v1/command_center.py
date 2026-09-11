"""Fail-closed Command Center logic for the isolated HK_STAGING_TEST_PR flow.

This module intentionally has no publishing loop or real signing-key default:
installation supplies those two privileged adapters.  Keeping the untrusted
request parser and immutable source resolver pure makes their behavior
independently testable before any live installation.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import secrets
import subprocess
from dataclasses import dataclass
from typing import Any, Callable

GO_SOURCE_REPOSITORY = "git@github.com:yuguangzhi3836-glitch/GO.git"
ENVIRONMENT = "HK-STAGING-01"
ACTION = "HK_STAGING_TEST_PR"
REQUEST_FIELDS = frozenset({"schema_version", "request_id", "action_id", "environment", "pr_number", "requested_at"})
TASK_FIELDS = frozenset({"schema_version", "task_id", "environment", "action_id", "issued_at", "expires_at", "nonce", "authority", "source", "parameters", "signature"})
REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,79}$")
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
PR_NUMBER = re.compile(r"^[1-9][0-9]{0,8}$")
TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")


class Reject(ValueError):
    """A bounded, machine-readable reason to refuse an untrusted input."""


def canonical(value: dict[str, Any]) -> bytes:
    """The Task signing payload excludes exactly the detached signature."""
    return json.dumps({k: v for k, v in value.items() if k != "signature"}, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _time(value: object) -> dt.datetime:
    if not isinstance(value, str):
        raise Reject("requested_at_not_string")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Reject("requested_at_invalid") from exc
    if parsed.tzinfo is None:
        raise Reject("requested_at_timezone")
    return parsed


def validate_request(raw: bytes, at: dt.datetime | None = None) -> dict[str, Any]:
    """Accept a fresh Request that names only a GitHub PR number."""
    if not isinstance(raw, bytes) or len(raw) > 4096:
        raise Reject("request_size")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Reject("request_json") from exc
    if not isinstance(value, dict) or set(value) != REQUEST_FIELDS:
        raise Reject("request_schema")
    if value["schema_version"] != "1" or value["action_id"] != ACTION or value["environment"] != ENVIRONMENT:
        raise Reject("request_policy")
    if not isinstance(value["request_id"], str) or not REQUEST_ID.fullmatch(value["request_id"]):
        raise Reject("request_id")
    # JSON numbers are intentionally rejected: string form avoids a language-
    # specific integer range and a leading-zero ambiguity.
    if not isinstance(value["pr_number"], str) or not PR_NUMBER.fullmatch(value["pr_number"]):
        raise Reject("pr_number")
    requested_at = _time(value["requested_at"])
    at = at or utc_now()
    if requested_at > at + dt.timedelta(seconds=60) or at - requested_at > dt.timedelta(minutes=15):
        raise Reject("request_stale_or_future")
    return value


def _run_git(argv: list[str]) -> str:
    completed = subprocess.run(argv, check=True, shell=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    return completed.stdout


@dataclass(frozen=True)
class ResolvedPullRequest:
    number: str
    commit_sha: str


class GitHubPullRequestResolver:
    """Resolve one mutable PR head exactly once, then return only its SHA."""

    def __init__(self, runner: Callable[[list[str]], str] = _run_git):
        self._runner = runner

    def resolve(self, number: str) -> ResolvedPullRequest:
        if not isinstance(number, str) or not PR_NUMBER.fullmatch(number):
            raise Reject("pr_number")
        ref = f"refs/pull/{number}/head"
        try:
            output = self._runner(["/usr/bin/git", "ls-remote", GO_SOURCE_REPOSITORY, ref])
        except (OSError, subprocess.SubprocessError) as exc:
            raise Reject("pr_resolution_unavailable") from exc
        lines = output.splitlines()
        if len(lines) != 1:
            raise Reject("pr_head_not_found")
        parts = lines[0].split("\t")
        if len(parts) != 2 or parts[1] != ref or not COMMIT_SHA.fullmatch(parts[0]):
            raise Reject("pr_head_invalid")
        return ResolvedPullRequest(number=number, commit_sha=parts[0])


class TaskSigner:
    """Installation adapter.  The private key remains Command-Center-only."""

    def sign(self, payload: bytes) -> str:  # pragma: no cover - interface
        raise NotImplementedError


def derive_task(request: dict[str, Any], resolved: ResolvedPullRequest, signer: TaskSigner, at: dt.datetime | None = None) -> dict[str, Any]:
    """Bind a formal Task to a PR number *and* an immutable commit SHA."""
    if request.get("pr_number") != resolved.number or not COMMIT_SHA.fullmatch(resolved.commit_sha):
        raise Reject("resolution_binding")
    at = at or utc_now()
    # The SHA-derived suffix is deterministic for the source identity while the
    # nonce preserves the signed-task replay boundary.
    task_id = f"go-boss-test-pr-{resolved.number}-{resolved.commit_sha[:12]}"
    task = {
        "schema_version": "1",
        "task_id": task_id,
        "environment": ENVIRONMENT,
        "action_id": ACTION,
        "issued_at": iso(at),
        "expires_at": iso(at + dt.timedelta(minutes=20)),
        "nonce": secrets.token_urlsafe(24),
        "authority": "GO-COMMAND-CENTER",
        "source": {
            "repository": GO_SOURCE_REPOSITORY,
            "pr_number": resolved.number,
            "commit_sha": resolved.commit_sha,
        },
        # No image, command, path, network, Compose, service, or credential
        # parameter is controlled by the Boss Request or formal task.
        "parameters": {"builder_profile": "go-application-python-v1"},
    }
    task["signature"] = signer.sign(canonical(task))
    if set(task) != TASK_FIELDS or not TASK_ID.fullmatch(task_id):
        raise AssertionError("internal task schema")
    return task


def task_sha256(task: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(task)).hexdigest()


class ReplayLedger:
    """Small in-memory reference ledger; production supplies durable storage."""

    def __init__(self) -> None:
        self._request_ids: set[str] = set()
        self._sources: set[tuple[str, str]] = set()

    def claim(self, request: dict[str, Any], resolved: ResolvedPullRequest) -> None:
        key = (resolved.number, resolved.commit_sha)
        if request["request_id"] in self._request_ids:
            raise Reject("duplicate_request_id")
        if key in self._sources:
            raise Reject("duplicate_pr_commit")
        self._request_ids.add(request["request_id"])
        self._sources.add(key)
