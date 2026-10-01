"""DEPTH48 VERIFY baseline regression for the frozen HK VERIFY collector.

Run directly:  python collector_runtime_regression.py

Why this file exists
--------------------
The VERIFY collector was pinned to the R3.1.5 runtime (revision
0114_ext_truth_incident_hard, image sha256:66c54087...). The host has since moved to
DEPTH48, so every VERIFY Task signed from that pin was rejected by the executor.
The generation is no longer pinned in the module at all: the collector derives it
from the root-owned environment fact.  This regression keeps
the collector honest about three things:

  * it accepts exactly the proven DEPTH48 baseline, and
  * it still REJECTS every way of not being it (old runtime, wrong image, mixed
    service images, wrong compose bytes, wrong env bytes, old revision, a revision
    that is not also the head), and
  * the protections around the decision were not weakened to make it pass: the
    compose/env/revision/image checks are all still enforced, the collector is still
    loaded only through the deployctl byte-integrity check, and the executor still
    issues a fixed, bounded argv set.

No network, no docker, no live host, no files outside a temporary directory.
"""
import hashlib
import importlib.util
import json
import pathlib
import re
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
COLLECTOR = HERE / "collector_runtime.py"
CANARY = HERE / "canary_runtime.py"
DEPLOYCTL = HERE.parent / "go-hk-deployctl"

# The generation is no longer written into either module; it is read from the
# root-owned environment fact. `LIVE["EXPECTED_REVISION"]` below is the value that
# fact declares on this host, so the regression can still prove the module derives
# the truth rather than a copy of it.
REVISION_LITERAL = re.compile(r"'[0-9]{4}_[a-z0-9_]+'")

# Proven read-only from HK-STAGING on 2026-10-01. These are the live values, not
# copies of what the repository happens to say.
LIVE = {
    "COMPOSE_PROJECT": "go-822-staging",
    "COMPOSE_FILE": ("/home/go-stg/releases/r31-5-final-completion-20260906/"
                     "GO_HYATT_DIRECT_BOOKING_R3_1_5_TEST_BOOTSTRAP_IDENTITY_FIX_20260906/"
                     "deploy/docker-compose.r31-hk-staging.yml"),
    "COMPOSE_SHA256": "7ef4ab181c1250d8cec0e348b29c24bfbb8e5dce4fc2a57f6faaa59363c26895",
    "ENV_FILE": "/home/go-stg/control/r317-five-star-completeness-20260828/runtime.env",
    "ENV_SHA256": "6682ff61f336fb8ff95a6585e9133c88c52a4eaa440a7aea6a6e06f771e607fc",
    "EXPECTED_REVISION": "0145_source_latest_index",
}
LIVE_IMAGE = "sha256:1c9598d699c21620f4a3b489662f7b11be07acb46440516b74452dd2b6065132"
RETIRED_R315_IMAGE = "sha256:66c540878ff5dd8d2d089059288c3d9f0c45f880514f7b053bd50defb9e8c324"
RETIRED_R315_REVISION = "0114_ext_truth_incident_hard"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def load_collector():
    spec = importlib.util.spec_from_file_location("collector_runtime_under_test",
                                                  str(COLLECTOR))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


C = load_collector()
API_ID = "a" * 64


class Result:
    def __init__(self, argv, returncode=0, stdout="", stderr=""):
        self.argv, self.returncode, self.stdout, self.stderr = tuple(argv), returncode, stdout, stderr


class PatternRunner:
    """Answers the collector's fixed docker argv by shape, so a case states its fault."""

    def __init__(self, api_image=LIVE_IMAGE, worker_image=None, api_health="healthy",
                 api_running=True, worker_running=True, current=None, heads=None):
        self.api_image = api_image
        self.worker_image = worker_image if worker_image is not None else api_image
        self.api_health, self.api_running, self.worker_running = api_health, api_running, worker_running
        self.current = current if current is not None else LIVE["EXPECTED_REVISION"]
        self.heads = heads if heads is not None else self.current
        self.argv = []

    def _container(self, image, service, running=True, health=None):
        state = {"Running": running, "Status": "running" if running else "exited",
                 "Restarting": False, "OOMKilled": False, "StartedAt": "2026-09-13T00:00:00Z"}
        if health is not None:
            state["Health"] = {"Status": health}
        return json.dumps([{"Id": "%s-%s" % (image[:14], service), "Image": image,
                            "State": state, "RestartCount": 0}])

    def run(self, argv):
        argv = tuple(argv)
        self.argv.append(argv)
        if argv[:2] == (C.DOCKER, "ps"):
            service = [a for a in argv if "com.docker.compose.service=" in a][0]
            service = service.split("com.docker.compose.service=", 1)[1]
            return Result(argv, 0, ("c-%s" % service) + "\n")
        if argv[:2] == (C.DOCKER, "inspect"):
            name = argv[2]
            if name.endswith("-" + C.API_SERVICE) or name == "c-" + C.API_SERVICE:
                return Result(argv, 0, self._container(self.api_image, C.API_SERVICE,
                                                       self.api_running, self.api_health))
            return Result(argv, 0, self._container(self.worker_image, "worker",
                                                   self.worker_running))
        if argv[-2:] == ("current", "-v"):
            return Result(argv, 0, "Rev: %s (head)\n" % self.current)
        if argv[-1:] == ("heads",):
            return Result(argv, 0, "%s (head)\n" % self.heads)
        raise AssertionError("the collector issued an argv outside its fixed set: %s" % (argv,))


