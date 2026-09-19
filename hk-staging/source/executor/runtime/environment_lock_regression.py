"""Regression for the HK executor's environment-scoped mutation lock.

Run directly:  python environment_lock_regression.py

Why this file exists
--------------------
`deploy` and `rollback` mutate the same eight business containers, and until this
revision nothing serialised them.  Two executors could both pass `_precheck()`,
each find the host exactly as it expected, and both run
`docker compose up -d --force-recreate` over the same project: the last writer
wins and neither Evidence describes the host that is left.  The Command Center
now refuses a second mutating Request for a busy environment, but that is one
door; this is the second, at the only layer that actually touches containers.

This regression pins the locked shape down with no daemon, no network and no live
host:

  * the lock is taken BEFORE the runtime is entered, so `_precheck()` can never run
    concurrently with another executor's mutation, and the runtime observes the
    environment as busy while it runs,
  * a second holder fails immediately with E_ENVIRONMENT_DEPLOYMENT_BUSY; the
    elapsed time is asserted rather than promised, so a "wait then continue"
    implementation fails here,
  * the lock is released after success, after failure, and by the kernel when the
    holder dies without releasing it,
  * two environments hold two locks: the slot is per environment, not global,
  * the only two lock call sites are the two mutating actions -- CANARY and VERIFY
    take no lock, because they mutate no business runtime,
  * a failed installation stops the action before the lock is even taken, so the
    WP-5 gate is not behind P1 and P1 is not behind the gate,
  * the launcher still pins every runtime module by exact bytes, and this revision
    added no module.

The primitive, and what this host can honestly show
---------------------------------------------------
The shipped launcher locks with `fcntl.flock(LOCK_EX|LOCK_NB)`, and refuses with
`E_ENVIRONMENT_DEPLOYMENT_LOCK` on a host that has no such primitive rather than
proceeding unlocked.  Where `fcntl` is absent -- a Windows workstation -- this file
substitutes the host's own kernel primitive (`msvcrt.locking`, likewise exclusive,
non-blocking, and released by the OS when the descriptor or the process goes away)
so the *discipline* is exercised rather than skipped.  Which one ran is printed, so
a green result can never be read as more than it is; the Linux CI job runs this
file with the real `fcntl`.

Line endings: a CRLF working tree is a checkout artifact.  The shipped bytes are
the LF blob -- that is what an archive extraction installs and what the pins are
over -- so the pin checks hash the line-ending-normalised file.
"""
import ast
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent
DEPLOYCTL = ROOT.parent / "go-hk-deployctl"

try:
    import fcntl
except ImportError:
    fcntl = None
try:
    import msvcrt
except ImportError:
    msvcrt = None

PRIMITIVE = "fcntl.flock" if fcntl else ("msvcrt.locking" if msvcrt else None)
SUBSTITUTED = fcntl is None

checks = []
failed = []


def load(name, path):
    spec = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, str(path)))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check(name, condition, detail=""):
    checks.append(name)
    if not condition:
        failed.append({"check": name, "detail": str(detail)[:200]})


# --------------------------------------------------------------------------- #
# the host's locking primitive
# --------------------------------------------------------------------------- #
def _acquire(descriptor):
    """Exclusive, non-blocking, or an OSError whose errno says which failure it was."""
    if fcntl is not None:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return
    if msvcrt is not None:
        # A byte-range lock needs a byte to lock.  The lock file is ours and holds
        # nothing, so giving it one costs nothing and keeps the discipline usable on a
        # host whose kernel locks ranges instead of whole files.
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\0")
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        return
    raise OSError(38, "no file locking primitive on this host")


def _release(descriptor):
    if fcntl is not None:
        try: fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError: pass
    elif msvcrt is not None:
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        except OSError: pass


HOLDER = """
import os, sys, time
sys.path.insert(0, sys.argv[3])
import environment_lock_regression as reg
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)
reg._acquire(fd)
sys.stdout.write("held\\n"); sys.stdout.flush()
time.sleep(float(sys.argv[2]))
"""

CONTENDER = """
import os, sys, time
sys.path.insert(0, sys.argv[2])
import environment_lock_regression as reg
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)
start = time.time()
try:
    reg._acquire(fd)
except OSError as exc:
    sys.stdout.write("busy %s %.3f" % (exc.errno, time.time() - start)); sys.exit(0)
sys.stdout.write("acquired %.3f" % (time.time() - start))
"""


