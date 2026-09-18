"""Regression for the HK rollback runtime's Compose argv.

Run directly:  python rollback_runtime_regression.py

Why this file exists
--------------------
The first live HK rollback came back as `EXECUTOR_NONZERO_EXIT` with the opaque error
code `docker read`.  Neither the signed source pair nor the authorisation was at
fault: the runtime built its Compose argv from the frozen R3.1.5 base file alone.
That file addresses its eight services by tag, this host holds the images by id only,
so Compose resolved a tag that is not present and tried to pull it, and
`docker compose up` exited non-zero.  DEPLOY never had the problem because it has
always merged an override naming its candidate by id.

This regression pins the corrected shape down with no daemon, no network and no live
host:

  * the rollback argv carries the base file *and* an override, and the override pins
    exactly the eight services to the ids the source deploy record carries,
  * the override is mode 0600, is read by Compose exactly once, and is removed on the
    success path and on the failure path alike,
  * the original failing shape -- a Compose invocation with no override -- is still
    refused by the same model, so the checks cannot pass by accident,
  * the run is not reported as restored until the api the record names is healthy,
  * a durable pre-mutation record is still written before Compose is called, and still
    survives a failed Compose,
  * none of the checks around the source pair were loosened to make this work: a
    consumed source, a tampered record and an unusable target are all still refused,
  * the launcher still pins this runtime by exact bytes and still enforces that, and
    the other four runtime pins are untouched.

Digests are compared against **committed** bytes, so the file's own line ending is
normalised first: this workstation's working tree is CRLF while the blob -- and the
copy HK is given -- is LF.
"""
import base64
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import sys
import tempfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

RUNTIME_DIR = pathlib.Path(__file__).resolve().parent
EXECUTOR_DIR = RUNTIME_DIR.parent
ROLLBACK_PY = RUNTIME_DIR / "rollback_runtime.py"
DEPLOY_PY = RUNTIME_DIR / "deploy_runtime.py"
COLLECTOR_PY = RUNTIME_DIR / "collector_runtime.py"
LAUNCHER = EXECUTOR_DIR / "go-hk-deployctl"

DOCKER = "/usr/bin/docker"
PROJECT = "go-822-staging"
SOURCE_TASK_ID = "go-boss-deploy-6344dcdd3ccd103d5efdc1b6"
ROLLBACK_TASK_ID = "go-boss-rollback-be119fa22df0a096b2dd5ed1"
RELEASE_ID = "boss-rollback-be119fa22df0a096b2dd5ed1"
DEPLOY_RELEASE_ID = "boss-deploy-6344dcdd3ccd103d5efdc1b6"
BASE_TAG = "go-hotel:aoluguya-direct-r3-1-20260906"
CONTRACT_SHA = "d0a4d82a1e56e7ff96ddedc1668534f57961aab6875ca9c0f7997d37e72b56fb"


def image(prefix):
    return "sha256:" + (prefix + "0" * 64)[:64]


CANDIDATE = image("6b92050ed42c115d")   # what the source deployment put on the host
TARGET = image("1c9598d699c21620")      # what its record says to put back
REDIS = image("ff02b58f971e7d7d")
CADDY = image("af32e97399febea8")

SERVICE_LINE = re.compile(r"^  ([A-Za-z0-9][A-Za-z0-9._-]*):$")
IMAGE_LINE = re.compile(r"^    image: (sha256:[0-9a-f]{64})$")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def committed_bytes(path):
    """The bytes a commit would carry: LF, whichever line ending the tree has."""
    return pathlib.Path(path).read_bytes().replace(b"\r\n", b"\n")


class Result:
    def __init__(self, argv, returncode=0, stdout="", stderr=""):
        self.argv, self.returncode, self.stdout, self.stderr = tuple(argv), returncode, stdout, stderr


def parse_override(raw):
    """The exact shape `_override` writes, and nothing else."""
    lines = raw.decode("utf-8").splitlines()
    if not lines or lines[0] != "services:":
        raise ValueError("not a compose override")
    if len(lines) != 1 + 2 * 8:
        raise ValueError("expected one line per service plus its image, got %d" % len(lines))
    pinned, service = {}, None
    for line in lines[1:]:
        m = SERVICE_LINE.match(line)
        if m:
            service = m.group(1)
            continue
        m = IMAGE_LINE.match(line)
        if not m or service is None:
            raise ValueError("unexpected line %r" % line)
        pinned[service] = m.group(1)
        service = None
    return pinned


