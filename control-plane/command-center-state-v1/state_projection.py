#!/usr/bin/env python3
"""GO Command Center control-state projection — CONTROL_STATE_V1.

Scope: CONTROL_STATE_AND_STATUS_ONLY.

Read-only, offline, deterministic projection of the GitHub-native Control Plane.
It answers one question: *given only the control bus, what is the current control
state?*  It never invents an answer.  Every leaf is an assertion carrying a state
from {PROVEN, OBSERVED, PENDING, HOLD, FAILED, UNKNOWN} plus the evidence
references that produced it.  Absence of evidence is reported as UNKNOWN, never
as success.

Identity discipline
-------------------
Signed Tasks and Signed Evidence are verified with **different** verifier
identities:

  * the Command Center task-manifest signing key  (``--task-verify-key``)
  * the Hong Kong agent evidence signing key      (``--evidence-verify-key``)

A Task must never validate against the evidence key and Evidence must never
validate against the task key.  If both public keys turn out to be the same key,
the projection refuses to claim PROVEN for anything and records a
VERIFIER_IDENTITY_COLLISION anomaly.

Runtime discipline
------------------
A repository pointer is a *declaration*.  It is never the truth about what is
running on Hong Kong.  ``repository_runtime_pointer`` and ``live_verified_runtime``
are separate objects, and ``runtime_verification`` reports MATCH / DRIFT /
NOT_RECENTLY_VERIFIED / UNKNOWN.

Portability
-----------
The derived output contains no workstation path, no temp directory and no local
absolute path.  Sources are identified by repository, ref, commit SHA, artifact
id and repository-relative path only, so two different machines projecting the
same inputs produce a semantically equivalent, stable document.

Authority
---------
The output is a DERIVED, NON-AUTHORITATIVE view.  The Signed Task is the only
Execution Authority and the Signed Evidence is the only proof.  This file is
never hand-edited and is always rebuildable.
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
CONTRACT_SCOPE = "CONTROL_STATE_AND_STATUS_ONLY"

STATE_PROVEN = "PROVEN"
STATE_OBSERVED = "OBSERVED"
STATE_PENDING = "PENDING"
STATE_HOLD = "HOLD"
STATE_FAILED = "FAILED"
STATE_UNKNOWN = "UNKNOWN"

RUNTIME_MATCH = "MATCH"
RUNTIME_DRIFT = "DRIFT"
RUNTIME_NOT_RECENTLY_VERIFIED = "NOT_RECENTLY_VERIFIED"
RUNTIME_UNKNOWN = "UNKNOWN"

AUTHORITY = "DERIVED_NON_AUTHORITATIVE"

TASKS_REPOSITORY = "chenzhenxi1-sudo/go-control-tasks"
EVIDENCE_REPOSITORY = "chenzhenxi1-sudo/go-control-evidence"
GO_REPOSITORY = "yuguangzhi3836-glitch/GO"
CANONICAL_RUNTIME_POINTER = "docs/canonical-baseline/CURRENT_HK_RUNTIME.json"
CANONICAL_CANDIDATE_POINTER = "docs/canonical-baseline/CURRENT_CANDIDATE.json"

TASK_VERIFIER_IDENTITY = "GO Command Center task-manifest signer"
EVIDENCE_VERIFIER_IDENTITY = "Hong Kong agent evidence signer"

# Every action the Control Plane can execute.
KNOWN_CAPABILITIES = (
    "CONTROL_PLANE_HEALTH",
    "HK_STAGING_VERIFY",
    "HK_STAGING_TEST_PR",
    "HK_STAGING_DEPLOY",
    "HK_STAGING_CANARY",
    "HK_STAGING_ROLLBACK",
)
# The only actions a human / ChatGPT Request channel may currently create.
ENABLED_REQUEST_ACTIONS = ("HK_STAGING_VERIFY", "HK_STAGING_TEST_PR")
CAPABILITY_CLASSIFICATION = {
    "HK_STAGING_VERIFY": "SUPPORTED_PROVEN",
    "HK_STAGING_TEST_PR": "SUPPORTED_PROVEN",
    "HK_STAGING_DEPLOY": "CAPABILITY_PRESENT_BUT_DISABLED",
    "HK_STAGING_CANARY": "NOT_REQUESTABLE",
    "HK_STAGING_ROLLBACK": "NOT_REQUESTABLE",
    "CONTROL_PLANE_HEALTH": "PLATFORM_ADMIN_ONLY",
}

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

# Anything that would make the derived document machine-specific.
LOCAL_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\[^\\]|/home/|/Users/|/var/folders/|AppData)")


def normalize_instance(value):
    """Map the three observed spellings of one Alibaba instance id to one form.

    ``i-j6ccs8t04f1p4d8pe69z`` (workbench), ``iZj6ccs8t04f1p4d8pe69zZ`` (uname
    nodename inside the guest) and the bare ``j6ccs8t04f1p4d8pe69z`` all denote
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
# signature verification — two separate identities
# --------------------------------------------------------------------------- #
class Verifier:
    """One Ed25519 verifier identity.

    Reports NOT_PERFORMED rather than assuming success when no key is supplied.
    ``encoding`` is carried per artifact: tasks are hex, evidence is base64.
    """

    def __init__(self, key_path, identity, encoding):
        self.identity = identity
        self.encoding = encoding
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

    def disabled_copy(self):
        return Verifier(None, self.identity, self.encoding)

    def verify(self, obj, encoding=None):
        """Return True / False / None (None = could not be performed)."""
        if not self.available:
            return None
        encoding = encoding or self.encoding
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

    def describe(self):
        return {"identity": self.identity, "encoding": self.encoding,
                "key_fingerprint": self.fingerprint,
                "signature_verification": "PERFORMED" if self.available else "NOT_PERFORMED"}


def separated(task_verifier, evidence_verifier, loaded):
    """Enforce that the two verifier identities are genuinely different keys."""
    if not (task_verifier.available and evidence_verifier.available):
        return True
    if task_verifier.fingerprint == evidence_verifier.fingerprint:
        loaded.anomaly("VERIFIER_IDENTITY_COLLISION",
                       "the task verifier and the evidence verifier resolve to the same public "
                       "key; the two signing identities must be distinct, so no PROVEN claim is "
                       "made in this run", task_verifier.fingerprint)
        return False
    return True


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
    terminal = evidence["completed_at"] if generation == "v2" else evidence["finished_at"]
    parse_time(terminal)
    out = dict(evidence)
    out["_generation"] = generation
    out["_completed_at"] = terminal
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
        self.tasks = []            # (file name, task)
        self.evidence = []         # (file name, evidence)
        self.requests = []         # (ref, head_sha, file name, request)
        self.anomalies = []        # {kind, detail, ref}

    def anomaly(self, kind, detail, ref=None):
        self.anomalies.append({"kind": kind, "detail": detail, "ref": ref})


