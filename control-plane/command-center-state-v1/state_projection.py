#!/usr/bin/env python3
"""GO Command Center control-state projection — CONTROL_STATE_V1.

Read-only, offline, deterministic projection of the GitHub-native Control Plane.

It answers one question: *given only the control bus, what is the current control
state?*  It never invents an answer.  Every leaf is an assertion carrying a
state from {PROVEN, OBSERVED, PENDING, HOLD, FAILED, UNKNOWN} plus the evidence
references that produced it.  Absence of evidence is reported as UNKNOWN, never
as success.

Inputs are local directory checkouts.  Nothing here reaches the network, the
Hong Kong runtime, Production, a signing key, or any live Control Plane state.

Authority: the output of this tool is a DERIVED, NON-AUTHORITATIVE view.  The
Signed Task and the Signed Evidence remain the only Execution Authority and the
only proof.  This file is never hand-edited and is always rebuildable.
"""
import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys

SCHEMA_VERSION = "1"
CONTRACT_STATE = "CURRENT_CONTROL_STATE"
CONTRACT_STATUS = "CONTROL_STATUS_V1"

STATE_PROVEN = "PROVEN"
STATE_OBSERVED = "OBSERVED"
STATE_PENDING = "PENDING"
STATE_HOLD = "HOLD"
STATE_FAILED = "FAILED"
STATE_UNKNOWN = "UNKNOWN"

AUTHORITY = "DERIVED_NON_AUTHORITATIVE"

TASK_REQUIRED = {"schema_version", "task_id", "environment", "action_id", "issued_at",
                 "expires_at", "nonce", "parameters", "authority", "signature"}
EVIDENCE_COMMON = {"schema_version", "task_id", "nonce", "action_id", "environment",
                   "status", "started_at", "signature"}
REQUEST_REQUIRED = {"schema_version", "request_id", "action_id", "environment", "requested_at"}

ACTION_PARAMETERS = {
    "CONTROL_PLANE_HEALTH": set(),
    "HK_STAGING_VERIFY": {"release_id", "candidate_image_id", "expected_current_image_id"},
    "HK_STAGING_CANARY": {"release_id", "candidate_image_id", "candidate_repo_digest",
                          "expected_current_image_id"},
    "HK_STAGING_DEPLOY": {"release_id", "candidate_image_id", "candidate_repo_digest",
                          "expected_current_image_id", "canary_evidence_id", "approval_id"},
    "HK_STAGING_ROLLBACK": {"release_id", "source_deploy_task_id", "approval_id"},
    "HK_STAGING_TEST_PR": {"builder_profile", "source"},
}
ACTION_RESULT = {
    "HK_STAGING_VERIFY": "VERIFY_OK",
    "HK_STAGING_CANARY": "CANARY_OK",
    "HK_STAGING_DEPLOY": "DEPLOY_OK",
    "HK_STAGING_ROLLBACK": "ROLLBACK_OK",
    "HK_STAGING_TEST_PR": "TEST_PR_OK",
    "CONTROL_PLANE_HEALTH": None,
}
REQUEST_EXTRA_FIELDS = {
    "HK_STAGING_VERIFY": set(),
    "HK_STAGING_TEST_PR": {"pr_number"},
    "HK_STAGING_DEPLOY": {"plan_id"},
}

TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
RELEASE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
INSTANCE_RE = re.compile(r"^(?:i[-Zz]?)?([0-9a-z]{16,20})[Zz]?$")


def normalize_instance(value):
    """Map the three observed spellings of one Alibaba instance id to one form.

    `i-j6ccs8t04f1p4d8pe69z` (workbench), `iZj6ccs8t04f1p4d8pe69zZ` (uname
    nodename inside the guest) and the bare `j6ccs8t04f1p4d8pe69z` all denote
    the same machine, so liveness can be bound to the runtime host.
    """
    if not isinstance(value, str):
        return None
    match = INSTANCE_RE.fullmatch(value.strip())
    return "i-" + match.group(1) if match else None

LIFECYCLE_REQUEST = {"REQUEST_CREATED", "REQUEST_VALIDATED", "REQUEST_REJECTED"}
LIFECYCLE_TASK = {"TASK_SIGNED", "TASK_PUBLISHED", "HK_AGENT_PICKED_UP", "EXECUTION_STARTED",
                  "EVIDENCE_PUBLISHED", "EVIDENCE_VERIFIED", "COMPLETE", "TASK_EXPIRED",
                  "TASK_NOT_PICKED_UP", "EXECUTION_FAILED", "EVIDENCE_INVALID",
                  "EVIDENCE_TIMEOUT", "REPLAY_REJECTED", "POLICY_HOLD"}


# --------------------------------------------------------------------------- #
# primitives
# --------------------------------------------------------------------------- #
def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def now_utc():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(value):
    return value.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value):
    if not isinstance(value, str):
        raise ValueError("timestamp_not_string")
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("naive_timestamp")
    return parsed.astimezone(dt.timezone.utc)


def assertion(state, value, reason, evidence=None):
    if state == STATE_UNKNOWN:
        value = None
    return {"state": state, "value": value, "reason": reason,
            "evidence": sorted({e for e in (evidence or []) if e})}


def unknown(reason, evidence=None):
    return assertion(STATE_UNKNOWN, None, reason, evidence)


def read_json(path):
    raw = pathlib.Path(path).read_bytes()
    return json.loads(raw.decode("utf-8"))