class Host:
    """A command-level model of the host's docker argv.  Never runs anything."""

    def __init__(self, fail_compose=False, api_health_after="healthy"):
        self.calls = []
        self.overrides = []
        self.compose_calls = 0
        self.fail_compose = fail_compose
        self.api_health = "starting"
        self.api_health_after = api_health_after
        self.live = {s: CANDIDATE for s in R.SERVICES}
        self.protected = {"redis": REDIS, "caddy": CADDY}
        self.cid, self.by_cid = {}, {}
        for s in R.SERVICES:
            self.cid[s] = "old-" + s
            self.by_cid["old-" + s] = s
        for s in self.protected:
            self.cid[s] = "p-" + s
            self.by_cid["p-" + s] = s
        self.present = {CANDIDATE, TARGET, REDIS, CADDY}
        self.image_report = {}

    def _doc(self, service):
        state = {"Running": True, "Status": "running", "Restarting": False,
                 "OOMKilled": False, "StartedAt": "2026-09-17T08:00:00Z"}
        if service == R.SERVICES[0]:
            state["Health"] = {"Status": self.api_health}
        image_id = self.live.get(service, self.protected.get(service))
        return {"Id": self.cid[service], "Image": image_id, "State": state, "RestartCount": 0}

    def _compose(self, argv):
        self.compose_calls += 1
        flags = list(argv[2:])
        files = [flags[i + 1] for i, tok in enumerate(flags) if tok == "-f" and i + 1 < len(flags)]
        if len(files) < 2:
            # The original failure, reproduced exactly: the base file names a tag the
            # host does not hold, so Compose tries to pull it and exits non-zero.
            return Result(argv, 1, "", "pull access denied for %s, repository does not exist "
                                       "or may require authorization" % BASE_TAG.split(":")[0])
        override_path = files[-1]
        if not pathlib.Path(override_path).is_file():
            return Result(argv, 1, "", "override file missing at compose time")
        raw = pathlib.Path(override_path).read_bytes()
        try:
            pinned = parse_override(raw)
        except ValueError as exc:
            return Result(argv, 1, "", "unparseable override: %s" % exc)
        self.overrides.append({"argv": tuple(argv), "pinned": pinned, "raw": raw,
                               "mode": os.stat(override_path).st_mode & 0o777})
        if self.fail_compose:
            return Result(argv, 1, "", "simulated compose failure")
        for service, image_id in pinned.items():
            self.live[service] = image_id
            self.cid[service] = "new-" + service
            self.by_cid["new-" + service] = service
        self.api_health = self.api_health_after
        return Result(argv, 0, "")

    def run(self, argv):
        argv = tuple(argv)
        self.calls.append(argv)
        if argv[:2] == (DOCKER, "ps"):
            service = project = None
            for token in argv:
                for label, prefix in (("service", "label=com.docker.compose.service="),
                                      ("project", "label=com.docker.compose.project=")):
                    if token.startswith(prefix):
                        value = token[len(prefix):]
                        if label == "service":
                            service = value
                        else:
                            project = value
            if project != PROJECT or service not in self.cid:
                return Result(argv, 1, "", "unmodelled ps filter")
            return Result(argv, 0, self.cid[service] + "\n")
        if argv[:2] == (DOCKER, "inspect") and len(argv) == 3:
            service = self.by_cid.get(argv[2])
            if service is None:
                return Result(argv, 1, "", "no such object")
            return Result(argv, 0, json.dumps([self._doc(service)]))
        if argv[:3] == (DOCKER, "image", "inspect"):
            wanted = argv[3]
            if wanted not in self.present:
                return Result(argv, 1, "", "No such image")
            return Result(argv, 0, self.image_report.get(wanted, wanted) + " ")
        if argv[:2] == (DOCKER, "compose"):
            return self._compose(argv)
        return Result(argv, 1, "", "unmodelled argv: %r" % (argv,))


def sign(obj, key, hexadecimal):
    body = {k: v for k, v in obj.items() if k != "signature"}
    raw = key.sign(R.canonical(body))
    out = dict(obj)
    out["signature"] = raw.hex() if hexadecimal else base64.b64encode(raw).decode("ascii")
    return out


