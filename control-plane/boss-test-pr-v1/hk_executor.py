"""HK isolated TEST_PR builder: fixed source identity, recipe, argv, and limits."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from command_center import ACTION, COMMIT_SHA, ENVIRONMENT, GO_SOURCE_REPOSITORY, TASK_FIELDS, canonical

PROFILE = "go-application-python-v1"
SOURCE_SUBDIRECTORY = "application"
DEPLOY_KEY = "/etc/go-hk-agent/keys/github-go-source-reader"
BUILD_ROOT = "/var/lib/go-hk-test-pr/builds"
DOCKERFILE = "/usr/local/libexec/go-hk-test-pr/Dockerfile.go-application-python-v1"
GIT = "/usr/bin/git"
DOCKER = "/usr/bin/docker"
IMAGE = re.compile(r"^go-hk-test-pr:[0-9a-f]{40}$")


class Reject(ValueError):
    pass


class SignatureVerifier:
    """Installation adapter; verifies the Command Center's detached signature."""

    def verify(self, payload: bytes, signature: str) -> bool:  # pragma: no cover - interface
        raise NotImplementedError


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise Reject(label)
    return value


def validate_task(task: dict[str, Any], verifier: SignatureVerifier, at: dt.datetime | None = None) -> dict[str, Any]:
    """Reject every variable that could turn source test into host control."""
    if not isinstance(task, dict) or set(task) != TASK_FIELDS:
        raise Reject("task_schema")
    if task.get("schema_version") != "1" or task.get("action_id") != ACTION or task.get("environment") != ENVIRONMENT or task.get("authority") != "GO-COMMAND-CENTER":
        raise Reject("task_policy")
    signature = task.get("signature")
    if not isinstance(signature, str) or not verifier.verify(canonical(task), signature):
        raise Reject("task_signature")
    source = task.get("source")
    if not isinstance(source, dict) or set(source) != {"repository", "pr_number", "commit_sha"}:
        raise Reject("source_schema")
    if source["repository"] != GO_SOURCE_REPOSITORY or not isinstance(source["pr_number"], str) or not re.fullmatch(r"[1-9][0-9]{0,8}", source["pr_number"]) or not isinstance(source["commit_sha"], str) or not COMMIT_SHA.fullmatch(source["commit_sha"]):
        raise Reject("source_binding")
    parameters = task.get("parameters")
    if parameters != {"builder_profile": PROFILE}:
        raise Reject("builder_profile")
    for key in ("task_id", "issued_at", "expires_at", "nonce"):
        _require_text(task.get(key), key)
    try:
        issued = dt.datetime.fromisoformat(task["issued_at"].replace("Z", "+00:00"))
        expires = dt.datetime.fromisoformat(task["expires_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise Reject("task_time") from exc
    at = at or dt.datetime.now(dt.timezone.utc)
    if issued.tzinfo is None or expires.tzinfo is None or issued >= expires or expires <= at:
        raise Reject("task_expired_or_invalid")
    return source


def source_reader_environment(base: dict[str, str] | None = None) -> dict[str, str]:
    """A fixed HK deploy key only; never inherit HTTPS credential helpers."""
    env = dict(base or {})
    env.pop("GIT_ASKPASS", None)
    # Do not let an HK user's global Git configuration select a credential
    # helper.  `/dev/null` is a fixed inert config on the target Linux host.
    env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_SSH_COMMAND"] = f"ssh -i {DEPLOY_KEY} -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes"
    return env


@dataclass
class Completed:
    returncode: int
    stdout: str = ""
    stderr: str = ""


def _run(argv: list[str], *, cwd: str | None = None, env: dict[str, str] | None = None, timeout: int = 300) -> Completed:
    completed = subprocess.run(argv, cwd=cwd, env=env, shell=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
    return Completed(completed.returncode, completed.stdout, completed.stderr)


class IsolatedTestPRExecutor:
    """Only fixed argv lists cross the HK host process boundary."""

    def __init__(self, runner: Callable[..., Completed] = _run, build_root: str = BUILD_ROOT, clock: Callable[[], dt.datetime] | None = None):
        self._runner = runner
        self._build_root = build_root
        self._clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))

    def _checked(self, argv: list[str], *, cwd: str | None = None, env: dict[str, str] | None = None, timeout: int = 300) -> Completed:
        result = self._runner(argv, cwd=cwd, env=env, timeout=timeout)
        if result.returncode != 0:
            raise Reject("subprocess_failed")
        return result

    @staticmethod
    def image_tag(commit_sha: str) -> str:
        tag = f"go-hk-test-pr:{commit_sha}"
        if not IMAGE.fullmatch(tag):
            raise Reject("image_tag")
        return tag

    def fetch_exact_source(self, commit_sha: str) -> str:
        """Fetch by SHA, not a PR ref, into a disposable HK builder directory."""
        if not COMMIT_SHA.fullmatch(commit_sha):
            raise Reject("commit_sha")
        Path(self._build_root).mkdir(mode=0o700, parents=True, exist_ok=True)
        workspace = tempfile.mkdtemp(prefix="source-", dir=self._build_root)
        env = source_reader_environment(os.environ)
        try:
            self._checked([GIT, "init", "--quiet", workspace], env=env)
            self._checked([GIT, "-C", workspace, "remote", "add", "origin", GO_SOURCE_REPOSITORY], env=env)
            # This is the immutable SHA already covered by the Command Center
            # signature.  No refs/pull/* or caller-provided ref reaches HK.
            self._checked([GIT, "-C", workspace, "fetch", "--no-tags", "--depth", "1", "origin", commit_sha], env=env)
            actual = self._checked([GIT, "-C", workspace, "rev-parse", "FETCH_HEAD"], env=env).stdout.strip()
            if actual != commit_sha:
                raise Reject("fetched_commit_mismatch")
            self._checked([GIT, "-C", workspace, "checkout", "--detach", "--quiet", commit_sha], env=env)
            if not Path(workspace, SOURCE_SUBDIRECTORY, "pyproject.toml").is_file():
                raise Reject("source_layout")
            return workspace
        except Exception:
            shutil.rmtree(workspace, ignore_errors=True)
            raise

    def run(self, task: dict[str, Any], verifier: SignatureVerifier) -> dict[str, Any]:
        source = validate_task(task, verifier, self._clock())
        commit_sha = source["commit_sha"]
        workspace: str | None = None
        image = self.image_tag(commit_sha)
        gates: dict[str, str] = {}
        try:
            workspace = self.fetch_exact_source(commit_sha)
            context = str(Path(workspace, SOURCE_SUBDIRECTORY))
            # Dockerfile is outside the checked source tree and profile-owned.
            self._checked([DOCKER, "build", "--network", "none", "--file", DOCKERFILE, "--tag", image, context], timeout=900)
            image_id = self._checked([DOCKER, "image", "inspect", image, "--format", "{{.Id}}"], timeout=30).stdout.strip()
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
                raise Reject("built_image_identity")
            gates["source_commit"] = "PASS"
            gates["offline_build"] = "PASS"
            # No mount, user, socket, or business network is supplied.  The
            # PR controls source bytes only; test argv remains profile-owned.
            self._checked([DOCKER, "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "128", "--memory", "768m", "--cpus", "1.00", "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m", image, "/bin/sh", "-c", "python -m compileall -q /workspace/src && alembic heads"], timeout=180)
            gates["isolated_runtime_checks"] = "PASS"
            return {
                "status": "SUCCESS",
                "result": "TEST_PR_OK",
                "source_pr_number": source["pr_number"],
                "source_commit_sha": commit_sha,
                "built_image_id": image_id,
                "gates": gates,
                "application_health_proven": False,
                "deployment_performed": False,
            }
        except Reject as exc:
            return {"status": "REJECTED", "result": "TEST_PR_REJECTED", "source_pr_number": source.get("pr_number"), "source_commit_sha": commit_sha, "gates": gates, "error_code": str(exc), "application_health_proven": False, "deployment_performed": False}
        finally:
            # Candidate image and fetched source are per-task temporary state.
            # The removal target is derived solely from a validated SHA.
            self._runner([DOCKER, "image", "rm", "--force", image], timeout=60)
            if workspace:
                shutil.rmtree(workspace, ignore_errors=True)


def evidence_payload(task: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Unsigned evidence body; HK's existing evidence signer owns the signature."""
    return {
        "schema_version": "1",
        "task_id": task["task_id"],
        "nonce": task["nonce"],
        "action_id": ACTION,
        "environment": ENVIRONMENT,
        "status": result["status"],
        "result": result["result"],
        "source": {"pr_number": result["source_pr_number"], "commit_sha": result["source_commit_sha"]},
        "gates": result["gates"],
        "application_health_proven": False,
        "deployment_performed": False,
        "task_canonical_sha256": hashlib.sha256(canonical(task)).hexdigest(),
    }