def load_tasks(root, loaded):
    folder = pathlib.Path(root) / "tasks"
    if not folder.is_dir():
        loaded.anomaly("TASKS_DIRECTORY_MISSING", "%s/tasks" % TASKS_REPOSITORY)
        return
    for path in sorted(folder.glob("*.json")):
        try:
            loaded.tasks.append((path.name, validate_task(read_json(path))))
        except (Malformed, ValueError, OSError, UnicodeError) as exc:
            loaded.anomaly("TASK_UNREADABLE", "%s" % exc, path.name)


def load_evidence(root, loaded):
    folder = pathlib.Path(root) / "evidence"
    if not folder.is_dir():
        loaded.anomaly("EVIDENCE_DIRECTORY_MISSING", "%s/evidence" % EVIDENCE_REPOSITORY)
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
        loaded.anomaly("REQUESTS_DIRECTORY_MISSING",
                       "collected Request files were not supplied")
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
        action = request["action_id"]
        requestable = action in ENABLED_REQUEST_ACTIONS
        out.append({
            "schema_version": "1",
            "request_id": request["request_id"],
            "action_id": action,
            "environment": request["environment"],
            "requested_at": request["requested_at"],
            "target": {k: request[k] for k in sorted(set(request) - REQUEST_REQUIRED)},
            "request_sha256": digest(request),
            "source": {"repository": TASKS_REPOSITORY, "ref": ref,
                       "head_sha": head, "path": "requests/" + source},
            "requestable_by_current_channel": requestable,
            "capability_classification": CAPABILITY_CLASSIFICATION.get(action, "UNKNOWN"),
            "holding_execution_authority": False,
            # Command Center acceptance is a Bridge-ledger fact, not a control-bus
            # fact, so a Request is only ever reported as CREATED.
            "lifecycle": "REQUEST_CREATED",
            "duplicate_request_id": duplicate,
        })
    return out


def task_records(loaded, task_verifier, evidence_verifier, at, stale_seconds):
    by_nonce, by_id = {}, {}
    evidence_by_key = {}
    for name, item in loaded.evidence:
        evidence_by_key.setdefault((item["task_id"], item["nonce"]), []).append((name, item))

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
        signature = task_verifier.verify(task, "hex")
        entry = {
            "task_id": task["task_id"],
            "nonce": task["nonce"],
            "action_id": task["action_id"],
            "environment": task["environment"],
            "authority": task["authority"],
            "issued_at": task["issued_at"],
            "expires_at": task["expires_at"],
            "parameters": task["parameters"],
            "task_sha256": digest({k: v for k, v in task.items() if k != "signature"}),
            "source": {"repository": TASKS_REPOSITORY, "path": "tasks/" + name},
            "task_signature_verified": signature,
            "task_verifier_identity": TASK_VERIFIER_IDENTITY,
            "parameter_contract": task.get("_parameter_contract", "CURRENT"),
        }
        expires = parse_time(task["expires_at"])
        candidates = evidence_by_key.get((task["task_id"], task["nonce"]), [])
        if len(candidates) > 1:
            digests = {digest({k: v for k, v in item.items() if not k.startswith("_")})
                       for _, item in candidates}
            if len(digests) > 1:
                loaded.anomaly("EVIDENCE_CONFLICT",
                               "multiple distinct Evidence records for one signed task",
                               task["task_id"])
            entry["evidence_count"] = len(candidates)
        if signature is False:
            entry.update({"lifecycle": "POLICY_HOLD",
                          "assertion": assertion(STATE_FAILED, "TASK_SIGNATURE_INVALID",
                                                 "the task signature does not verify against the "
                                                 "Command Center task verifier identity", refs)})
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
                        "the agent ledger is not on the control bus, so absence of Evidence cannot "
                        "distinguish TASK_NOT_PICKED_UP from an unpublished failure", refs),
                })
            else:
                entry.update({
                    "lifecycle": "TASK_PUBLISHED",
                    "assertion": assertion(STATE_OBSERVED, "TASK_PUBLISHED",
                                           "signed task published and still inside its validity "
                                           "window", refs),
                    "hk_agent_picked_up": unknown("no Evidence published yet", refs),
                })
            records.append(entry)
            continue

        ev_name, ev = sorted(candidates, key=lambda pair: pair[1]["_completed_at"])[0]
        refs = sorted({name, ev_name})
        ev_signature = evidence_verifier.verify(ev, "base64")
        completed = parse_time(ev["_completed_at"])
        started = parse_time(ev["started_at"])
        # The health payload sits at executor_result in the current agent and at
        # result in the legacy generation; both are read-only observations.
        payload = ev.get("executor_result")
        if not isinstance(payload, dict):
            payload = ev.get("result") if isinstance(ev.get("result"), dict) else None
        entry["evidence"] = {
            "source": {"repository": EVIDENCE_REPOSITORY,
                       "path": "evidence/" + ev_name},
            "completed_at": ev["_completed_at"],
            "generation": ev["_generation"],
            "status": ev["status"],
            "executor_result": ev.get("executor_result") if isinstance(ev.get("executor_result"), str)
            else (ev.get("result") if isinstance(ev.get("result"), str) else None),
            "signature_verified": ev_signature,
            "verifier_identity": EVIDENCE_VERIFIER_IDENTITY,
            "evidence_sha256": digest({k: v for k, v in ev.items() if not k.startswith("_")}),
        }
        if payload:
            entry["liveness_payload"] = {
                "hostname": payload.get("hostname"),
                "agent_version": payload.get("agent_version"),
                "tasks_repo_connectivity": payload.get("tasks_repo_connectivity"),
                "evidence_repo_connectivity": payload.get("evidence_repo_connectivity"),
            }
        for key in ("built_image_id", "source_pr_number", "source_commit_sha",
                    "task_canonical_sha256", "deploy_record_id", "deploy_record_sha256",
                    "rollback_record_id"):
            if isinstance(ev.get(key), str):
                entry["evidence"][key] = ev[key]
        if isinstance(ev.get("agent_version"), str):
            entry["evidence"]["agent_version"] = ev["agent_version"]
        entry["execution_started"] = assertion(
            STATE_PROVEN if ev_signature else STATE_OBSERVED, ev["started_at"],
            "the Evidence carries started_at for this task/nonce", refs)

        verified = ev_signature is True
        if ev_signature is False:
            entry.update({"lifecycle": "EVIDENCE_INVALID",
                          "assertion": assertion(STATE_FAILED, "EVIDENCE_SIGNATURE_INVALID",
                                                 "the Evidence signature does not verify against the "
                                                 "Hong Kong evidence verifier identity", refs)})
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
                                                 "the signed Evidence reports a non-success status",
                                                 refs)})
        else:
            expected = ACTION_RESULT.get(task["action_id"])
            result = ev.get("executor_result") if isinstance(ev.get("executor_result"), str) else None
            mismatch = bool(expected) and result != expected
            task_established = signature is True
            if mismatch and verified:
                entry.update({"lifecycle": "EXECUTION_FAILED",
                              "assertion": assertion(STATE_FAILED, "EXECUTOR_RESULT_MISMATCH",
                                                     "executor_result %r does not equal the frozen "
                                                     "terminal result %r" % (result, expected), refs)})
            elif mismatch:
                entry.update({"lifecycle": "EVIDENCE_PUBLISHED",
                              "assertion": assertion(
                                  STATE_OBSERVED, "EXECUTOR_RESULT_MISMATCH",
                                  "Evidence reports %r instead of the frozen terminal result %r, but "
                                  "the evidence signature was not verified, so OBSERVED is the "
                                  "strongest honest claim" % (result, expected), refs)})
            elif verified and task_established:
                entry.update({"lifecycle": "COMPLETE",
                              "assertion": assertion(STATE_PROVEN, expected or "HEALTH_OK",
                                                     "Evidence verified against the Hong Kong evidence "
                                                     "verifier identity, its Task verified against the "
                                                     "Command Center task verifier identity, and it "
                                                     "reports the frozen terminal result", refs)})
            elif verified:
                entry.update({"lifecycle": "EVIDENCE_VERIFIED",
                              "assertion": assertion(
                                  STATE_OBSERVED, "EVIDENCE_VERIFIED",
                                  "the Evidence verifies against the Hong Kong evidence identity, but "
                                  "no Command Center task verifier key was supplied, so the Task this "
                                  "Evidence claims to answer was never established and COMPLETE "
                                  "cannot be claimed", refs)})
            else:
                entry.update({"lifecycle": "EVIDENCE_PUBLISHED",
                              "assertion": assertion(
                                  STATE_OBSERVED, "EVIDENCE_PUBLISHED",
                                  "Evidence is published and reports %r, but no evidence verifier "
                                  "key was supplied, so OBSERVED is the strongest honest claim"
                                  % (result or "no result"), refs)})
        if at - completed > dt.timedelta(seconds=stale_seconds):
            entry["staleness"] = assertion(STATE_OBSERVED, "STALE",
                                           "the newest Evidence for this task is older than the "
                                           "configured freshness window", refs)
        records.append(entry)
    return records