def build_fixture(root, *, contract_bound=False, migration_required=False):
    root = pathlib.Path(root)
    dirs = {name: root / name for name in ("handoff", "deploy", "rollback", "run")}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    compose = root / "compose.yml"
    env = root / "runtime.env"
    compose.write_text("services:\n  api:\n    image: %s\n" % BASE_TAG)
    env.write_text("R31_IMAGE_TAG=%s\n" % BASE_TAG.split(":", 1)[1])
    task_key, evidence_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    task_pub, evidence_pub = root / "task.pub", root / "evidence.pub"
    for key, path in ((task_key, task_pub), (evidence_key, evidence_pub)):
        path.write_bytes(key.public_key().public_bytes(serialization.Encoding.OpenSSH,
                                                       serialization.PublicFormat.OpenSSH))
    parameters = {"release_id": DEPLOY_RELEASE_ID}
    if contract_bound:
        parameters["candidate_contract_sha256"] = CONTRACT_SHA
    task = {"schema_version": "1", "task_id": SOURCE_TASK_ID, "nonce": "nonce-deploy-0001",
            "authority": "GO-COMMAND-CENTER", "action_id": "HK_STAGING_DEPLOY",
            "environment": "HK-STAGING-01", "issued_at": "2026-09-17T06:00:00Z",
            "parameters": parameters}
    task = sign(task, task_key, True)
    record_id = hashlib.sha256(b"deploy-record-2efcbabf").hexdigest()
    record = {
        "deploy_record_schema_version": "2", "record_id": record_id,
        "task_id": task["task_id"], "nonce": task["nonce"], "authority": task["authority"],
        "task_canonical_sha256": hashlib.sha256(R.canonical(task)).hexdigest(),
        "action_id": "HK_STAGING_DEPLOY", "environment": "HK-STAGING-01",
        "release_id": DEPLOY_RELEASE_ID, "candidate_image_id": CANDIDATE,
        "target_count": 8,
        "compose_sha256": hashlib.sha256(compose.read_bytes()).hexdigest(),
        "env_sha256": hashlib.sha256(env.read_bytes()).hexdigest(),
        "targets": [{"service": s, "image_id": TARGET} for s in R.SERVICES],
        "protected_non_target_inventory": [{"service": "redis", "image_id": REDIS},
                                           {"service": "caddy", "image_id": CADDY}],
    }
    protected = record["protected_non_target_inventory"]
    record["protected_non_target_inventory_sha256"] = hashlib.sha256(
        json.dumps(protected, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if contract_bound:
        record.update(candidate_contract_sha256=CONTRACT_SHA,
                      baseline_revision="0133_flight_change_plan",
                      target_revision="0133_flight_change_plan",
                      migration_required=bool(migration_required))
    raw = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    (dirs["deploy"] / (record_id + ".json")).write_bytes(raw)
    record_sha = hashlib.sha256(raw).hexdigest()
    evidence = {"schema_version": "1", "task_id": task["task_id"], "nonce": task["nonce"],
                "action_id": "HK_STAGING_DEPLOY", "environment": "HK-STAGING-01",
                "status": "SUCCESS", "executor_result": "DEPLOY_OK",
                "release_id": DEPLOY_RELEASE_ID, "deploy_record_schema_version": "2",
                "deploy_record_id": record_id, "deploy_record_sha256": record_sha}
    if contract_bound:
        evidence["candidate_contract_sha256"] = CONTRACT_SHA
    evidence = sign(evidence, evidence_key, False)
    (dirs["handoff"] / (ROLLBACK_TASK_ID + ".json")).write_text(json.dumps({
        "schema_version": "1", "rollback_task_id": ROLLBACK_TASK_ID,
        "source_task": task, "source_evidence": evidence,
        "source_deploy_task_id": SOURCE_TASK_ID, "deploy_record_id": record_id,
        "deploy_record_sha256": record_sha,
        "history": [{"task": task, "evidence": evidence}]}, sort_keys=True))
    return {"root": root, "compose": compose, "env": env, "task_key": task_pub,
            "evidence_key": evidence_pub, "record": record, "record_id": record_id,
            "record_sha": record_sha, "task": task, "evidence": evidence, "dirs": dirs}


def invoke(fx, host):
    R.COMPOSE = str(fx["compose"])
    R.ENV_FILE = str(fx["env"])
    R.TEMP_DIR = str(fx["dirs"]["run"])
    binding = {"task_id": ROLLBACK_TASK_ID, "nonce": "nonce-rollback-0001",
               "authority": "GO-COMMAND-CENTER", "canonical_sha256": "f" * 64}
    try:
        result = R.run_rollback(RELEASE_ID, SOURCE_TASK_ID, binding, host, COL,
                                handoff_dir=str(fx["dirs"]["handoff"]),
                                deploy_dir=str(fx["dirs"]["deploy"]),
                                rollback_dir=str(fx["dirs"]["rollback"]),
                                task_key=str(fx["task_key"]),
                                evidence_key=str(fx["evidence_key"]),
                                sleeper=lambda _seconds: None)
        return result, None
    except ValueError as exc:
        return None, str(exc)


def records_in(fx):
    return sorted(p.name for p in pathlib.Path(fx["dirs"]["rollback"]).glob("*.json"))


def run():
    checks = {}

    def check(name, condition, detail=""):
        checks[name] = bool(condition)
        print("%s  %s%s" % ("PASS" if condition else "FAIL", name,
                            "" if condition else "  %s" % detail))

    with tempfile.TemporaryDirectory(prefix="go-hk-rollback-") as raw:
        fx = build_fixture(raw)
        host = Host()
        result, error = invoke(fx, host)

        # 1. the corrected scope: base file plus an override, and nothing else
        check("ROLLBACK_SUCCEEDS_AGAINST_THE_RECORDED_SOURCE", result is not None, error or "")
        expected_argv = (DOCKER, "compose", "--env-file", str(fx["env"]), "-p", PROJECT,
                         "-f", str(fx["compose"]), "-f", None, "up", "-d", "--no-deps",
                         "--force-recreate", *R.SERVICES)
        compose = [c for c in host.calls if c[:2] == (DOCKER, "compose")]
        check("EXACTLY_ONE_COMPOSE_INVOCATION", len(compose) == 1, "saw %d" % len(compose))
        argv = compose[0] if compose else ()
        check("COMPOSE_ARGV_CARRIES_BASE_AND_OVERRIDE",
              len(argv) == len(expected_argv) and argv[:9] == expected_argv[:9]
              and argv[9].endswith(".yaml"),
              "argv=%r" % (argv,))
        check("COMPOSE_ARGV_TAIL_IS_THE_FIXED_EIGHT_SERVICES",
              argv[10:] == expected_argv[10:], "tail=%r" % (argv[10:],))

        # 2. the override is what makes it resolvable, and it says exactly one thing
        pins = host.overrides[0]["pinned"] if host.overrides else {}
        check("OVERRIDE_PINS_EXACTLY_THE_EIGHT_RECORDED_TARGET_IMAGES",
              pins == {s: TARGET for s in R.SERVICES},
              "pinned=%r" % (sorted(set(pins.values())),))
        check("OVERRIDE_IS_READ_BY_COMPOSE_EXACTLY_ONCE", len(host.overrides) == 1,
              "seen %d" % len(host.overrides))
        if os.name == "posix":
            check("OVERRIDE_IS_MODE_0600", host.overrides[0]["mode"] == 0o600,
                  "mode=%o" % host.overrides[0]["mode"])
        else:
            check("OVERRIDE_MODE_IS_CHECKED_ON_POSIX_ONLY", True, "skipped on this platform")

        # 3. no leftover, and no pull/migration path anywhere in the argv set
        check("OVERRIDE_IS_REMOVED_AFTER_SUCCESS",
              list(pathlib.Path(fx["dirs"]["run"]).iterdir()) == [],
              "leftover=%r" % (list(pathlib.Path(fx["dirs"]["run"]).iterdir()),))
        watch = ("pull", "alembic", "exec", "restart", "rm", "down")
        offending = [c for c in host.calls for token in c if token in watch]
        check("NO_PULL_MIGRATION_OR_WIDER_DOCKER_PATH_IS_EVER_INVOKED", not offending,
              "offending=%r" % (offending,))
        protected_reads = [c for c in host.calls
                           if any(a.endswith("service=%s" % s) for a in c for s in R.PROTECTED)]
        check("THE_PROTECTED_TWO_ARE_STILL_READ_FOR_THE_DRIFT_CHECK", len(protected_reads) > 0,
              "saw %d" % len(protected_reads))
        mutating = ("up", "down", "rm", "restart", "stop", "kill", "exec")
        names_protected = [c for c in host.calls
                           if any(t in mutating for t in c)
                           and any(a.endswith("service=%s" % s) for a in c for s in R.PROTECTED)]
        check("NO_MUTATING_DOCKER_ARGV_NAMES_A_PROTECTED_SERVICE", not names_protected,
              "saw %r" % (names_protected,))

    # 4. a candidate contract may be same-revision; only a real migration blocks rollback
    with tempfile.TemporaryDirectory(prefix="go-hk-rollback-contract-") as raw:
        fx = build_fixture(raw, contract_bound=True, migration_required=False)
        host = Host()
        result, error = invoke(fx, host)
        check("SAME_REVISION_CONTRACT_SOURCE_ROLLS_BACK", result is not None, error or "")
        check("SAME_REVISION_CONTRACT_IS_FUTURE_ROLLBACK_ELIGIBLE",
              DEP.rollback_source_eligible(fx["record"], fx["record_sha"], fx["task"], fx["evidence"]),
              "same-revision contract was classified as non-rollbackable")

    with tempfile.TemporaryDirectory(prefix="go-hk-rollback-migration-") as raw:
        fx = build_fixture(raw, contract_bound=True, migration_required=True)
        host = Host()
        result, error = invoke(fx, host)
        check("MIGRATED_CONTRACT_SOURCE_REMAINS_BLOCKED",
              result is None and error == "migration rollback compatibility unproven",
              "error=%r" % (error,))
        check("MIGRATED_CONTRACT_IS_NOT_FUTURE_ROLLBACK_ELIGIBLE",
              not DEP.rollback_source_eligible(fx["record"], fx["record_sha"], fx["task"], fx["evidence"]),
              "migrated contract was classified as rollbackable")

    # 5. the pre-mutation record, and the failure path
    with tempfile.TemporaryDirectory(prefix="go-hk-rollback-") as raw:
        fx = build_fixture(raw)
        host = Host(fail_compose=True)
        result, error = invoke(fx, host)
        check("A_FAILED_COMPOSE_IS_REPORTED_AS_THE_COMPOSE_STEP", result is None and error == "docker rollback",
              "error=%r" % (error,))
        check("PRE_MUTATION_RECORD_SURVIVES_A_FAILED_COMPOSE", len(records_in(fx)) == 1,
              "records=%r" % (records_in(fx),))
        check("OVERRIDE_IS_REMOVED_AFTER_A_FAILED_COMPOSE",
              list(pathlib.Path(fx["dirs"]["run"]).iterdir()) == [],
              "leftover=%r" % (list(pathlib.Path(fx["dirs"]["run"]).iterdir()),))

    # 5. an unhealthy api is not a restored host
    with tempfile.TemporaryDirectory(prefix="go-hk-rollback-") as raw:
        fx = build_fixture(raw)
        host = Host(api_health_after="starting")
        result, error = invoke(fx, host)
        check("AN_API_THAT_NEVER_BECOMES_HEALTHY_IS_REFUSED", result is None and error == "rollback readiness",
              "error=%r" % (error,))
        check("THE_HEALTH_GATE_RUNS_AFTER_COMPOSE_HAS_BEEN_CALLED",
              host.compose_calls == 1, "compose_calls=%d" % host.compose_calls)

    # 6. a host that is already at the candidate is the only shape that is accepted,
    #    and none of that was relaxed to make the override work
    with tempfile.TemporaryDirectory(prefix="go-hk-rollback-") as raw:
        fx = build_fixture(raw)
        seeded = pathlib.Path(fx["dirs"]["rollback"]) / "seeded.json"
        seeded.write_text(json.dumps({"source_deploy_task_id": SOURCE_TASK_ID}))
        host = Host()
        result, error = invoke(fx, host)
        check("A_SOURCE_CONSUMED_BY_A_PRIOR_ATTEMPT_IS_STILL_REFUSED",
              result is None and error == "source consumed", "error=%r" % (error,))
        check("A_CONSUMED_SOURCE_NEVER_REACHES_COMPOSE", host.compose_calls == 0,
              "compose_calls=%d" % host.compose_calls)

    with tempfile.TemporaryDirectory(prefix="go-hk-rollback-") as raw:
        fx = build_fixture(raw)
        record_path = pathlib.Path(fx["dirs"]["deploy"]) / (fx["record_id"] + ".json")
        record_path.write_bytes(record_path.read_bytes().replace(b'"target_count":8', b'"target_count":9'))
        host = Host()
        result, error = invoke(fx, host)
        check("A_TAMPERED_SOURCE_RECORD_IS_STILL_REFUSED", result is None and error == "record integrity",
              "error=%r" % (error,))

    with tempfile.TemporaryDirectory(prefix="go-hk-rollback-") as raw:
        fx = build_fixture(raw)
        host = Host()
        host.present.discard(TARGET)
        result, error = invoke(fx, host)
        check("A_TARGET_IMAGE_THE_HOST_DOES_NOT_HOLD_IS_STILL_REFUSED",
              result is None and error is not None, "error=%r" % (error,))
        check("A_MISSING_TARGET_IMAGE_NEVER_REACHES_COMPOSE", host.compose_calls == 0,
              "compose_calls=%d" % host.compose_calls)
        check("A_MISSING_TARGET_IMAGE_WRITES_NO_ROLLBACK_RECORD", records_in(fx) == [],
              "records=%r" % (records_in(fx),))

    with tempfile.TemporaryDirectory(prefix="go-hk-rollback-") as raw:
        fx = build_fixture(raw)
        host = Host()
        host.image_report[TARGET] = image("deadbeefdeadbeef")
        result, error = invoke(fx, host)
        check("A_TARGET_IMAGE_THAT_IS_NOT_THE_RECORDED_ID_IS_STILL_REFUSED",
              result is None and error == "immutable image missing", "error=%r" % (error,))
        check("A_MISREPORTED_TARGET_IMAGE_NEVER_REACHES_COMPOSE", host.compose_calls == 0,
              "compose_calls=%d" % host.compose_calls)

    # 7. the model itself still reproduces the original failure, so check 1 means something
    host = Host()
    base_only = (DOCKER, "compose", "--env-file", "/tmp/x", "-p", PROJECT,
                 "-f", "/tmp/base.yml", "up", "-d", "--no-deps", "--force-recreate",
                 *R.SERVICES)
    outcome = host.run(base_only)
    check("A_BASE_ONLY_COMPOSE_STILL_FAILS_THE_WAY_IT_DID",
          outcome.returncode != 0 and "pull access denied" in outcome.stderr,
          "rc=%r" % (outcome.returncode,))

    # 8. the launcher's pins, compared against committed bytes
    launcher = committed_bytes(LAUNCHER).decode("utf-8")
    for name, path in (("ROLLBACK", ROLLBACK_PY), ("COLLECTOR", COLLECTOR_PY),
                       ("CANARY", RUNTIME_DIR / "canary_runtime.py"),
                       ("DEPLOY", RUNTIME_DIR / "deploy_runtime.py"),
                       ("ARTIFACT", RUNTIME_DIR / "artifact_runtime.py")):
        pin = re.search(r'(?m)^_%s_SHA256 = "([0-9a-f]{64})"$' % name, launcher)
        digest = hashlib.sha256(committed_bytes(path)).hexdigest()
        check("LAUNCHER_STILL_PINS_%s_BY_EXACT_BYTES" % name,
              pin is not None and pin.group(1) == digest,
              "pin=%s bytes=%s" % (pin.group(1)[:16] if pin else None, digest[:16]))
    check("LAUNCHER_STILL_ENFORCES_THE_ROLLBACK_INTEGRITY_CHECK",
          "rollback integrity" in launcher and "_load_rollback" in launcher)

    failed = sorted(k for k, v in checks.items() if not v)
    print("\n%d checks, %d failed" % (len(checks), len(failed)))
    print(json.dumps({"checks": len(checks), "failed": failed,
                      "status": "PASS" if not failed else "FAIL"}, sort_keys=True))
    return 1 if failed else 0


R = load("rollback_runtime_under_test", ROLLBACK_PY)
DEP = load("deploy_runtime_under_test", DEPLOY_PY)
COL = load("collector_runtime_under_test", COLLECTOR_PY)


if __name__ == "__main__":
    sys.exit(run())