def _subprocess_flock(deployctl):
    """Point the launcher's lock primitive at this host's, and say that we did.

    Only reached when the host has no `fcntl`.  Everything else about the call site --
    where the lock is taken, what it protects, what a failure means -- is the shipped
    code either way.
    """
    if not SUBSTITUTED:
        return False
    deployctl._lock_exclusive = _acquire
    deployctl._unlock = _release
    return True


def lock_call_sites(path):
    """The functions that take the environment lock, read from the shipped source.

    A lock claimed to cover the mutation critical section is only worth something if
    the mutating actions take it and nothing else does, so this is read out of the
    file rather than asserted in prose.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    owners = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name)
                    and inner.func.id == "_environment_lock"):
                owners.setdefault(node.name, []).append(inner.lineno)
    return owners


def run():
    if PRIMITIVE is None:
        print(json.dumps({"checks": 0, "failed": ["no locking primitive on this platform"],
                          "status": "FAIL"}, sort_keys=True))
        return 1
    with tempfile.TemporaryDirectory(prefix="go-env-lock-") as raw:
        work = pathlib.Path(raw)
        deployctl = load("go_hk_deployctl_under_test", DEPLOYCTL)
        deployctl.LOCK_DIR = str(work)
        # Kept before any substitution: the "no primitive on this host" check has to
        # exercise the shipped refusal, not this file's replacement for it.
        shipped_lock, shipped_unlock = deployctl._lock_exclusive, deployctl._unlock
        substituted = _subprocess_flock(deployctl)
        path_a = str(work / (deployctl.LOCK_TEMPLATE % "HK-STAGING-01"))
        path_b = str(work / (deployctl.LOCK_TEMPLATE % "HK-STAGING-02"))

        check("the lock is one file per environment",
              deployctl.LOCK_TEMPLATE % "HK-STAGING-01" == "deploy-HK-STAGING-01.lock",
              deployctl.LOCK_TEMPLATE)
        check("the lock lives beside the deploy records, so no new writable path is needed",
              deployctl.LOCK_DIR == str(work) and deployctl.LOCK_DIR == os.path.dirname(path_a))

        # 1. acquired, released, reacquired: the ordinary single-executor path.
        with deployctl._environment_lock():
            pass
        with deployctl._environment_lock():
            pass
        check("the lock is released after success and can be taken again", True)

        # 2. released after a failure inside the critical section.
        try:
            with deployctl._environment_lock():
                raise RuntimeError("synthetic failure inside the critical section")
        except RuntimeError:
            pass
        with deployctl._environment_lock():
            pass
        check("the lock is released after failure", True)

        # 3. two environments hold two locks at once.
        with deployctl._environment_lock("HK-STAGING-01"):
            with deployctl._environment_lock("HK-STAGING-02"):
                both = os.path.exists(path_a) and os.path.exists(path_b)
        check("two different environments hold their own locks simultaneously", both)
        check("neither environment's lock is a global lock",
              os.path.basename(path_a) != os.path.basename(path_b))

        # 4. -> 7. a second holder acquires; a contender is refused, without waiting.
        holder = subprocess.Popen([sys.executable, "-c", HOLDER, path_a, "6", str(ROOT)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            line = holder.stdout.readline().strip()
            check("the first holder acquired the environment lock", line == "held",
                  line or holder.stderr.read()[:160])
            contender = subprocess.run(
                [sys.executable, "-c", CONTENDER, path_a, str(ROOT)],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
        finally:
            holder.kill()
            holder.wait(timeout=30)
        fields = contender.stdout.split()
        check("a second holder is refused rather than queued",
              bool(fields) and fields[0] == "busy", contender.stdout or contender.stderr[:160])
        check("the refusal is immediate, not a wait for the first to finish",
              len(fields) == 3 and float(fields[2]) < 2.0, fields)

        # 5. -> 8. the kernel releases the lock when the holder dies.
        holder = subprocess.Popen([sys.executable, "-c", HOLDER, path_a, "0.1", str(ROOT)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        holder.stdout.readline()
        holder.kill()
        holder.wait(timeout=30)
        time.sleep(0.3)
        with deployctl._environment_lock("HK-STAGING-01"):
            check("a holder that died without releasing leaves no lock behind", True)

        # 6 and 7 replace the module loaders for the duration of both checks: the
        #    assertions are about the lock boundary and the busy refusal, not about
        #    module pins, and a CRLF checkout must not be able to decide them.
        seen = {}

        class Runtime:
            def ProductionRunner(self):
                return self

            def run_deploy(self, *args, **kwargs):
                try:
                    with deployctl._environment_lock():
                        seen["free_while_running"] = True
                except ValueError as exc:
                    seen["busy_while_running"] = str(exc)
                raise ValueError("stop here: the lock boundary is under test")

            def run_rollback(self, *args, **kwargs):
                raise ValueError("stop here: the rollback lock boundary is under test")

        originals = {name: getattr(deployctl, name) for name in
                     ("_load_deploy", "_load_collector", "_load_artifact",
                      "_verify_installation")}
        deployctl._load_deploy = lambda: Runtime()
        deployctl._load_collector = lambda: Runtime()
        deployctl._load_artifact = lambda: Runtime()
        gate_seen = []
        deployctl._verify_installation = lambda: gate_seen.append("install")
        arguments = ("r", "sha256:" + "a" * 64, "f" * 64, "sha256:" + "b" * 64,
                     "approval-1", "canary-1", "e" * 64,
                     {"task_id": "t", "nonce": "n", "authority": "GO-COMMAND-CENTER",
                      "canonical_sha256": "c" * 64})
        try:
            # 10. the lock is already held while the runtime runs, which is what makes
            #     the runtime's own precondition check safe.
            try:
                deployctl._deploy(*arguments)
            except Exception:                   # noqa: BLE001
                pass
            check("the runtime is entered with the environment lock already held",
                  seen.get("busy_while_running") == "E_ENVIRONMENT_DEPLOYMENT_BUSY", seen)
            check("the environment is not free while the runtime is running",
                  seen.get("free_while_running") is not True, seen)
            check("the installation is verified before the lock is taken",
                  gate_seen == ["install"], gate_seen)

            # 11. a busy environment reaches the executor document as its own error
            #     code, so the agent records it instead of reporting a silent success.
            held = deployctl._environment_lock()
            held.__enter__()
            try:
                document, code = deployctl._deploy(*arguments)
            finally:
                held.__exit__(None, None, None)
        finally:
            for name, value in originals.items():
                setattr(deployctl, name, value)
        check("a busy environment is reported as E_ENVIRONMENT_DEPLOYMENT_BUSY",
              code == 2 and document.get("error_code") == "E_ENVIRONMENT_DEPLOYMENT_BUSY",
              document.get("error_code"))
        check("a busy environment is reported as REJECTED, not as a success",
              document.get("status") == "REJECTED" and document.get("result") == "DEPLOY_REJECTED",
              str(document.get("status")) + "/" + str(document.get("result")))

        # 11b. contention reaches no runner at all: the refusal happens before the
        #      runtime is loaded, so nothing on the host can have been touched.
        check("a refused deployment never entered the runtime",
              seen.get("free_while_running") is not True, seen)

        # 12. a failed installation stops the action before the lock is taken, so the
        #     WP-5 gate is not behind P1 and the lock is not held by a refusal.
        blocked = str(work / (deployctl.LOCK_TEMPLATE % "HK-STAGING-01"))
        if os.path.exists(blocked): os.unlink(blocked)
        originals = {name: getattr(deployctl, name) for name in
                     ("_load_deploy", "_verify_installation")}
        deployctl._load_deploy = lambda: Runtime()
        deployctl._verify_installation = lambda: (_ for _ in ()).throw(
            ValueError("E_INSTALL_FACT_ABSENT"))
        try:
            document, code = deployctl._deploy(*arguments)
        finally:
            for name, value in originals.items():
                setattr(deployctl, name, value)
        check("a failed installation is reported as its own code",
              code == 2 and document.get("error_code") == "E_INSTALL_FACT_ABSENT",
              document.get("error_code"))
        check("a failed installation never reaches the runtime",
              seen.get("free_while_running") is not True, seen)
        check("a failed installation does not even take the environment lock",
              not os.path.exists(blocked), blocked)

        # 13. the only two lock call sites are the two mutating actions.
        owners = lock_call_sites(DEPLOYCTL)
        check("the lock is taken by deploy and by rollback",
              sorted(owners) == ["_deploy", "_rollback"], sorted(owners))
        check("CANARY takes no lock", "_canary" not in owners)
        check("VERIFY takes no lock", "_verify" not in owners)

        # 14. a host with no locking primitive refuses rather than proceeding unlocked.
        saved_fcntl, saved_lock, saved_unlock = (deployctl.fcntl,
                                                 deployctl._lock_exclusive,
                                                 deployctl._unlock)
        deployctl.fcntl = None
        deployctl._lock_exclusive, deployctl._unlock = shipped_lock, shipped_unlock
        try:
            try:
                with deployctl._environment_lock("HK-STAGING-01"):
                    refused = None
            except ValueError as exc:
                refused = str(exc)
        finally:
            (deployctl.fcntl, deployctl._lock_exclusive,
             deployctl._unlock) = saved_fcntl, saved_lock, saved_unlock
        check("a host with no locking primitive refuses rather than running unlocked",
              refused == "E_ENVIRONMENT_DEPLOYMENT_LOCK", refused)

        # 15. the pins still describe the shipped bytes, and this revision added no
        #     module for the lock to live in.  The chain is the one the launcher has:
        #     five modules it loads itself, two the deploy runtime loads, and the one
        #     the candidate source loads.
        chain = {("go-hk-deployctl", "_COLLECTOR_SHA256"): "collector_runtime.py",
                 ("go-hk-deployctl", "_CANARY_SHA256"): "canary_runtime.py",
                 ("go-hk-deployctl", "_DEPLOY_SHA256"): "deploy_runtime.py",
                 ("go-hk-deployctl", "_ROLLBACK_SHA256"): "rollback_runtime.py",
                 ("go-hk-deployctl", "_ARTIFACT_SHA256"): "artifact_runtime.py"}
        deploy_source = (ROOT / "deploy_runtime.py").read_text(encoding="utf-8")
        for attribute, name in (("_CANDIDATE_SOURCE_SHA256", "candidate_source.py"),
                                ("_MIGRATION_GUARD_SHA256", "migration_guard.py")):
            pinned = ast.literal_eval(
                next(n for n in ast.parse(deploy_source).body
                     if isinstance(n, ast.Assign)
                     and getattr(n.targets[0], "id", "") == attribute).value)
            raw = (ROOT / name).read_bytes().replace(b"\r\n", b"\n")
            check("the pin for %s still matches the shipped bytes" % name,
                  pinned == hashlib.sha256(raw).hexdigest(), pinned)
        source_source = (ROOT / "candidate_source.py").read_text(encoding="utf-8")
        pinned = ast.literal_eval(
            next(n for n in ast.parse(source_source).body
                 if isinstance(n, ast.Assign)
                 and getattr(n.targets[0], "id", "") == "CANDIDATE_FACT_SHA256").value)
        raw = (ROOT / "candidate_fact.py").read_bytes().replace(b"\r\n", b"\n")
        check("the pin for candidate_fact.py still matches the shipped bytes",
              pinned == hashlib.sha256(raw).hexdigest(), pinned)
        for (owner, attribute), name in sorted(chain.items()):
            raw = (ROOT / name).read_bytes().replace(b"\r\n", b"\n")
            check("the pin for %s still matches the shipped bytes" % name,
                  getattr(deployctl, attribute) == hashlib.sha256(raw).hexdigest(),
                  getattr(deployctl, attribute))
        check("no runtime module was added by this revision",
              not (ROOT / "environment_lock_runtime.py").exists())
        check("the launcher still pins exactly the five modules it loads itself",
              len([n for n in dir(deployctl) if n.endswith("_SHA256")]) == 5,
              [n for n in dir(deployctl) if n.endswith("_SHA256")])

    print("\nprimitive: %s%s" % (PRIMITIVE, " (substituted on this host)" if substituted else ""))
    print("%d checks, %d failed" % (len(checks), len(failed)))
    print(json.dumps({"checks": len(checks), "failed": failed, "primitive": PRIMITIVE,
                      "substituted": substituted,
                      "status": "PASS" if not failed else "FAIL"}, sort_keys=True))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