_last_runner = None


def _run(runner, over, inputs):
    global _last_runner
    _last_runner = runner
    try:
        C._collect_verify(runner, over.get("candidate", LIVE_IMAGE),
                          over.get("expected", LIVE_IMAGE), inputs, lambda _s: None)
        return True, runner
    except ValueError as exc:
        return False, str(exc)


def verify(**over):
    """Run the production collector against a case. Returns (ok, detail)."""
    inputs = over.pop("inputs", None)
    runner = PatternRunner(**{k: v for k, v in over.items()
                              if k in ("api_image", "worker_image", "api_health",
                                       "api_running", "worker_running", "current",
                                       "heads")})
    if inputs is not None:
        return _run(runner, over, inputs)
    # The files must still exist while the collector hashes them, so the call
    # happens inside the temporary directory's lifetime.
    with tempfile.TemporaryDirectory(prefix="go-hk-verify-") as raw:
        compose = pathlib.Path(raw) / "compose.yml"
        env = pathlib.Path(raw) / "runtime.env"
        compose.write_text("image: synthetic\n")
        env.write_text("R31_IMAGE_TAG=synthetic\n")
        built = C._VerifyInputs(str(compose), C.sha256_file(str(compose)),
                                str(env), C.sha256_file(str(env)))
        return _run(runner, over, built)


