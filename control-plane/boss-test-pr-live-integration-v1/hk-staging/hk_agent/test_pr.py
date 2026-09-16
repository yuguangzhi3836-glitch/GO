"""Fixed, isolated HK_STAGING_TEST_PR executor; no Compose or runtime bindings."""
import hashlib
import os
import pathlib
import re
import shutil
import stat
import subprocess
import tempfile

from . import artifact_store

ACTION = "HK_STAGING_TEST_PR"
PROFILE = "go-application-python-v1"   # the Task-facing contract: unchanged by V2
EXECUTOR_VERSION = "test-pr-v3"
REPOSITORY = "git@github.com:yuguangzhi3836-glitch/GO.git"
DEPLOY_KEY = "/etc/go-hk-agent/keys/github-go-source-reader"
DOCKERFILE = "/usr/local/libexec/go-hk-test-pr/Dockerfile.go-application-python-v2"
BUILD_ROOT = "/var/lib/go-hk-test-pr/builds"
# V3 keeps V2's builder pin and adds one step: the exact image this build
# produced is sealed into the fixed artifact store before the temporary tag is
# removed.  V2 reported built_image_id and then deleted the image, so the
# Evidence named an artifact that no longer existed anywhere and no later
# CANARY or DEPLOY could use it.
BUILDER_IMAGE = "go-hotel:depth48-runtime-6d0fd905"
BUILDER_IMAGE_ID = "sha256:1c9598d699c21620f4a3b489662f7b11be07acb46440516b74452dd2b6065132"
ARTIFACT_STORE = artifact_store.STORE_ROOT
DEPENDENCY_PROFILE_SHA256 = "904ede5e7ee3408e5f80bc2957d5f4b4d32754be6797bf6a53cff545b2fc94aa"
PYTHONPYCACHEPREFIX = "/tmp/pycache"
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


def _build_root():
    """Return the installer-provisioned per-agent build root, or fail closed."""
    root = pathlib.Path(BUILD_ROOT)
    try:
        info = root.lstat()
    except OSError as exc:
        raise Reject("TEST_PR_BUILD_ROOT_REJECT") from exc
    effective_uid = getattr(os, "geteuid", lambda: info.st_uid)()
    effective_gid = getattr(os, "getegid", lambda: info.st_gid)()
    if (stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or
            info.st_uid != effective_uid or info.st_gid != effective_gid or
            stat.S_IMODE(info.st_mode) != 0o700 or
            not os.access(root, os.W_OK | os.X_OK)):
        raise Reject("TEST_PR_BUILD_ROOT_REJECT")
    return root


PROFILE_PROGRAM = (
    "import tomllib,json,hashlib;"
    "p=tomllib.load(open('/input/pyproject.toml','rb'))['project'];"
    "v={'requires-python':p['requires-python'],'dependencies':p['dependencies'],"
    "'optional-dependencies':{'dev':p.get('optional-dependencies',{})['dev']}};"
    "print(hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest())"
)


def _dependency_profile(path, workspace, runner):
    try:
        resolved = path.resolve(strict=True)
        root = workspace.resolve(strict=True)
    except OSError as exc:
        raise Reject("TEST_PR_DEPENDENCY_PROFILE_REJECT") from exc
    if path.is_symlink() or not resolved.is_file() or root not in resolved.parents:
        raise Reject("TEST_PR_DEPENDENCY_PROFILE_REJECT")
    result = runner(["/usr/bin/docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
                     "--security-opt", "no-new-privileges", "--pids-limit", "32", "--memory", "128m", "--cpus", "0.25",
                     "--mount", "type=bind,src=%s,dst=/input/pyproject.toml,readonly" % resolved,
                     "--entrypoint", "python", BUILDER_IMAGE, "-c", PROFILE_PROGRAM], timeout=60).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{64}", result):
        raise Reject("TEST_PR_DEPENDENCY_PROFILE_REJECT")
    return result


def _builder_image(runner):
    actual = runner(["/usr/bin/docker", "image", "inspect", BUILDER_IMAGE, "--format", "{{.Id}}"], timeout=30).stdout.strip()
    if actual != BUILDER_IMAGE_ID:
        raise Reject("TEST_PR_BUILDER_IMAGE_REJECT")


def execute(task, runner=_run):
    source = validate_parameters(task["parameters"])
    commit = source["commit_sha"]
    root = _build_root()
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
        _builder_image(runner)
        if _dependency_profile(context / "pyproject.toml", context, runner) != DEPENDENCY_PROFILE_SHA256:
            raise Reject("TEST_PR_DEPENDENCY_PROFILE_REJECT")
        runner(["/usr/bin/docker", "build", "--network", "none", "--pull=false", "--file", DOCKERFILE, "--tag", image, str(context)], timeout=900)
        image_id = runner(["/usr/bin/docker", "image", "inspect", image, "--format", "{{.Id}}"], timeout=30).stdout.strip()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise Reject("TEST_PR_IMAGE_ID_REJECT")
        runner(["/usr/bin/docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--pids-limit", "128", "--memory", "768m", "--cpus", "1.00",
                "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m", "--env", "PYTHONPYCACHEPREFIX=" + PYTHONPYCACHEPREFIX,
                "--entrypoint", "/bin/sh", image, "-c",
                "python -m compileall -q /workspace/src && alembic heads"], timeout=180)
        # Only now, with every gate above already PASS, is the exact built image
        # made durable.  Sealing is the last step on purpose: an image that failed
        # a gate must never reach the store, and an image that passes is no longer
        # allowed to disappear with this process.
        package = artifact_store.seal(runner, image, image_id, root=ARTIFACT_STORE)
        return {
            "schema_version": "1", "executor_version": EXECUTOR_VERSION, "action_id": ACTION,
            "status": "SUCCESS", "result": "TEST_PR_OK",
            "source_pr_number": source["pr_number"], "source_commit_sha": commit,
            "task_canonical_sha256": hashlib.sha256(__import__("hk_agent.transport", fromlist=["canonical"]).canonical(task)).hexdigest(),
            "built_image_id": image_id,
            # The build identity and the delivery identity are both stated: the
            # first is what docker inspect reported, the second is the immutable
            # package a later CANARY or DEPLOY resolves this same image from.
            "artifact_durability": "PROVEN",
            "artifact_package": package,
            "gate_results": {"source_commit": "PASS", "offline_build": "PASS",
                             "isolated_runtime_checks": "PASS", "artifact_sealed": "PASS"},
            "application_health_proven": False, "deployment_performed": False,
        }
    finally:
        # The temporary build tag is still removed: the durable copy is the sealed
        # package, and leaving a second, untracked copy in Docker would be a
        # delivery path the store cannot vouch for.
        subprocess.run(["/usr/bin/docker", "image", "rm", "--force", image], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False, timeout=60)
        shutil.rmtree(workspace, ignore_errors=True)