def lifecycle_counts(tasks):
    counts = {}
    for task in tasks:
        counts[task["lifecycle"]] = counts.get(task["lifecycle"], 0) + 1
    return counts


def newest_for(tasks, action):
    matches = [t for t in tasks if t["action_id"] == action]
    if not matches:
        return None
    return max(matches, key=lambda t: t["evidence"]["completed_at"])


def canonical_pointers(go_repo):
    out = {"runtime": None, "candidate": None, "hold": {}, "read_errors": []}
    if not go_repo:
        return out
    base = pathlib.Path(go_repo) / "docs" / "canonical-baseline"
    for key, name in (("runtime", "CURRENT_HK_RUNTIME.json"),
                      ("candidate", "CURRENT_CANDIDATE.json")):
        try:
            out[key] = read_json(base / name)
        except (OSError, ValueError) as exc:
            out["read_errors"].append("%s:%s" % (name, type(exc).__name__))
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


def source_identity(args, request_count):
    """Stable, portable provenance. Never a workstation path."""
    return {
        "tasks": {"repository": TASKS_REPOSITORY, "ref": args.tasks_ref,
                  "head_sha": args.tasks_head},
        "evidence": {"repository": EVIDENCE_REPOSITORY, "ref": args.evidence_ref,
                     "head_sha": args.evidence_head},
        "requests": {"repository": TASKS_REPOSITORY,
                     "refs": ["refs/heads/boss-request-*", "refs/heads/request/*"],
                     "collected": request_count},
        "go": {"repository": GO_REPOSITORY, "ref": args.go_ref, "head_sha": args.go_head,
               "canonical_runtime_pointer": CANONICAL_RUNTIME_POINTER,
               "canonical_candidate_pointer": CANONICAL_CANDIDATE_POINTER},
    }