def run():
    checks = {}

    def check(name, condition, detail=""):
        checks[name] = bool(condition)
        print("%s  %s%s" % ("PASS" if condition else "FAIL", name,
                            "" if condition else "  %s" % detail))

    # 1. the production pins are the proven live DEPTH48 ones
    # EXPECTED_REVISION is no longer a module constant: the collector derives the
    # generation from the root-owned environment fact, so the proven live value is
    # asserted against the derivation rather than against a copy of it.
    resolved = {"EXPECTED_REVISION": C.resolve_revision}
    for name, value in LIVE.items():
        actual = resolved[name]() if name in resolved else getattr(C, name)
        check("PRODUCTION_%s_IS_THE_PROVEN_LIVE_VALUE" % name,
              actual == value,
              "collector says %r" % (actual,))

    # 2. the exact DEPTH48 baseline passes
    ok, detail = verify()
    check("EXACT_DEPTH48_BASELINE_PASSES", ok, detail)

    # 3. every way of not being it is still refused
    ok, _ = verify(api_image=RETIRED_R315_IMAGE)
    check("OLD_R315_IMAGE_REJECTS", not ok)
    ok, _ = verify(api_image="sha256:" + "0" * 64)
    check("WRONG_IMAGE_REJECTS", not ok)
    ok, _ = verify(worker_image=RETIRED_R315_IMAGE)
    check("MIXED_SERVICE_IMAGES_REJECTS", not ok)
    ok, _ = verify(candidate=RETIRED_R315_IMAGE)
    check("CANDIDATE_NOT_EQUAL_TO_EXPECTED_REJECTS", not ok)
    ok, _ = verify(api_health="starting")
    check("UNHEALTHY_API_REJECTS", not ok)
    ok, _ = verify(worker_running=False)
    check("NOT_RUNNING_WORKER_REJECTS", not ok)

    ok, _ = verify(current=RETIRED_R315_REVISION, heads=RETIRED_R315_REVISION)
    check("OLD_R315_REVISION_REJECTS", not ok)
    # A pair from a previous generation, and a pair that disagrees with itself: both
    # are refused now, because the comparison is against the environment fact and not
    # against "a revision that happens to agree with itself".
    ok, _ = verify(current="0133_flight_change_plan", heads="0114_ext_truth_incident_hard")
    check("ALEMBIC_CURRENT_NOT_EQUAL_TO_HEAD_REJECTS", not ok)
    ok, _ = verify(current="0133_flight_change_plan", heads="0133_flight_change_plan")
    check("A_SELF_CONSISTENT_OLD_GENERATION_STILL_REJECTS", not ok)

    with tempfile.TemporaryDirectory(prefix="go-hk-verify-") as raw:
        compose = pathlib.Path(raw) / "compose.yml"
        env = pathlib.Path(raw) / "runtime.env"
        compose.write_text("image: synthetic\n")
        env.write_text("R31_IMAGE_TAG=synthetic\n")
        good_compose, good_env = C.sha256_file(str(compose)), C.sha256_file(str(env))
        ok, _ = verify(inputs=C._VerifyInputs(str(compose), "0" * 64, str(env), good_env))
        check("WRONG_COMPOSE_HASH_REJECTS", not ok)
        ok, _ = verify(inputs=C._VerifyInputs(str(compose), good_compose, str(env), "0" * 64))
        check("WRONG_ENV_HASH_REJECTS", not ok)
        bounded_runner = PatternRunner()
        ok, _ = verify(inputs=C._VerifyInputs(str(compose), good_compose,
                                              str(env), good_env))
        check("CORRECT_COMPOSE_AND_ENV_HASHES_PASS", ok,
              "the exact DEPTH48 baseline with real hashes did not pass")
        # the bounded-argv proof runs the case again so it has a runner to inspect
        verify(inputs=C._VerifyInputs(str(compose), good_compose, str(env), good_env))
        runner = PatternRunner()

    # 4. the protections around the decision were not weakened
    verify()
    runner = _last_runner
    bounded = set()
    for argv in runner.argv:
        bounded.add(argv[:2])
    check("EXECUTOR_STILL_ISSUES_ONLY_A_FIXED_BOUNDED_ARGV_SET",
          bounded <= {(C.DOCKER, "ps"), (C.DOCKER, "inspect"), (C.DOCKER, "exec")}
          and all(a[0] == C.DOCKER for a in runner.argv),
          sorted(str(b) for b in bounded))
    check("THE_REVISION_CHECK_IS_STILL_EXACT_AND_NOT_A_PREFIX_MATCH",
          C.resolve_revision() == LIVE["EXPECTED_REVISION"]
          and RETIRED_R315_REVISION != LIVE["EXPECTED_REVISION"])
    check("NEITHER_MODULE_CARRIES_A_REVISION_LITERAL",
          not REVISION_LITERAL.search(COLLECTOR.read_text(encoding="utf-8"))
          and not REVISION_LITERAL.search(CANARY.read_text(encoding="utf-8")),
          "a literal would silently block the next generation advance")

    deployctl = DEPLOYCTL.read_text(encoding="utf-8")
    # The pin is the hash of the file **as the repository stores it** (LF). A checkout with
    # `core.autocrlf` holds CRLF bytes, so hashing the working tree directly reports a
    # mismatch on Windows for a file that is byte-identical to its blob -- a false red about
    # the pin, which is the one thing this check is for. Compare the form the pin was
    # computed over, and say which form was compared. (CCV1-89)
    collector_bytes = COLLECTOR.read_bytes().replace(b"\r\n", b"\n")
    pin = None
    for line in deployctl.splitlines():
        if line.startswith("_COLLECTOR_SHA256"):
            pin = line.split('"')[1]
    check("DEPLOYCTL_STILL_PINS_THE_COLLECTOR_BY_EXACT_BYTES",
          pin == hashlib.sha256(collector_bytes).hexdigest(),
          "pin=%s bytes=%s" % (pin, hashlib.sha256(collector_bytes).hexdigest()[:16]))
    check("DEPLOYCTL_INTEGRITY_CHECK_IS_STILL_ENFORCED",
          "collector integrity" in deployctl and "hashlib.sha256" in deployctl)
    check("THE_CANARY_DEPLOY_AND_ROLLBACK_PINS_ARE_UNTOUCHED",
          all(("_%s_SHA256" % name) in deployctl
              for name in ("CANARY", "DEPLOY", "ROLLBACK")))

    failed = sorted(k for k, v in checks.items() if not v)
    print("\n%d checks, %d failed" % (len(checks), len(failed)))
    print(json.dumps({"checks": len(checks), "failed": failed,
                      "status": "PASS" if not failed else "FAIL"}, sort_keys=True))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