# --------------------------------------------------------------------------- #
# signature verification (optional; absent key => OBSERVED, never PROVEN)
# --------------------------------------------------------------------------- #
class Verifier:
    """Ed25519 verifier that reports NOT_PERFORMED rather than assuming success."""

    def __init__(self, key_path=None):
        self.key = None
        self.fingerprint = None
        self.available = False
        if not key_path:
            return
        try:
            from cryptography.hazmat.primitives import serialization
            raw = pathlib.Path(key_path).read_bytes()
            if raw.startswith(b"ssh-"):
                self.key = serialization.load_ssh_public_key(raw)
            else:
                self.key = serialization.load_pem_public_key(raw)
            self.fingerprint = hashlib.sha256(
                self.key.public_bytes(serialization.Encoding.Raw,
                                      serialization.PublicFormat.Raw)).hexdigest()
            self.available = True
        except Exception as exc:  # noqa: BLE001 - fail closed, report why
            self.key = None
            self.available = False
            self.fingerprint = "unavailable:%s" % type(exc).__name__

    def verify(self, obj, encoding):
        """Return True / False / None (None = could not be performed)."""
        if not self.available:
            return None
        signature = obj.get("signature")
        if not isinstance(signature, str):
            return False
        try:
            import base64
            if encoding == "hex":
                if not re.fullmatch(r"[0-9a-f]{128}", signature):
                    return False
                raw = bytes.fromhex(signature)
            else:
                raw = base64.b64decode(signature.encode("ascii"), validate=True)
            if len(raw) != 64:
                return False
            # Internal annotations added during normalisation are never part of
            # the signed canonical form.
            unsigned = {k: v for k, v in obj.items()
                        if k != "signature" and not k.startswith("_")}
            self.key.verify(raw, canonical(unsigned))
            return True
        except Exception:  # noqa: BLE001
            return False


# --------------------------------------------------------------------------- #
# schema validation
# --------------------------------------------------------------------------- #
class Malformed(Exception):
    pass


def validate_task(task):
    """Validate the immutable core strictly; report parameter-contract drift."""
    if not isinstance(task, dict) or set(task) != TASK_REQUIRED:
        raise Malformed("task_fields")
    if task["schema_version"] != "1":
        raise Malformed("task_schema_version")
    if not TASK_ID_RE.fullmatch(task["task_id"] or ""):
        raise Malformed("task_id")
    if not NONCE_RE.fullmatch(task["nonce"] or ""):
        raise Malformed("task_nonce")
    if task["authority"] != "GO-COMMAND-CENTER":
        raise Malformed("task_authority")
    action = task["action_id"]
    if action not in ACTION_PARAMETERS:
        raise Malformed("task_action_unknown")
    if task["environment"] != "HK-STAGING-01":
        raise Malformed("task_environment")
    parse_time(task["issued_at"])
    parse_time(task["expires_at"])
    if not isinstance(task["parameters"], dict):
        raise Malformed("task_parameters")
    # Historical Tasks may predate the current parameter contract. They stay in
    # the projection with an explicit drift marker instead of being dropped, so
    # the state is never silently incomplete.
    current = set(task["parameters"]) == ACTION_PARAMETERS[action]
    task["_parameter_contract"] = "CURRENT" if current else "LEGACY_OR_UNKNOWN"
    if current and action == "HK_STAGING_TEST_PR":
        source = task["parameters"]["source"]
        if (task["parameters"]["builder_profile"] != "go-application-python-v1"
                or not isinstance(source, dict)
                or set(source) != {"repository", "pr_number", "commit_sha"}
                or not COMMIT_RE.fullmatch(source["commit_sha"])):
            raise Malformed("task_test_pr_source")
    if current and action == "HK_STAGING_DEPLOY" \
            and not IMAGE_RE.fullmatch(task["parameters"]["candidate_image_id"]):
        raise Malformed("task_candidate_image")
    return task


def normalize_evidence(evidence):
    """Normalise the two published Evidence generations onto one shape."""
    if not isinstance(evidence, dict):
        raise Malformed("evidence_not_object")
    generation = "v2" if "completed_at" in evidence else ("v1" if "finished_at" in evidence else None)
    if generation is None:
        raise Malformed("evidence_timestamp")
    missing = EVIDENCE_COMMON - set(evidence)
    if missing:
        raise Malformed("evidence_fields")
    if evidence["schema_version"] != "1":
        raise Malformed("evidence_schema_version")
    if evidence["action_id"] not in ACTION_PARAMETERS:
        raise Malformed("evidence_action_unknown")
    parse_time(evidence["started_at"])
    parse_time(evidence[generation == "v2" and "completed_at" or "finished_at"])
    out = dict(evidence)
    out["_generation"] = generation
    out["_completed_at"] = evidence["completed_at"] if generation == "v2" else evidence["finished_at"]
    return out


def validate_request(request):
    if not isinstance(request, dict):
        raise Malformed("request_not_object")
    action = request.get("action_id")
    if action not in REQUEST_EXTRA_FIELDS:
        raise Malformed("request_action_unknown")
    if set(request) != REQUEST_REQUIRED | REQUEST_EXTRA_FIELDS[action]:
        raise Malformed("request_fields")
    if request["schema_version"] != "1":
        raise Malformed("request_schema_version")
    if not isinstance(request["request_id"], str) or not re.fullmatch(
            r"^[A-Za-z0-9][A-Za-z0-9._-]{2,79}$", request["request_id"]):
        raise Malformed("request_id")
    if request["environment"] != "HK-STAGING-01":
        raise Malformed("request_environment")
    parse_time(request["requested_at"])
    if action == "HK_STAGING_TEST_PR" and not re.fullmatch(r"^[1-9][0-9]{0,8}$", request["pr_number"]):
        raise Malformed("request_pr_number")
    if action == "HK_STAGING_DEPLOY" and not RELEASE_RE.fullmatch(request["plan_id"]):
        raise Malformed("request_plan_id")
    return request


# --------------------------------------------------------------------------- #
# loaders
# --------------------------------------------------------------------------- #
class Loaded:
    def __init__(self):
        self.tasks = []            # (path, task)
        self.evidence = []         # (path, evidence)
        self.requests = []         # (ref, head_sha, source, request)
        self.anomalies = []        # {kind, detail, ref}

    def anomaly(self, kind, detail, ref=None):
        self.anomalies.append({"kind": kind, "detail": detail, "ref": ref})