def build_state(loaded, task_verifier, evidence_verifier, at, options):
    stale_seconds = options["stale_seconds"]
    liveness_window = options["liveness_window"]
    verification_window = options["verification_window"]
    stuck_after = options["stuck_after"]
    recent_window = options["recent_window"]

    tasks = task_records(loaded, task_verifier, evidence_verifier, at, stale_seconds)
    requests = request_records(loaded)
    pointers = canonical_pointers(options.get("go_repo"))

    def has_success(task):
        return (task.get("evidence") or {}).get("status") == "SUCCESS"

    # `completed` = signature-verified success (PROVEN territory)
    # `observed`  = published success whose chain could not be fully verified here
    completed = [t for t in tasks if t["lifecycle"] == "COMPLETE"]
    observed = [t for t in tasks
                if t["lifecycle"] in ("EVIDENCE_PUBLISHED", "EVIDENCE_VERIFIED") and has_success(t)]
    successes = completed + observed
    deploys = [t for t in successes if t["action_id"] == "HK_STAGING_DEPLOY"
               and t["assertion"]["state"] != STATE_FAILED]
    health = [t for t in successes if t["action_id"] == "CONTROL_PLANE_HEALTH"]
    newest_health = max(health, key=lambda t: t["evidence"]["completed_at"], default=None)
    newest_evidence = (max(successes, key=lambda t: t["evidence"]["completed_at"], default=None)
                       or max((t for t in tasks if t.get("evidence")),
                              key=lambda t: t["evidence"]["completed_at"], default=None))

    def last_task(action=None):
        pool = [t for t in tasks if action is None or t["action_id"] == action]
        if not pool:
            return unknown("no signed task of this class exists on the control bus yet")
        pick = max(pool, key=lambda t: t["evidence"]["completed_at"]
                   if t.get("evidence") else t["issued_at"])
        state = STATE_OBSERVED if pick["task_signature_verified"] is None else (
            STATE_PROVEN if pick["task_signature_verified"] else STATE_FAILED)
        return assertion(state,
                         {"task_id": pick["task_id"], "action_id": pick["action_id"],
                          "lifecycle": pick["lifecycle"], "issued_at": pick["issued_at"],
                          "expires_at": pick["expires_at"]},
                         "the newest signed task of this class observed on the control bus",
                         [pick["source"]["path"]]
                         + ([pick["evidence"]["source"]["path"]] if pick.get("evidence") else []))

    # ---- HK agent activity and liveness ------------------------------------ #
    last_activity = unknown("no CONTROL_PLANE_HEALTH Evidence exists on the control bus")
    liveness = unknown("no CONTROL_PLANE_HEALTH Evidence exists on the control bus")
    if newest_health:
        age = (at - parse_time(newest_health["evidence"]["completed_at"])).total_seconds()
        payload = newest_health.get("liveness_payload") or {}
        probe = newest_health["evidence"]["source"]["path"]
        last_activity = assertion(
            STATE_PROVEN if newest_health["lifecycle"] == "COMPLETE" else STATE_OBSERVED,
            {"completed_at": newest_health["evidence"]["completed_at"],
             "hostname": payload.get("hostname"), "agent_version": payload.get("agent_version"),
             "age_seconds": int(age)},
            "the newest signed CONTROL_PLANE_HEALTH Evidence, at any age. Activity is not liveness",
            [probe])
        if age > liveness_window:
            liveness = assertion(STATE_UNKNOWN, None,
                                 "the newest signed liveness Evidence is %d s old, outside the "
                                 "%d s window: a past success is not proof of current liveness"
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

    # ---- repository-declared runtime vs live verified runtime -------------- #
    runtime = pointers["runtime"] or {}
    image = runtime.get("image") or {}
    pointer_image = image.get("image_config_id")
    runtime_identity = runtime.get("canonical_runtime_identity") or {}
    source_identity_block = runtime.get("product_source_identity") or {}

    if pointer_image:
        repository_runtime = assertion(
            STATE_OBSERVED, {"image_config_id": pointer_image,
                             "image_tag": image.get("image_tag"),
                             "runtime_generation": runtime.get("runtime_generation"),
                             "host": runtime.get("host"),
                             "pointer_path": CANONICAL_RUNTIME_POINTER},
            "the repository declares this runtime. A declaration is never the truth about what is "
            "running on Hong Kong, so this can never be PROVEN",
            [CANONICAL_RUNTIME_POINTER])
    else:
        repository_runtime = unknown("no canonical runtime pointer was supplied")

    newest_verify = newest_for(successes, "HK_STAGING_VERIFY")
    live_image, live_state = None, RUNTIME_UNKNOWN
    if newest_verify:
        live_image = newest_verify["parameters"].get("expected_current_image_id")
        verify_age = (at - parse_time(newest_verify["evidence"]["completed_at"])).total_seconds()
        verified = newest_verify["lifecycle"] == "COMPLETE"
        live_verified = assertion(
            STATE_PROVEN if verified else STATE_OBSERVED,
            {"image_config_id": live_image,
             "verified_at": newest_verify["evidence"]["completed_at"],
             "age_seconds": int(verify_age),
             "verification_rank": "SIGNATURE_VERIFIED" if verified else "OBSERVED_ONLY"},
            "the newest VERIFY Evidence names the image that was current at that moment. This is a "
            "point-in-time proof, not a continuous statement",
            [newest_verify["evidence"]["source"]["path"]])
        if pointer_image and live_image == pointer_image:
            image_relation = "MATCH"
        elif pointer_image:
            image_relation = "DIFFER"
        else:
            image_relation = "UNKNOWN"
        detail = {"verdict": RUNTIME_UNKNOWN, "image_relation": image_relation,
                  "repository_declared_image": pointer_image,
                  "live_proven_image": live_image,
                  "live_verification_age_seconds": int(verify_age),
                  "live_verification_rank": "SIGNATURE_VERIFIED" if verified else "OBSERVED_ONLY"}
        refs = sorted({newest_verify["evidence"]["source"]["path"]}
                      | ({CANONICAL_RUNTIME_POINTER} if pointer_image else set()))
        fresh = verify_age <= verification_window
        if not fresh:
            live_state = RUNTIME_NOT_RECENTLY_VERIFIED
            detail["verdict"] = live_state
            verification_assertion = assertion(
                STATE_OBSERVED, detail,
                "the newest VERIFY Evidence is %d s old, outside the %d s window, so the live "
                "runtime is not recently verified. The declared and proven images %s"
                % (int(verify_age), verification_window,
                   "are the same image" if image_relation == "MATCH" else
                   "differ" if image_relation == "DIFFER" else "cannot be compared"),
                refs)
        elif image_relation == "MATCH":
            live_state = RUNTIME_MATCH
            detail["verdict"] = live_state
            verification_assertion = assertion(
                STATE_PROVEN if verified else STATE_OBSERVED, detail,
                "the live VERIFY Evidence and the repository pointer name the same image",
                refs)
        elif image_relation == "DIFFER":
            live_state = RUNTIME_DRIFT
            detail["verdict"] = live_state
            verification_assertion = assertion(
                STATE_PROVEN if verified else STATE_OBSERVED, detail,
                "the live VERIFY Evidence names %s while the repository pointer declares %s: the "
                "declared runtime has no live proof and the proven runtime is not the declared one"
                % (live_image, pointer_image), refs)
        else:
            verification_assertion = assertion(
                STATE_OBSERVED, detail,
                "no repository pointer was supplied, so the live runtime cannot be compared", refs)
    else:
        live_verified = unknown("no VERIFY Evidence carrying a runtime image was observed")
        verification_assertion = unknown(
            "no VERIFY Evidence exists on the control bus, so live runtime verification is unknown")

    runtime_identity_assertion = unknown("no canonical runtime pointer supplied")
    if runtime:
        pointer_host = normalize_instance(runtime.get("host"))
        probe_host = normalize_instance(
            (newest_health or {}).get("liveness_payload", {}).get("hostname")) if newest_health else None
        identity = {"pointer_host": runtime.get("host"), "normalized": pointer_host,
                    "last_probe_host": (newest_health or {}).get("liveness_payload", {})
                    .get("hostname") if newest_health else None}
        if pointer_host and probe_host:
            identity["host_matches_last_probe"] = pointer_host == probe_host
            runtime_identity_assertion = assertion(
                STATE_OBSERVED, identity,
                "the canonical runtime host and the host that signed liveness Evidence are the same "
                "instance" if pointer_host == probe_host else
                "RUNTIME IDENTITY MISMATCH: the canonical pointer names %s but liveness Evidence was "
                "signed by %s" % (pointer_host, probe_host),
                [newest_health["evidence"]["source"]["path"]])
        else:
            runtime_identity_assertion = assertion(
                STATE_OBSERVED, identity,
                "canonical pointer host only; no signed liveness Evidence is available to bind it to "
                "a live machine")

    # ---- health, verify, test_pr ------------------------------------------ #
    health_assertion = unknown("no Evidence of any kind exists on the control bus")
    if newest_verify:
        age = (at - parse_time(newest_verify["evidence"]["completed_at"])).total_seconds()
        if newest_verify["assertion"]["state"] == STATE_FAILED:
            health_assertion = assertion(
                STATE_FAILED, newest_verify["lifecycle"],
                "the newest VERIFY task did not reach a successful terminal state",
                [newest_verify["source"]["path"]])
        else:
            rank = STATE_PROVEN if newest_verify["lifecycle"] == "COMPLETE" else STATE_OBSERVED
            health_assertion = assertion(
                rank, "HEALTHY_AS_OF_LAST_PROBE",
                "the newest VERIFY Evidence reports VERIFY_OK. This is the last proven moment, not "
                "present-moment liveness", [newest_verify["evidence"]["source"]["path"]])
            health_assertion["as_of"] = newest_verify["evidence"]["completed_at"]
            health_assertion["age_seconds"] = int(age)
            health_assertion["stale"] = age > stale_seconds

    newest_test_pr = newest_for(successes, "HK_STAGING_TEST_PR")
    test_pr = unknown("no successful TEST_PR Evidence was observed")
    if newest_test_pr:
        verifier_rank = STATE_PROVEN if newest_test_pr["lifecycle"] == "COMPLETE" else STATE_OBSERVED
        test_pr = assertion(
            verifier_rank,
            {"task_id": newest_test_pr["task_id"],
             "pr_number": newest_test_pr["parameters"]["source"]["pr_number"],
             "commit_sha": newest_test_pr["parameters"]["source"]["commit_sha"],
             "result": newest_test_pr["evidence"].get("executor_result"),
             "built_image_id": newest_test_pr["evidence"].get("built_image_id"),
             "completed_at": newest_test_pr["evidence"]["completed_at"],
             "application_health_proven": False, "deployment_performed": False},
            "the newest successful TEST_PR Evidence. An isolated offline build is not a deployment",
            [newest_test_pr["evidence"]["source"]["path"]])

    # ---- task population classification ----------------------------------- #
    def brief(task):
        return {"task_id": task["task_id"], "action_id": task["action_id"],
                "lifecycle": task["lifecycle"], "issued_at": task["issued_at"],
                "expires_at": task["expires_at"],
                "source_path": task["source"]["path"]}

    active = [t for t in tasks if t["lifecycle"] in ("TASK_PUBLISHED", "TASK_SIGNED")]
    active_stuck = [t for t in active
                    if (at - parse_time(t["issued_at"])).total_seconds() > stuck_after]
    expired = [t for t in tasks if t["lifecycle"] == "TASK_EXPIRED"]
    recent_expired = [t for t in expired
                      if parse_time(t["expires_at"]) >= at - dt.timedelta(seconds=recent_window)]
    historical_expired = [t for t in expired if t not in recent_expired]
    broken = [t for t in tasks if t["lifecycle"] in
              ("EXECUTION_FAILED", "EVIDENCE_INVALID", "EVIDENCE_TIMEOUT", "POLICY_HOLD")]

    if active_stuck:
        stuck_answer = assertion(
            STATE_OBSERVED, "YES",
            "%d task(s) are published, still inside their validity window and more than %d s old "
            "with no Evidence" % (len(active_stuck), stuck_after),
            [t["source"]["path"] for t in active_stuck])
    else:
        stuck_answer = assertion(
            STATE_OBSERVED, "NO",
            "no published task is overdue. %d recently expired and %d historical expired task(s) "
            "are indexed separately and do not affect current health"
            % (len(recent_expired), len(historical_expired)))

    last_failure = unknown("no failed, invalid, hold or expired task was observed")
    terminal_non_success = broken + expired
    if terminal_non_success:
        def terminal_rank(task):
            return ((task.get("evidence") or {}).get("completed_at")) or task["expires_at"]
        pick = max(terminal_non_success, key=terminal_rank)
        proven_failure = pick in broken
        last_failure = assertion(
            STATE_OBSERVED,
            {"task_id": pick["task_id"], "action_id": pick["action_id"],
             "lifecycle": pick["lifecycle"], "value": pick["assertion"]["value"],
             "kind": "FAILED_RECORD" if proven_failure else "EXPIRED_WITHOUT_EVIDENCE",
             "at": terminal_rank(pick)},
            ("the most recent terminal failure record on the control bus" if proven_failure else
             "the most recent terminal non-success is an expiry, not a proven failure: the task "
             "reached its expiry with no Evidence, and the agent ledger that would distinguish "
             "'never picked up' from 'failed unpublished' is not on the control bus"),
            [pick["source"]["path"]])

    # ---- rollback candidates ---------------------------------------------- #
    rollback_pairs = sorted({t["task_id"]: t["evidence"]["completed_at"] for t in deploys}.items(),
                            key=lambda pair: pair[1])
    rollback = unknown("no successful DEPLOY Evidence exists on the control bus")
    if rollback_pairs:
        newest_deploy = rollback_pairs[-1][0]
        rollback = assertion(
            STATE_OBSERVED,
            {"source_deploy_task_id": newest_deploy,
             "releases": [name for name, _ in rollback_pairs],
             "newest_completed_at": rollback_pairs[-1][1]},
            "rollback eligibility is a candidate set derived from successful DEPLOY Evidence. It is "
            "not an approval and not a signed ROLLBACK task",
            [t["evidence"]["source"]["path"] for t in deploys if t["task_id"] == newest_deploy])

    # ---- request channel and deploy capability ---------------------------- #
    request_channel = {
        "enabled_request_actions": list(ENABLED_REQUEST_ACTIONS),
        "known_capabilities": list(KNOWN_CAPABILITIES),
        "capability_classification": dict(CAPABILITY_CLASSIFICATION),
        "deploy_request_enabled": False,
        "deploy_request_enabled_source": (
            "the authoritative Boss Request contract currently exposes VERIFY and TEST_PR only; "
            "the DEPLOY request capability is present in the repository and installed per its "
            "closeout, but its request enablement remains fail-closed"),
        "live_request_switch": unknown(
            "the live Command Center channel switch is a live-host fact. It is not on the control "
            "bus and this projection must not assert it"),
        "readiness_evaluation": "NOT_IN_SCOPE",
        "note": ("ChatGPT may create Request files only for enabled_request_actions. HK_STAGING_DEPLOY "
                 "is reported as a capability classification; computing deploy or rollback readiness "
                 "is out of scope for this contract"),
    }

    # ---- repository main vs runtime build source --------------------------- #
    repository_main = (assertion(STATE_OBSERVED, options["repository_main_sha"],
                                 "the repository main revision supplied to this run")
                       if options.get("repository_main_sha")
                       else unknown(
                           "the current repository main revision was not supplied. The projector "
                           "reads local checkouts and never runs git, so it will not substitute a "
                           "runtime source SHA for the repository head"))
    runtime_built_from = (assertion(
        STATE_OBSERVED, source_identity_block.get("source_commit"),
        "the repository records the product source commit that this runtime was built from",
        [CANONICAL_RUNTIME_POINTER])
        if source_identity_block.get("source_commit")
        else unknown("the canonical runtime pointer does not record a product source commit"))
    runtime_canonical_main = (assertion(
        STATE_OBSERVED, runtime_identity.get("canonical_main_commit"),
        "the repository records the main commit at which the canonical runtime definition was "
        "frozen", [CANONICAL_RUNTIME_POINTER])
        if runtime_identity.get("canonical_main_commit")
        else unknown("the canonical runtime pointer does not record a canonical main commit"))

    # ---- deploy capability classification ---------------------------------- #
    # Capability only. This contract does not evaluate deploy readiness: real
    # readiness would have to combine an approved candidate, TEST_PR, VERIFY,
    # CANARY, Human Approval, a deployment plan, source/package/image binding,
    # the current runtime and the live Command Center switch. None of that is in
    # scope here, so no DEPLOY_READY / can_deploy / eligibility value is produced.
    hold = pointers["hold"]
    deploy_capability = assertion(
        STATE_OBSERVED,
        {"capability": "CAPABILITY_PRESENT_BUT_DISABLED", "request_enabled": False,
         "readiness_evaluation": "NOT_IN_SCOPE"},
        "the DEPLOY capability exists in the repository and its request enablement is fail-closed. "
        "This is a capability classification, not a readiness evaluation, and it must never be read "
        "as one")

    return {
        "schema_version": SCHEMA_VERSION,
        "contract": CONTRACT_STATE,
        "scope": CONTRACT_SCOPE,
        "authority": AUTHORITY,
        "authority_note": ("Derived projection only. The Signed Task is the only Execution "
                           "Authority and the Signed Evidence is the only proof. This document "
                           "never authorizes an operation, and it adds no execution capability."),
        "generated_at": iso(at),
        "freshness": {"stale_after_seconds": stale_seconds,
                      "liveness_window_seconds": liveness_window,
                      "live_verification_window_seconds": verification_window,
                      "stuck_after_seconds": stuck_after,
                      "recent_expired_window_seconds": recent_window},
        "sources": source_identity(options["args"], len(requests)),
        "verification": {
            "task": task_verifier.describe(),
            "evidence": evidence_verifier.describe(),
            "identities_separated": options["identities_separated"],
            "proven_requires_both_keys": True,
            "note": ("A Task must never validate against the evidence key and Evidence must never "
                     "validate against the task key. PROVEN requires the artifact's own identity to "
                     "verify"),
        },
        "counts": {
            "tasks": len(tasks), "evidence": len(loaded.evidence), "requests": len(requests),
            "by_lifecycle": lifecycle_counts(tasks), "anomalies": len(loaded.anomalies),
        },
        "requests": requests,
        "tasks": tasks,
        "request_channel": request_channel,
        "control_state": {
            "health": health_assertion,
            "last_request": (assertion(STATE_OBSERVED, requests[-1]["request_id"],
                                       "the newest Request file observed on a control-bus ref",
                                       [requests[-1]["source"]["path"]])
                             if requests else unknown("no Request file observed on the control bus")),
            "last_task": last_task(),
            "last_evidence": (assertion(
                STATE_PROVEN if newest_evidence["lifecycle"] == "COMPLETE" else STATE_OBSERVED,
                {"task_id": newest_evidence["task_id"],
                 "action_id": newest_evidence["action_id"],
                 "completed_at": newest_evidence["evidence"]["completed_at"]},
                "the newest signed Evidence on the control bus",
                [newest_evidence["evidence"]["source"]["path"]])
                if newest_evidence else unknown("no signed Evidence exists on the control bus")),
            "last_failure": last_failure,
            "hk_agent_last_activity": last_activity,
            "hk_agent_liveness": liveness,
            "hk_runtime_identity": runtime_identity_assertion,
            "verify_status": last_task("HK_STAGING_VERIFY"),
            "test_pr_status": test_pr,
            "deploy_capability": deploy_capability,
            "repository_runtime_pointer": repository_runtime,
            "live_verified_runtime": live_verified,
            "runtime_verification": verification_assertion,
            "runtime_verification_state": live_state,
            "repository_main_sha": repository_main,
            "runtime_built_from_main_sha": runtime_built_from,
            "runtime_canonical_main_sha": runtime_canonical_main,
            "stuck_answer": stuck_answer,
            "active_tasks": [brief(t) for t in active],
            "active_stuck_tasks": [brief(t) for t in active_stuck],
            "recent_expired_tasks": [brief(t) for t in recent_expired],
            "historical_expired_tasks": [brief(t) for t in historical_expired],
            "failed_or_invalid_tasks": [
                {"task_id": t["task_id"], "action_id": t["action_id"], "lifecycle": t["lifecycle"],
                 "reason": t["assertion"]["reason"], "source_path": t["source"]["path"]}
                for t in broken],
            "stale_tasks": [{"task_id": t["task_id"], "action_id": t["action_id"],
                             "completed_at": t["evidence"]["completed_at"]}
                            for t in tasks if t.get("staleness")],
            "last_successful_deploy": (assertion(STATE_OBSERVED, deploys[-1]["task_id"],
                                                 "the newest successful DEPLOY Evidence",
                                                 [deploys[-1]["evidence"]["source"]["path"]])
                                       if deploys else unknown("no successful DEPLOY Evidence")),
            # Informational, non-contract. These are recorded facts read from the
            # canonical pointer and from historical signed Evidence. They are NOT
            # part of CONTROL_STATUS_V1 and they are NOT a readiness evaluation.
            "informational": {
                "contract": False,
                "note": ("recorded facts only. Deploy readiness and rollback readiness are explicitly "
                         "out of scope for this contract"),
                "rollback_candidate_history": rollback,
                "release_gates": hold or {"hk_deploy": "UNKNOWN", "final_release": "UNKNOWN",
                                          "production": "UNKNOWN"},
                "final_release_gate": assertion(
                    STATE_HOLD if hold.get("final_release") == "HOLD" else STATE_UNKNOWN,
                    hold.get("final_release"),
                    "release acceptance is a separate axis from the business runtime and the Control "
                    "Plane"),
                "hk_deploy_gate": assertion(
                    STATE_HOLD if hold.get("hk_deploy") == "HOLD" else STATE_UNKNOWN,
                    hold.get("hk_deploy"),
                    "deployment authorization is not derived from the existence of a DEPLOY "
                    "capability, and this contract does not evaluate deployment readiness"),
                "production": assertion(
                    STATE_HOLD if hold.get("production") in ("HOLD", "UNTOUCHED_HOLD")
                    else STATE_UNKNOWN,
                    hold.get("production"),
                    "Production has not been touched and is out of scope for the Control Plane"),
            },
            "out_of_scope": {
                "deploy_readiness_evaluation": "NOT_IN_SCOPE",
                "rollback_readiness_evaluation": "NOT_IN_SCOPE",
                "note": ("deploy readiness would have to combine an approved candidate, TEST_PR, "
                         "VERIFY, CANARY, Human Approval, a deployment plan, source/package/image "
                         "binding, the current runtime and the live Command Center switch. Rollback "
                         "readiness would have to combine a signed source DEPLOY task, its Evidence "
                         "and Human Approval. Neither is implemented or claimed here"),
            },
        },
        "anomalies": loaded.anomalies,
        "rebuild": {
            "deterministic": True,
            "pin_generated_at": "pass --now <ISO8601> to make the byte output reproducible",
            "command": ("python control-plane/command-center-state-v1/state_projection.py "
                        "--tasks-repo <go-control-tasks> --evidence-repo <go-control-evidence> "
                        "--requests-dir <collected-requests> --go-repo <GO> "
                        "--task-verify-key <cc-task.pub> --evidence-verify-key <hk-evidence.pub> "
                        "--tasks-head <sha> --evidence-head <sha> --go-head <sha> "
                        "--repository-main-sha <sha> --now <ISO8601> --out <dir>"),
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

    pr_index = {}
    for task in tasks:
        if task["action_id"] != "HK_STAGING_TEST_PR" or not task.get("evidence"):
            continue
        source = task["parameters"]["source"]
        pr_index.setdefault(source["pr_number"], []).append({
            "task_id": task["task_id"],
            "commit_sha": source["commit_sha"],
            "lifecycle": task["lifecycle"],
            "result": task["evidence"].get("executor_result"),
            "built_image_id": task["evidence"].get("built_image_id"),
            "completed_at": task["evidence"]["completed_at"],
            "signature_verified": task["evidence"].get("signature_verified"),
            "state": task["assertion"]["state"],
            "source_path": task["evidence"]["source"]["path"],
        })
    pending_test_pr = [{"task_id": t["task_id"], "pr_number": t["parameters"]["source"]["pr_number"],
                        "lifecycle": t["lifecycle"], "state": t["assertion"]["state"],
                        "issued_at": t["issued_at"], "expires_at": t["expires_at"]}
                       for t in tasks
                       if t["action_id"] == "HK_STAGING_TEST_PR" and not t.get("evidence")]

    answers = {
        # ---- the ten status questions, and nothing that implies more ------- #
        # 1  HK Agent 最近是否有活动
        "hk_agent_recent_activity": cs["hk_agent_last_activity"],
        # 2  当前有没有正在执行的任务
        "active_tasks": {"state": STATE_OBSERVED, "value": len(cs["active_tasks"]),
                         "reason": "tasks published and still inside their validity window",
                         "evidence": [t["source_path"] for t in cs["active_tasks"]],
                         "tasks": cs["active_tasks"]},
        # 3  最近任务是否完成
        "last_task": cs["last_task"],
        # 4 + 5  PR X 是否已经 TEST_PR / 结果是什么
        "pr_tested": {"latest": cs["test_pr_status"], "by_pr_number": pr_index,
                      "in_flight": pending_test_pr,
                      "note": "look up by_pr_number for 'has PR N been TEST_PR tested?'"},
        # 6  最近一次 VERIFY 是否成功
        "verify": cs["verify_status"],
        # 7  repository-declared runtime
        "repository_declared_runtime": cs["repository_runtime_pointer"],
        # 8  该 runtime 最近是否被 live VERIFY 证明
        "runtime_verification": cs["runtime_verification"],
        # 9  当前是否存在 active stuck task
        "stuck_tasks": {
            "answer": cs["stuck_answer"],
            "active_stuck_tasks": cs["active_stuck_tasks"],
            "recent_expired_tasks": cs["recent_expired_tasks"],
            "historical_expired_tasks": cs["historical_expired_tasks"],
            "default_lookup": "active_stuck_tasks",
            "note": ("'is anything stuck right now' is answered only from active_stuck_tasks. "
                     "Expired history is indexed separately and never affects current health"),
        },
        # 10 最近一次失败是什么
        "last_failure": cs["last_failure"],
        # Which actions chat may currently create a Request for.
        "request_channel": state["request_channel"],
        # ---- supporting fields, not part of the required answer set -------- #
        "last_evidence": cs["last_evidence"],
        "live_verified_runtime": cs["live_verified_runtime"],
        "go_is_healthy": verdict,
        "hk_agent_online": cs["hk_agent_liveness"],
        "repository_main_sha": cs["repository_main_sha"],
        "runtime_built_from_main_sha": cs["runtime_built_from_main_sha"],
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "contract": CONTRACT_STATUS,
        "scope": CONTRACT_SCOPE,
        "audience": "CHATGPT_CONNECTOR / HUMAN_OPERATOR",
        "authority": AUTHORITY,
        "generated_at": state["generated_at"],
        "freshness": state["freshness"],
        "sources": state["sources"],
        "verification": state["verification"],
        "answers": answers,
        "limits": {
            "read_contract_only": ("This is a bounded read contract. It is not Execution Authority, "
                                   "it never contains an execution parameter, and it can neither "
                                   "create nor sign a Task"),
            "unobservable_by_this_projection": [
                "the live Command Center channel switch and the approved deployment plan store",
                "the Hong Kong agent ledger (attempts, failures, nonce claims)",
                "runtime process state on HK-STAGING",
                "the current repository main revision, unless it is passed in explicitly",
            ],
            "never_infer": ("last successful task != agent online; repository pointer != live "
                            "runtime; capability present != request enabled"),
        },
        "out_of_scope": {
            "deploy_readiness_evaluation": "NOT_IN_SCOPE",
            "rollback_readiness_evaluation": "NOT_IN_SCOPE",
            "note": ("this contract answers the ten status questions and the request channel only. It "
                     "does not compute can_deploy, deployment eligibility, rollback target selection "
                     "or release-gate verdicts, and no such key is present in answers"),
        },
        "verdict": {"healthy": verdict},
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
    parser.add_argument("--task-verify-key",
                        help="pinned Command Center task-manifest public key (hex-signature identity)")
    parser.add_argument("--evidence-verify-key",
                        help="pinned Hong Kong evidence public key (base64-signature identity)")
    parser.add_argument("--tasks-head", default=None, help="pinned commit SHA of the tasks source")
    parser.add_argument("--tasks-ref", default="main")
    parser.add_argument("--evidence-head", default=None, help="pinned commit SHA of the evidence source")
    parser.add_argument("--evidence-ref", default="permission-test")
    parser.add_argument("--go-head", default=None, help="pinned commit SHA of the GO source")
    parser.add_argument("--go-ref", default="main")
    parser.add_argument("--repository-main-sha",
                        help="current repository main revision, if it has been established out of band")
    parser.add_argument("--out", required=True, help="output directory (created if absent)")
    parser.add_argument("--now", help="ISO 8601 instant to project at (default: current UTC)")
    parser.add_argument("--stale-after-seconds", type=int, default=86400)
    parser.add_argument("--liveness-window-seconds", type=int, default=1800)
    parser.add_argument("--live-verification-window-seconds", type=int, default=86400)
    parser.add_argument("--stuck-after-seconds", type=int, default=900)
    parser.add_argument("--recent-expired-window-seconds", type=int, default=604800)
    parser.add_argument("--stdout", action="store_true", help="also print CONTROL_STATUS_V1")
    args = parser.parse_args(argv)

    at = parse_time(args.now) if args.now else now_utc().replace(microsecond=0)
    loaded = Loaded()
    load_tasks(args.tasks_repo, loaded)
    load_evidence(args.evidence_repo, loaded)
    load_requests(args.requests_dir, loaded)

    task_verifier = Verifier(args.task_verify_key, TASK_VERIFIER_IDENTITY, "hex")
    evidence_verifier = Verifier(args.evidence_verify_key, EVIDENCE_VERIFIER_IDENTITY, "base64")
    identities_separated = separated(task_verifier, evidence_verifier, loaded)
    if not identities_separated:
        task_verifier = task_verifier.disabled_copy()
        evidence_verifier = evidence_verifier.disabled_copy()

    options = {
        "stale_seconds": args.stale_after_seconds,
        "liveness_window": args.liveness_window_seconds,
        "verification_window": args.live_verification_window_seconds,
        "stuck_after": args.stuck_after_seconds,
        "recent_window": args.recent_expired_window_seconds,
        "go_repo": args.go_repo,
        "repository_main_sha": args.repository_main_sha,
        "identities_separated": identities_separated,
        "args": args,
    }
    state = build_state(loaded, task_verifier, evidence_verifier, at, options)
    status = build_status(state, verdict_for(state["control_state"]))

    # Portability guard: the derived documents must never carry a workstation
    # path, a user directory or a temp directory.
    leaked = sorted(set(LOCAL_PATH_RE.findall(
        json.dumps(state, sort_keys=True) + json.dumps(status, sort_keys=True))))
    if leaked:
        loaded.anomaly("LOCAL_PATH_LEAK",
                       "derived output contains machine-specific path fragments: %s" % leaked)
        state["anomalies"] = loaded.anomalies
        state["counts"]["anomalies"] = len(loaded.anomalies)

    index = {
        "schema_version": SCHEMA_VERSION,
        "contract": "TASK_INDEX",
        "scope": CONTRACT_SCOPE,
        "authority": AUTHORITY,
        "generated_at": state["generated_at"],
        "entries": [{
            "task_id": t["task_id"], "action_id": t["action_id"], "lifecycle": t["lifecycle"],
            "issued_at": t["issued_at"], "expires_at": t["expires_at"],
            "task_sha256": t["task_sha256"], "source_path": t["source"]["path"],
            "task_signature_verified": t["task_signature_verified"],
            "evidence_state": (t.get("evidence") or {}).get("status", "NO_EVIDENCE_PUBLISHED"),
            "evidence_path": (t.get("evidence") or {}).get("source", {}).get("path"),
            "evidence_sha256": (t.get("evidence") or {}).get("evidence_sha256"),
            "evidence_signature_verified": (t.get("evidence") or {}).get("signature_verified"),
            "assertion_state": t["assertion"]["state"],
        } for t in state["tasks"]],
    }
    latest = {
        "schema_version": SCHEMA_VERSION,
        "contract": "LATEST_EVIDENCE",
        "scope": CONTRACT_SCOPE,
        "authority": AUTHORITY,
        "generated_at": state["generated_at"],
        "by_action": {},
    }
    for task in sorted((t for t in state["tasks"] if t.get("evidence")),
                       key=lambda t: t["evidence"]["completed_at"]):
        latest["by_action"][task["action_id"]] = {
            "task_id": task["task_id"], "completed_at": task["evidence"]["completed_at"],
            "path": task["evidence"]["source"]["path"], "sha256": task["evidence"]["evidence_sha256"],
            "status": task["evidence"]["status"], "lifecycle": task["lifecycle"],
            "signature_verified": task["evidence"]["signature_verified"],
        }

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, payload in (("CURRENT_CONTROL_STATE.json", state),
                          ("CONTROL_STATUS_V1.json", status),
                          ("TASK_INDEX.json", index),
                          ("LATEST_EVIDENCE.json", latest)):
        (out / name).write_bytes(
            json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n")

    summary = {
        "contract": CONTRACT_STATUS, "scope": CONTRACT_SCOPE,
        "generated_at": state["generated_at"],
        "tasks": state["counts"]["tasks"], "evidence": state["counts"]["evidence"],
        "requests": state["counts"]["requests"],
        "by_lifecycle": state["counts"]["by_lifecycle"],
        "task_signature_verification": state["verification"]["task"]["signature_verification"],
        "evidence_signature_verification": state["verification"]["evidence"]["signature_verification"],
        "identities_separated": identities_separated,
        "hk_agent_liveness": status["answers"]["hk_agent_online"]["state"],
        "runtime_verification": state["control_state"]["runtime_verification_state"],
        "active_stuck_tasks": len(state["control_state"]["active_stuck_tasks"]),
        "enabled_request_actions": request_channel_list(state),
        "anomalies": [a["kind"] for a in state["anomalies"]],
        "out": str(out),
    }
    print(json.dumps(summary, sort_keys=True))
    if args.stdout:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0


def request_channel_list(state):
    return state["request_channel"]["enabled_request_actions"]


if __name__ == "__main__":
    sys.exit(main())
