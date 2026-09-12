"""Fixed, isolated HK_STAGING_TEST_PR executor; no Compose or runtime bindings."""
import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

ACTION = "HK_STAGING_TEST_PR"
PROFILE = "go-application-python-v1"
REPOSITORY = "git@github.com:yuguangzhi3836-glitch/GO.git"
DEPLOY_KEY = "/etc/go-hk-agent/keys/github-go-source-reader"
DOCKERFILE = "/usr/local/libexec/go-hk-test-pr/Dockerfile.go-application-python-v1"
BUILD_ROOT = "/var/lib/go-hk-test-pr/builds"
SHA = re.compile(r"^[0-9a-f]{40}$")
PR = re.compile(r"^[1-9][0-9]{0,8}$")


class Reject(Exception):
    pass


def validate_parameters(value):
    if not isinstance(value, dict) or set(value) != {"builder_profile", "source"}:
        raise Reject("TEST_PR_PARAMETERS_REJECT")
    source = value["source"]
    if value["builder_profile"] != PROFILE or not isinstance(source, dict) or set(source) != {"repository", "pr_number", "commit_sha"}:
        raise Reject("TEST_PR_PARAMETERS_REJECT")
    if source["repository"] != REPOSITORY or not isinstance(source["pr_number"], str) or not PR.fullmatch(source["pr_number"]) or not isinstance(source["commit_sha"], str) or not SHA.fullmatch(source["commit_sha"]):
        raise Reject("TEST_PR_SOURCE_REJECT")
    return source


def _env():
    return {
        "PATH": "/usr/bin:/bin",
        "LC_ALL": "C",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_SSH_COMMAND": "ssh -i %s -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes" % DEPLOY_KEY,
    }


def _run(argv, *, cwd=None, env=None, timeout=300):
    try:
        return subprocess.run(argv, cwd=cwd, env=env, check=True, shell=False, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.CalledProcessError as exc:
        error = Reject("TEST_PR_SUBPROCESS_REJECT")
        error.stdout, error.stderr, error.returncode, error.stage = exc.stdout, exc.stderr, exc.returncode, "subprocess"
        raise error from exc
    except (OSError, subprocess.SubprocessError) as exc:
        error = Reject("TEST_PR_SUBPROCESS_REJECT")
        error.stage = "subprocess"
        raise error from exc


def execute(task, runner=_run):
    source = validate_parameters(task["parameters"])
    commit = source["commit_sha"]
    root = pathlib.Path(BUILD_ROOT)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    workspace = pathlib.Path(tempfile.mkdtemp(prefix="source-", dir=root))
    image = "go-hk-test-pr:" + commit
    try:
        env = _env()
        runner(["/usr/bin/git", "init", "--quiet", str(workspace)], env=env)
        runner(["/usr/bin/git", "-C", str(workspace), "remote", "add", "origin", REPOSITORY], env=env)
        runner(["/usr/bin/git", "-C", str(workspace), "fetch", "--no-tags", "--depth", "1", "origin", commit], env=env)
        actual = runner(["/usr/bin/git", "-C", str(workspace), "rev-parse", "FETCH_HEAD"], env=env).stdout.strip()
        if actual != commit:
            raise Reject("TEST_PR_FETCH_MISMATCH")
        runner(["/usr/bin/git", "-C", str(workspace), "checkout", "--detach", "--quiet", commit], env=env)
        context = workspace / "application"
        if not (context / "pyproject.toml").is_file():
            raise Reject("TEST_PR_SOURCE_LAYOUT_REJECT")
        runner(["/usr/bin/docker", "build", "--network", "none", "--file", DOCKERFILE, "--tag", image, str(context)], timeout=900)
        image_id = runner(["/usr/bin/docker", "image", "inspect", image, "--format", "{{.Id}}"], timeout=30).stdout.strip()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise Reject("TEST_PR_IMAGE_ID_REJECT")
        runner(["/usr/bin/docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--pids-limit", "128", "--memory", "768m", "--cpus", "1.00",
                "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m", image, "/bin/sh", "-c",
                "python -m compileall -q /workspace/src && alembic heads"], timeout=180)
        return {
            "schema_version": "1", "executor_version": "test-pr-v1", "action_id": ACTION,
            "status": "SUCCESS", "result": "TEST_PR_OK",
            "source_pr_number": source["pr_number"], "source_commit_sha": commit,
            "task_canonical_sha256": hashlib.sha256(__import__("hk_agent.transport", fromlist=["canonical"]).canonical(task)).hexdigest(),
            "built_image_id": image_id,
            "gate_results": {"source_commit": "PASS", "offline_build": "PASS", "isolated_runtime_checks": "PASS"},
            "application_health_proven": False, "deployment_performed": False,
        }
    finally:
        subprocess.run(["/usr/bin/docker", "image", "rm", "--force", image], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False, timeout=60)
        shutil.rmtree(workspace, ignore_errors=True)