def load_tasks(root, loaded):
    folder = pathlib.Path(root) / "tasks"
    if not folder.is_dir():
        loaded.anomaly("TASKS_DIRECTORY_MISSING", str(folder))
        return
    for path in sorted(folder.glob("*.json")):
        try:
            loaded.tasks.append((path.name, validate_task(read_json(path))))
        except (Malformed, ValueError, OSError, UnicodeError) as exc:
            loaded.anomaly("TASK_UNREADABLE", "%s" % exc, path.name)


def load_evidence(root, loaded):
    folder = pathlib.Path(root) / "evidence"
    if not folder.is_dir():
        loaded.anomaly("EVIDENCE_DIRECTORY_MISSING", str(folder))
        return
    for path in sorted(folder.glob("*.json")):
        try:
            loaded.evidence.append((path.name, normalize_evidence(read_json(path))))
        except (Malformed, ValueError, OSError, UnicodeError) as exc:
            loaded.anomaly("EVIDENCE_UNREADABLE", "%s" % exc, path.name)


def load_requests(root, loaded):
    if not root:
        return
    folder = pathlib.Path(root)
    if not folder.is_dir():
        loaded.anomaly("REQUESTS_DIRECTORY_MISSING", str(folder))
        return
    for path in sorted(folder.glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            payload = read_json(path)
        except (OSError, UnicodeError, ValueError) as exc:
            loaded.anomaly("REQUEST_UNREADABLE", "%s" % exc, path.name)
            continue
        ref, head = None, None
        if isinstance(payload, dict) and "request" in payload:
            ref = payload.get("ref")
            head = payload.get("head_sha")
            payload = payload["request"]
        try:
            loaded.requests.append((ref, head, path.name, validate_request(payload)))
        except (Malformed, ValueError) as exc:
            loaded.anomaly("REQUEST_UNREADABLE", "%s" % exc, path.name)


# --------------------------------------------------------------------------- #
# projection
# --------------------------------------------------------------------------- #
def request_records(loaded):
    out = []
    seen = {}
    for ref, head, source, request in loaded.requests:
        duplicate = request["request_id"] in seen
        if duplicate:
            loaded.anomaly("REQUEST_ID_REUSED", "request_id", request["request_id"])
        seen[request["request_id"]] = True
        lifecycle = "REQUEST_CREATED"
        if not duplicate:
            # Command Center acceptance is not on the control bus; a Request is
            # only proven consumed when its derived Task exists.
            lifecycle = "REQUEST_CREATED"
        out.append({
            "schema_version": "1",
            "request_id": request["request_id"],
            "action_id": request["action_id"],
            "environment": request["environment"],
            "requested_at": request["requested_at"],
            "target": {k: request[k] for k in sorted(set(request) - REQUEST_REQUIRED)},
            "request_sha256": digest(request),
            "source": {"ref": ref, "head_sha": head, "file": source},
            "holding_execution_authority": False,
            "lifecycle": lifecycle,
        })
    return out


def task_records(loaded, task_verifier, at, stale_seconds):
    by_nonce, by_id = {}, {}
    evidence_by_key = {}
    for name, item in loaded.evidence:
        key = (item["task_id"], item["nonce"])
        evidence_by_key.setdefault(key, []).append((name, item))

    for name, task in loaded.tasks:
        by_id.setdefault(task["task_id"], []).append(name)
        by_nonce.setdefault(task["nonce"], []).append(name)
    for task_id, names in sorted(by_id.items()):
        if len(names) > 1:
            loaded.anomaly("TASK_ID_REUSED", "duplicate task_id", task_id)
    for nonce, names in sorted(by_nonce.items()):
        if len(names) > 1:
            loaded.anomaly("REPLAY_REJECTED", "nonce reused across tasks", nonce)

    records = []
    for name, task in sorted(loaded.tasks, key=lambda pair: pair[1]["issued_at"]):
        refs = []
        signature = task_verifier.verify(task, "hex") if task_verifier.available else None
        task_sha = digest({k: v for k, v in task.items() if k != "signature"})
        entry = {
            "task_id": task["task_id"],
            "nonce": task["nonce"],
            "action_id": task["action_id"],
            "environment": task["environment"],
            "authority": task["authority"],
            "issued_at": task["issued_at"],
            "expires_at": task["expires_at"],
            "parameters": task["parameters"],
            "task_sha256": task_sha,
            "source_file": name,
            "signature_verified": signature,
            "parameter_contract": task.get("_parameter_contract", "CURRENT"),
        }
        expires = parse_time(task["expires_at"])
        candidates = evidence_by_key.get((task["task_id"], task["nonce"]), [])
        if len(candidates) > 1:
            digests = {digest({k: v for k, v in item.items() if not k.startswith("_")}) for _, item in candidates}
            if len(digests) > 1:
                loaded.anomaly("EVIDENCE_CONFLICT", "multiple distinct evidence for one signed task",
                               task["task_id"])
            entry["evidence_count"] = len(candidates)
        if signature is False:
            entry.update({"lifecycle": "POLICY_HOLD",
                          "assertion": assertion(STATE_FAILED, "TASK_SIGNATURE_INVALID",
                                                 "task signature does not verify against the pinned "
                                                 "Command Center key", refs)})
            records.append(entry)
            continue
        if entry["parameter_contract"] != "CURRENT":
            loaded.anomaly("TASK_PARAMETER_CONTRACT_DRIFT",
                           "observed parameters %s are not the current %s contract"
                           % (sorted(task["parameters"]), task["action_id"]), task["task_id"])
            entry.update({"lifecycle": "POLICY_HOLD",
                          "assertion": unknown(
                              "this Task predates the current Control Plane parameter contract; it "
                              "is preserved for lineage but cannot be evaluated or counted as proof",
                              refs)})
            records.append(entry)
            continue
        if not candidates:
            if at >= expires:
                entry.update({
                    "lifecycle": "TASK_EXPIRED",
                    "assertion": assertion(STATE_OBSERVED, "TASK_EXPIRED",
                                           "expires_at passed with no signed Evidence for this task",
                                           refs),
                    "hk_agent_picked_up": unknown(
                        "the agent ledger is not on the control bus; absence of Evidence cannot "
                        "distinguish TASK_NOT_PICKED_UP from an unpublished failure", refs),
                })
            else:
                entry.update({
                    "lifecycle": "TASK_PUBLISHED",
                    "assertion": assertion(STATE_OBSERVED, "TASK_PUBLISHED",
                                           "signed task published and still inside its validity window",
                                           refs),
                    "hk_agent_picked_up": unknown("no Evidence published yet", refs),
                })
            records.append(entry)
            continue

        ev_name, ev = sorted(candidates, key=lambda pair: pair[1]["_completed_at"])[0]
        refs = sorted({name, ev_name})
        ev_signature = task_verifier.verify(ev, "base64") if task_verifier.available else None
        completed = parse_time(ev["_completed_at"])
        started = parse_time(ev["started_at"])
        # The health payload sits at executor_result in the current agent and at
        # result in the legacy generation; both are read-only observations.
        payload = ev.get("executor_result")
        if not isinstance(payload, dict):
            payload = ev.get("result") if isinstance(ev.get("result"), dict) else None
        entry["evidence"] = {
            "source_file": ev_name,
            "completed_at": ev["_completed_at"],
            "generation": ev["_generation"],
            "status": ev["status"],
            "executor_result": ev.get("executor_result") if isinstance(ev.get("executor_result"), str)
            else (ev.get("result") if isinstance(ev.get("result"), str) else None),
            "signature_verified": ev_signature,
            "evidence_sha256": digest({k: v for k, v in ev.items() if not k.startswith("_")}),
        }
        if payload:
            entry["liveness_payload"] = {
                "hostname": payload.get("hostname"),
                "agent_version": payload.get("agent_version"),
                "tasks_repo_connectivity": payload.get("tasks_repo_connectivity"),
                "evidence_repo_connectivity": payload.get("evidence_repo_connectivity"),
            }
        if isinstance(ev.get("built_image_id"), str):
            entry["evidence"]["built_image_id"] = ev["built_image_id"]
        if isinstance(ev.get("agent_version"), str):
            entry["evidence"]["agent_version"] = ev["agent_version"]
        entry["execution_started"] = assertion(STATE_PROVEN if ev_signature else STATE_OBSERVED,
                                               ev["started_at"],
                                               "Evidence carries started_at for this task/nonce", refs)
        if ev_signature is False:
            entry.update({"lifecycle": "EVIDENCE_INVALID",
                          "assertion": assertion(STATE_FAILED, "EVIDENCE_SIGNATURE_INVALID",
                                                 "Evidence signature does not verify against the "
                                                 "pinned Hong Kong key", refs)})
        elif completed > expires:
            entry.update({"lifecycle": "EVIDENCE_TIMEOUT",
                          "assertion": assertion(STATE_FAILED, "EVIDENCE_AFTER_EXPIRY",
                                                 "Evidence completed_at is outside the task validity "
                                                 "window", refs)})
        elif started > completed:
            entry.update({"lifecycle": "EVIDENCE_INVALID",
                          "assertion": assertion(STATE_FAILED, "EVIDENCE_TIME_ORDER",
                                                 "started_at is after completed_at", refs)})
        elif ev["status"] != "SUCCESS":
            entry.update({"lifecycle": "EXECUTION_FAILED",
                          "assertion": assertion(STATE_FAILED, ev["status"],
                                                 "signed Evidence reports a non-success status", refs)})
        else:
            expected = ACTION_RESULT.get(task["action_id"])
            result = ev.get("executor_result")
            mismatch = bool(expected) and result != expected
            if ev_signature is None:
                entry.update({
                    "lifecycle": "EVIDENCE_PUBLISHED",
                    "assertion": assertion(
                        STATE_OBSERVED, "EXECUTOR_RESULT_MISMATCH" if mismatch else "EVIDENCE_PUBLISHED",
                        "Evidence is published and reports %r, but no verifier public key was "
                        "supplied, so OBSERVED is the strongest honest claim" % (result or "no result"),
                        refs)})
            elif mismatch:
                entry.update({"lifecycle": "EXECUTION_FAILED",
                              "assertion": assertion(STATE_FAILED, "EXECUTOR_RESULT_MISMATCH",
                                                     "executor_result %r does not equal the frozen "
                                                     "terminal result %r" % (result, expected), refs)})
            else:
                entry.update({"lifecycle": "COMPLETE",
                              "assertion": assertion(STATE_PROVEN, expected or "HEALTH_OK",
                                                     "signed Evidence verified against the pinned "
                                                     "Hong Kong key and reports the frozen terminal "
                                                     "result", refs)})
        if at - completed > dt.timedelta(seconds=stale_seconds):
            entry["staleness"] = assertion(STATE_OBSERVED, "STALE",
                                           "newest Evidence for this task is older than the "
                                           "configured freshness window", refs)
        records.append(entry)
    return records


def lifecycle_counts(tasks):
    counts = {}
    for task in tasks:
        counts[task["lifecycle"]] = counts.get(task["lifecycle"], 0) + 1
    return counts


def newest_for(tasks, action, predicate=None):
    matches = [t for t in tasks if t["action_id"] == action and (predicate is None or predicate(t))]
    if not matches:
        return None
    return max(matches, key=lambda t: t.get("evidence", {}).get("completed_at", t["issued_at"]))


def canonical_pointers(go_repo):
    out = {"runtime": None, "candidate": None, "hold": {}, "read_errors": []}
    if not go_repo:
        return out
    base = pathlib.Path(go_repo) / "docs" / "canonical-baseline"
    for key, name in (("runtime", "CURRENT_HK_RUNTIME.json"), ("candidate", "CURRENT_CANDIDATE.json")):
        path = base / name
        try:
            out[key] = read_json(path)
        except (OSError, ValueError) as exc:
            out["read_errors"].append("%s:%s" % (name, exc))
    runtime = out["runtime"] or {}
    candidate = out["candidate"] or {}
    release = runtime.get("release_acceptance") or {}
    out["hold"] = {
        "hk_deploy": "HOLD",
        "final_release": release.get("gate", candidate.get("final_release", "UNKNOWN")),
        "production": release.get("production", candidate.get("production", "UNKNOWN")),
        "runtime_status": runtime.get("status"),
    }
    return out


def build_state(loaded, task_verifier, at, stale_seconds, go_repo, liveness_window, source_refs):
    tasks = task_records(loaded, task_verifier, at, stale_seconds)
    requests = request_records(loaded)
    pointers = canonical_pointers(go_repo)

    def has_success(task):
        return (task.get("evidence") or {}).get("status") == "SUCCESS"

    # `completed`  = signature-verified success (PROVEN territory)
    # `observed`   = published success whose signature could not be checked here
    completed = [t for t in tasks if t["lifecycle"] == "COMPLETE"]
    observed = [t for t in tasks if t["lifecycle"] == "EVIDENCE_PUBLISHED" and has_success(t)]
    successes = completed + observed
    verified = bool(completed) and not observed
    deploys = [t for t in successes if t["action_id"] == "HK_STAGING_DEPLOY"
               and t["assertion"]["state"] != STATE_FAILED]
    health = [t for t in successes if t["action_id"] == "CONTROL_PLANE_HEALTH"]
    newest_health = max(health, key=lambda t: t["evidence"]["completed_at"], default=None)
    newest_evidence = max(successes, key=lambda t: t["evidence"]["completed_at"], default=None) \
        or max((t for t in tasks if t.get("evidence")),
               key=lambda t: t["evidence"]["completed_at"], default=None)

    def last_task(action=None):
        pool = [t for t in tasks if action is None or t["action_id"] == action]
        if not pool:
            return unknown("no signed task of this class exists on the control bus yet")
        pick = max(pool, key=lambda t: t["evidence"]["completed_at"]
                   if t.get("evidence") else t["issued_at"])
        return assertion(STATE_OBSERVED if pick["signature_verified"] is None else (
            STATE_PROVEN if pick["signature_verified"] else STATE_FAILED),
            {"task_id": pick["task_id"], "action_id": pick["action_id"],
             "lifecycle": pick["lifecycle"], "issued_at": pick["issued_at"],
             "expires_at": pick["expires_at"]},
            "newest signed task of this class observed on the control bus",
            [pick["source_file"]] + ([pick["evidence"]["source_file"]] if pick.get("evidence") else []))

    liveness = unknown("no CONTROL_PLANE_HEALTH Evidence exists on the control bus")
    if newest_health:
        age = (at - parse_time(newest_health["evidence"]["completed_at"])).total_seconds()
        payload = newest_health.get("liveness_payload") or {}
        probe = newest_health["evidence"]["source_file"]
        if age > liveness_window:
            liveness = assertion(STATE_UNKNOWN, None,
                                 "newest signed liveness Evidence is %d s old, outside the %d s "
                                 "window: a past success is not proof of current liveness"
                                 % (int(age), liveness_window), [probe])
            liveness["age_seconds"] = int(age)
            liveness["last_seen"] = {"hostname": payload.get("hostname"),
                                     "agent_version": payload.get("agent_version"),
                                     "completed_at": newest_health["evidence"]["completed_at"]}
        elif newest_health["lifecycle"] == "COMPLETE":
            liveness = assertion(STATE_PROVEN,
                                 {"hostname": payload.get("hostname"),
                                  "agent_version": payload.get("agent_version"),
                                  "age_seconds": int(age)},
                                 "signature-verified liveness Evidence inside the freshness window",
                                 [probe])
        else:
            liveness = assertion(STATE_OBSERVED,
                                 {"hostname": payload.get("hostname"),
                                  "agent_version": payload.get("agent_version"),
                                  "age_seconds": int(age)},
                                 "fresh liveness Evidence inside the window, but its signature was "
                                 "not checked here, so OBSERVED is the strongest honest claim",
                                 [probe])

    runtime = pointers["runtime"] or {}
    image = (runtime.get("image") or {})
    pointer_image = image.get("image_config_id")
    newest_verify = newest_for(successes, "HK_STAGING_VERIFY")
    evidence_image = None
    if newest_verify:
        evidence_image = newest_verify["parameters"].get("expected_current_image_id")
    verify_proven = bool(newest_verify) and newest_verify["lifecycle"] == "COMPLETE"
    verify_rank = "verified" if verify_proven else "observed"
    if pointer_image and evidence_image:
        if pointer_image == evidence_image:
            runtime_assertion = assertion(STATE_OBSERVED if not verify_proven else STATE_PROVEN,
                                          pointer_image,
                                          "canonical pointer and the newest %s VERIFY Evidence agree"
                                          % verify_rank,
                                          [newest_verify["evidence"]["source_file"]])
            drift = assertion(STATE_OBSERVED, "NONE",
                              "derived runtime image equals the canonical pointer image")
        else:
            runtime_assertion = assertion(STATE_OBSERVED, pointer_image,
                                          "canonical pointer is authoritative for the runtime "
                                          "currently deployed on HK-STAGING",
                                          [newest_verify["evidence"]["source_file"]])
            drift = assertion(STATE_OBSERVED, "DRIFT",
                              "the newest %s VERIFY Evidence refers to %s while the canonical "
                              "pointer records %s: no VERIFY Evidence of any rank exists for the "
                              "runtime now recorded as deployed" % (verify_rank, evidence_image,
                                                                    pointer_image),
                              [newest_verify["evidence"]["source_file"]])
    elif pointer_image:
        runtime_assertion = assertion(STATE_OBSERVED, pointer_image,
                                      "canonical pointer only; no VERIFY Evidence with a runtime "
                                      "image was observed on the control bus")
        drift = unknown("cannot compare: no VERIFY Evidence carrying a runtime image")
    else:
        runtime_assertion = unknown("no canonical runtime pointer supplied")
        drift = unknown("no canonical runtime pointer supplied")

    healthy = unknown("no Evidence of any kind exists on the control bus")
    if newest_verify:
        age = (at - parse_time(newest_verify["evidence"]["completed_at"])).total_seconds()
        if newest_verify["assertion"]["state"] == STATE_FAILED:
            healthy = assertion(STATE_FAILED, newest_verify["lifecycle"],
                                "the newest VERIFY task did not reach a successful terminal state",
                                [newest_verify["source_file"]])
        else:
            state = STATE_PROVEN if verify_proven else STATE_OBSERVED
            healthy = assertion(state, "HEALTHY_AS_OF_LAST_PROBE",
                                "the newest VERIFY Evidence reports VERIFY_OK. This is the last "
                                "proven moment, not present-moment liveness",
                                [newest_verify["evidence"]["source_file"]])
            healthy["as_of"] = newest_verify["evidence"]["completed_at"]
            healthy["age_seconds"] = int(age)
            healthy["stale"] = age > stale_seconds

    inflight = [{"task_id": t["task_id"], "action_id": t["action_id"],
                 "expires_at": t["expires_at"], "lifecycle": t["lifecycle"]}
                for t in tasks if t["lifecycle"] in ("TASK_PUBLISHED", "TASK_SIGNED")]
    failed = [{"task_id": t["task_id"], "action_id": t["action_id"], "lifecycle": t["lifecycle"],
               "reason": t["assertion"]["reason"]}
              for t in tasks if t["assertion"]["state"] == STATE_FAILED]
    stale = [{"task_id": t["task_id"], "action_id": t["action_id"],
              "completed_at": t["evidence"]["completed_at"]}
             for t in tasks if t.get("staleness")]
    timed_out = [{"task_id": t["task_id"], "action_id": t["action_id"],
                  "expires_at": t["expires_at"]} for t in tasks if t["lifecycle"] == "TASK_EXPIRED"]

    rollback_sources = sorted({t["task_id"]: t["evidence"]["completed_at"] for t in deploys}.items(),
                              key=lambda pair: pair[1])
    rollback = unknown("no successful DEPLOY Evidence exists on the control bus")
    if rollback_sources:
        newest = rollback_sources[-1][0]
        rollback = assertion(STATE_OBSERVED,
                             {"source_deploy_task_id": newest,
                              "releases": [name for name, _ in rollback_sources],
                              "newest_completed_at": rollback_sources[-1][1]},
                             "rollback eligibility is a candidate set derived from successful "
                             "DEPLOY Evidence; it is not an approval and not a signed ROLLBACK task",
                             [t["evidence"]["source_file"] for t in deploys if t["task_id"] == newest])

    if pointers["hold"]:
        deploy_gate = pointers["hold"].get("hk_deploy", "HOLD")
        deploy_state = STATE_HOLD if deploy_gate == "HOLD" else STATE_OBSERVED
        deploy_assertion = assertion(
            deploy_state,
            {"deployment_requests_enabled": "UNKNOWN",
             "approved_plans": "UNKNOWN",
             "canary_evidence": "UNKNOWN"},
            "RELEASE GATES: hk_deploy=%s, final_release=%s, production=%s. A verified DEPLOY "
            "capability is not deploy authorization: the live request switch, approved plan store "
            "and fresh CANARY/VERIFY proofs are Control Plane state that this projection cannot read"
            % (deploy_gate, pointers["hold"].get("final_release"),
               pointers["hold"].get("production")))
    else:
        deploy_assertion = unknown("no canonical pointer supplied, so release gates are unknown")

    # Bind the governed runtime host to the host that actually signed liveness
    # Evidence. One instance id has three spellings; all map to one identity.
    runtime_identity = unknown("no canonical runtime pointer supplied")
    if runtime:
        pointer_host = normalize_instance(runtime.get("host"))
        probe_host = None
        if newest_health:
            probe_host = normalize_instance((newest_health.get("liveness_payload") or {}).get("hostname"))
        identity = {"pointer_host": runtime.get("host"), "normalized": pointer_host,
                    "last_probe_host": (newest_health or {}).get("liveness_payload", {}).get("hostname")
                    if newest_health else None}
        if pointer_host and probe_host:
            identity["host_matches_last_probe"] = pointer_host == probe_host
            runtime_identity = assertion(
                STATE_OBSERVED, identity,
                "the canonical runtime host %s and the host that signed liveness Evidence %s are "
                "the same instance" % (pointer_host, probe_host) if pointer_host == probe_host else
                "RUNTIME IDENTITY MISMATCH: the canonical pointer names %s but liveness Evidence was "
                "signed by %s" % (pointer_host, probe_host),
                [newest_health["evidence"]["source_file"]])
        else:
            runtime_identity = assertion(STATE_OBSERVED, identity,
                                         "canonical pointer host only; no signed liveness Evidence "
                                         "is available to bind it to a live machine")

    return {
        "schema_version": SCHEMA_VERSION,
        "contract": CONTRACT_STATE,
        "authority": AUTHORITY,
        "authority_note": ("Derived projection only. The Signed Task is the only Execution "
                           "Authority and the Signed Evidence is the only proof. This document "
                           "never authorizes an operation."),
        "generated_at": iso(at),
        "freshness": {"stale_after_seconds": stale_seconds, "liveness_window_seconds": liveness_window},
        "sources": source_refs,
        "verification": {
            "task_key_fingerprint": task_verifier.fingerprint,
            "signature_verification": "PERFORMED" if task_verifier.available else "NOT_PERFORMED",
            "proven_requires_key": True,
        },
        "counts": {
            "tasks": len(tasks), "evidence": len(loaded.evidence), "requests": len(requests),
            "by_lifecycle": lifecycle_counts(tasks), "anomalies": len(loaded.anomalies),
        },
        "requests": requests,
        "tasks": tasks,
        "control_state": {
            "health": healthy,
            "last_request": (assertion(STATE_OBSERVED,                                       requests[-1]["request_id"],
                                       "newest Request file observed on a control-bus ref",
                                       [requests[-1]["source"]["file"]])
                             if requests else unknown("no Request file observed on the control bus")),
            "last_task": last_task(),
            "last_evidence": (assertion(
                STATE_PROVEN if newest_evidence["lifecycle"] == "COMPLETE" else STATE_OBSERVED,
                {"task_id": newest_evidence["task_id"],
                 "action_id": newest_evidence["action_id"],
                 "completed_at": newest_evidence["evidence"]["completed_at"]},
                "newest signed Evidence on the control bus",
                [newest_evidence["evidence"]["source_file"]])
                if newest_evidence else unknown("no signed Evidence exists on the control bus")),
            "hk_agent_liveness": liveness,
            "hk_runtime_identity": runtime_identity,
            "verify_status": last_task("HK_STAGING_VERIFY"),
            "test_pr_status": last_task("HK_STAGING_TEST_PR"),
            "deploy_status": deploy_assertion,
            "current_runtime": runtime_assertion,
            "current_main": assertion(STATE_OBSERVED, (pointers["runtime"] or {}).get(
                "canonical_runtime_identity", {}).get("canonical_main_commit"),
                "canonical runtime pointer records the main commit the runtime was built from"),
            "current_release_candidate": assertion(
                STATE_OBSERVED, (pointers["candidate"] or {}).get("source_commit"),
                "canonical candidate pointer records the newest integrated source identity"),
            "inflight_tasks": inflight,
            "failed_tasks": failed,
            "stale_tasks": stale,
            "expired_without_evidence": timed_out,
            "last_successful_deploy": (assertion(STATE_OBSERVED, deploys[-1]["task_id"],
                                                 "newest verified DEPLOY Evidence",
                                                 [deploys[-1]["evidence"]["source_file"]])
                                       if deploys else unknown("no verified successful DEPLOY Evidence")),
            "rollback_source": rollback,
            "control_plane_drift": drift,
            "release_gates": pointers["hold"] or {"hk_deploy": "UNKNOWN", "final_release": "UNKNOWN",
                                                  "production": "UNKNOWN"},
            "final_release": assertion(
                STATE_HOLD if pointers["hold"].get("final_release") == "HOLD" else STATE_UNKNOWN,
                pointers["hold"].get("final_release"),
                "release acceptance is a separate axis from business runtime and Control Plane"),
            "hk_deploy": assertion(
                STATE_HOLD if pointers["hold"].get("hk_deploy") == "HOLD" else STATE_UNKNOWN,
                pointers["hold"].get("hk_deploy"),
                "deployment authorization is not derived from the existence of a DEPLOY capability"),
            "production": assertion(
                STATE_HOLD if pointers["hold"].get("production") in ("HOLD", "UNTOUCHED_HOLD") else STATE_UNKNOWN,
                pointers["hold"].get("production"),
                "Production has not been touched and is out of scope for the Control Plane"),
        },
        "anomalies": loaded.anomalies,
        "rebuild": {
            "deterministic": True,
            "pin_generated_at": "pass --now <ISO8601> to make the byte output reproducible",
            "command": "python control-plane/command-center-state-v1/state_projection.py --tasks-repo "
                       "<go-control-tasks> --evidence-repo <go-control-evidence> "
                       "--requests-dir <requests> --go-repo <GO> --task-verify-key <pub> "
                       "--out <dir>",
        },
    }


def verdict_for(control_state):
    """One shared health verdict so the two contracts can never disagree."""
    verify = control_state["verify_status"]
    if verify["state"] == STATE_FAILED:
        return verify
    return control_state["health"]


def build_status(state, verdict):
    cs = state["control_state"]
    tasks = state["tasks"]
    test_pr_by_pr = {}
    for task in tasks:
        if task["action_id"] != "HK_STAGING_TEST_PR":
            continue
        source = task["parameters"]["source"]
        test_pr_by_pr.setdefault(source["pr_number"], []).append({
            "task_id": task["task_id"],
            "commit_sha": source["commit_sha"],
            "lifecycle": task["lifecycle"],
            "completed_at": (task.get("evidence") or {}).get("completed_at"),
            "built_image_id": (task.get("evidence") or {}).get("built_image_id"),
            "state": task["assertion"]["state"],
        })
    blocked = [a["reason"] for a in (cs["deploy_status"],) if a["state"] in (STATE_HOLD, STATE_UNKNOWN)]
    answers = {
        "go_is_healthy": verdict,
        "hk_agent_online": cs["hk_agent_liveness"],
        "my_task_executed": {
            "last_request": cs["last_request"], "last_task": cs["last_task"],
            "last_evidence": cs["last_evidence"],
        },
        "pr_tested": {"latest": cs["test_pr_status"], "by_pr_number": test_pr_by_pr,
                      "note": "look up by_pr_number for 'did you test PR N?'"},
        "verify": cs["verify_status"],
        "deploy": cs["deploy_status"],
        "current_runtime": cs["current_runtime"],
        "current_main": cs["current_main"],
        "current_release_candidate": cs["current_release_candidate"],
        "can_deploy": {
            "state": STATE_HOLD if cs["deploy_status"]["state"] == STATE_HOLD else cs["deploy_status"]["state"],
            "value": "NO" if cs["deploy_status"]["state"] == STATE_HOLD else None,
            "reason": ("deployment authorization is not established by this projection; %s"
                       % "; ".join(blocked) if blocked else "deployability is unknown"),
            "evidence": cs["deploy_status"]["evidence"],
        },
        "stuck_tasks": cs["inflight_tasks"] + cs["expired_without_evidence"],
        "pending_evidence": cs["inflight_tasks"],
        "rollback_targets": cs["rollback_source"],
        "control_plane_drift": cs["control_plane_drift"],
        "release_gates": cs["release_gates"],
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "contract": CONTRACT_STATUS,
        "audience": "CHATGPT_CONNECTOR / HUMAN_OPERATOR",
        "authority": AUTHORITY,
        "generated_at": state["generated_at"],
        "freshness": state["freshness"],
        "sources": state["sources"],
        "verification": state["verification"],
        "answers": answers,
        "limits": {
            "read_contract_only": "This is a bounded read contract. It is not Execution Authority "
                                  "and it never contains execution parameters.",
            "unobservable_by_this_projection": [
                "the live Command Center channel switch and approved plan store",
                "the Hong Kong agent ledger (attempts, failures, nonce claims)",
                "runtime process state on HK-STAGING",
            ],
            "never_infer": "last successful task != agent online; runtime ACTIVE != release accepted",
        },
        "verdict": {
            "healthy": verdict,
            "blockers": [{"source": "deploy_status", "reason": r} for r in blocked],
        },
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tasks-repo", required=True, help="local checkout of go-control-tasks")
    parser.add_argument("--evidence-repo", required=True, help="local checkout of go-control-evidence")
    parser.add_argument("--requests-dir", help="optional directory of collected Request files")
    parser.add_argument("--go-repo", help="optional local checkout of the GO repository")
    parser.add_argument("--task-verify-key", help="pinned Command Center task public key")
    parser.add_argument("--out", required=True, help="output directory (created if absent)")
    parser.add_argument("--now", help="ISO 8601 instant to project at (default: current UTC)")
    parser.add_argument("--stale-after-seconds", type=int, default=86400)
    parser.add_argument("--liveness-window-seconds", type=int, default=1800)
    parser.add_argument("--tasks-head", default=None)
    parser.add_argument("--evidence-head", default=None)
    parser.add_argument("--stdout", action="store_true", help="also print CONTROL_STATUS_V1")
    args = parser.parse_args(argv)

    at = parse_time(args.now) if args.now else now_utc().replace(microsecond=0)
    loaded = Loaded()
    load_tasks(args.tasks_repo, loaded)
    load_evidence(args.evidence_repo, loaded)
    load_requests(args.requests_dir, loaded)
    verifier = Verifier(args.task_verify_key)

    state = build_state(loaded, verifier, at, args.stale_after_seconds, args.go_repo,
                        args.liveness_window_seconds,
                        {"tasks_repo": args.tasks_repo, "tasks_head": args.tasks_head,
                         "evidence_repo": args.evidence_repo, "evidence_head": args.evidence_head,
                         "requests_dir": args.requests_dir, "go_repo": args.go_repo})
    # One shared verdict feeds both contracts, so they can never disagree.
    status = build_status(state, verdict_for(state["control_state"]))

    index = {
        "schema_version": SCHEMA_VERSION,
        "contract": "TASK_INDEX",
        "authority": AUTHORITY,
        "generated_at": state["generated_at"],
        "entries": [{
            "task_id": t["task_id"], "action_id": t["action_id"], "lifecycle": t["lifecycle"],
            "issued_at": t["issued_at"], "expires_at": t["expires_at"],
            "task_sha256": t["task_sha256"], "source_file": t["source_file"],
            "evidence_state": (t.get("evidence") or {}).get("status", "NO_EVIDENCE_PUBLISHED"),
            "evidence_file": (t.get("evidence") or {}).get("source_file"),
            "evidence_sha256": (t.get("evidence") or {}).get("evidence_sha256"),
            "assertion_state": t["assertion"]["state"],
        } for t in state["tasks"]],
    }
    latest = {
        "schema_version": SCHEMA_VERSION,
        "contract": "LATEST_EVIDENCE",
        "authority": AUTHORITY,
        "generated_at": state["generated_at"],
        "by_action": {},
    }
    for task in sorted((t for t in state["tasks"] if t.get("evidence")),
                       key=lambda t: t["evidence"]["completed_at"]):
        latest["by_action"][task["action_id"]] = {
            "task_id": task["task_id"], "completed_at": task["evidence"]["completed_at"],
            "file": task["evidence"]["source_file"], "sha256": task["evidence"]["evidence_sha256"],
            "status": task["evidence"]["status"], "lifecycle": task["lifecycle"],
        }

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, payload in (("CURRENT_CONTROL_STATE.json", state),
                          ("CONTROL_STATUS_V1.json", status),
                          ("TASK_INDEX.json", index),
                          ("LATEST_EVIDENCE.json", latest)):
        path = out / name
        path.write_bytes(json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    summary = {
        "contract": CONTRACT_STATUS, "generated_at": state["generated_at"],
        "tasks": state["counts"]["tasks"], "evidence": state["counts"]["evidence"],
        "requests": state["counts"]["requests"],
        "by_lifecycle": state["counts"]["by_lifecycle"],
        "signature_verification": state["verification"]["signature_verification"],
        "hk_agent_liveness": status["answers"]["hk_agent_online"]["state"],
        "control_plane_drift": status["answers"]["control_plane_drift"]["value"],
        "anomalies": [a["kind"] for a in state["anomalies"]],
        "out": str(out),
    }
    print(json.dumps(summary, sort_keys=True))
    if args.stdout:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
