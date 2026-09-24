"""Draft house-task adapter. No keys, git transport or executor in this module.

Only a trusted Command Center host can implement the signing and bus methods.
The acceptance actions require separately installed contract and runners.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import xml.etree.ElementTree as ET

from acceptance_gate import (C13_ACTION, C14_ACTION, C13_ENVIRONMENT,
                             C14_ENVIRONMENT, Refusal, c13_admission, c14_admission)

HEX64 = re.compile(r"[0-9a-f]{64}\Z")
TASK_FIELDS = {"schema_version", "task_id", "nonce", "issued_at", "expires_at",
               "authority", "environment", "action_id", "parameters", "signature"}
COMMON = {"candidate_sha", "application_tree", "test_scope_sha256", "runner_id"}
RESULT = COMMON | {"verdict", "junit_sha256", "stdout_sha256", "manifest_sha256",
                   "test_count", "failure_count", "error_count", "skipped_count"}
EVIDENCE_FIELDS = {"schema_version", "task_id", "nonce", "action_id", "environment",
                   "status", "started_at", "completed_at", "agent_version",
                   "executor_version", "executor_result", "gate_results", "signature",
                   "retry_permitted", "replay_authorized", "authorizes_any_action"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def iso(epoch):
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _params(admission):
    pair = (admission.get("action_id"), admission.get("environment"))
    if pair not in ((C13_ACTION, C13_ENVIRONMENT), (C14_ACTION, C14_ENVIRONMENT)):
        raise Refusal("acceptance_action_environment")
    expected = COMMON | (set() if pair[0] == C13_ACTION else {"c13_evidence_sha256"})
    if type(admission) is not dict or set(admission) != expected | {
            "action_id", "environment", "network", "providers", "payments", "deployment", "production"}:
        raise Refusal("admission_schema")
    if any(admission[k] != "disabled" for k in ("network", "providers", "payments", "deployment", "production")):
        raise Refusal("capability")
    if pair[0] == C14_ACTION and not HEX64.fullmatch(admission["c13_evidence_sha256"]):
        raise Refusal("c13_prerequisite")
    return {k: admission[k] for k in expected}


def _task_identity(admission):
    return "go-" + ("c13" if admission["action_id"] == C13_ACTION else "c14") + "-acceptance-" + digest(
        canonical({"action_id": admission["action_id"], "environment": admission["environment"],
                   "parameters": _params(admission)}))[:32]


def issue(request, role, epoch, host):
    """Use the installed house envelope, never any deployment action or argument."""
    if role not in ("C13", "C14"):
        raise Refusal("role")
    admission = c13_admission(request, host) if role == "C13" else c14_admission(request, host)
    params = _params(admission)
    if role == "C14" and host.verify_c13_prerequisite(admission) is not True:
        raise Refusal("c13_prerequisite")
    if type(epoch) is not int or epoch < 0:
        raise Refusal("task_time")
    nonce = host.fresh_nonce()
    if not isinstance(nonce, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", nonce):
        raise Refusal("nonce")
    unsigned = {"schema_version": "1", "task_id": _task_identity(admission),
                "nonce": nonce, "issued_at": iso(epoch), "expires_at": iso(epoch + 900),
                "authority": "GO-COMMAND-CENTER", "environment": admission["environment"],
                "action_id": admission["action_id"], "parameters": params}
    signature = host.sign_house_task(canonical(unsigned))
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{128}", signature):
        raise Refusal("task_signature")
    if host.verify_house_task(canonical(unsigned), signature) is not True:
        raise Refusal("task_signature")
    signed = {**unsigned, "signature": signature}
    # The host must atomically refuse any existing task ID and publish exact bytes.
    host.publish_house_task(signed["task_id"], canonical(signed) + b"\n")
    raw = host.read_house_task(signed["task_id"])
    if type(raw) is not bytes or raw != canonical(signed) + b"\n":
        raise Refusal("task_readback")
    return signed


def read_evidence(task, epoch, host):
    """Read the actual signed bus object and its three raw artifacts."""
    if type(task) is not dict or set(task) != TASK_FIELDS:
        raise Refusal("task_schema")
    unsigned = {k: v for k, v in task.items() if k != "signature"}
    if (task["authority"] != "GO-COMMAND-CENTER" or task["schema_version"] != "1" or
            (task["action_id"], task["environment"]) not in
            ((C13_ACTION, C13_ENVIRONMENT), (C14_ACTION, C14_ENVIRONMENT))):
        raise Refusal("task_schema")
    if host.verify_house_task(canonical(unsigned), task["signature"]) is not True:
        raise Refusal("task_signature")
    if host.read_house_task(task["task_id"]) != canonical(task) + b"\n":
        raise Refusal("task_readback")
    try:
        issued = dt.datetime.fromisoformat(task["issued_at"].replace("Z", "+00:00")).timestamp()
        expires = dt.datetime.fromisoformat(task["expires_at"].replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, OverflowError) as exc:
        raise Refusal("task_time") from exc
    if type(epoch) is not int or expires - issued != 900:
        raise Refusal("task_time")
    raw = host.read_house_evidence(task["task_id"], task["nonce"])
    if type(raw) is not bytes or len(raw) > 256_000:
        raise Refusal("evidence_bytes")
    try:
        evidence = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Refusal("evidence_json") from exc
    if type(evidence) is not dict or set(evidence) != EVIDENCE_FIELDS:
        raise Refusal("evidence_schema")
    if (evidence["schema_version"] != "1" or any(evidence[k] != task[k] for k in
            ("task_id", "nonce", "action_id", "environment")) or
            evidence["status"] not in ("SUCCESS", "FAILED", "REJECTED") or
            any(evidence[k] is not False for k in
                ("retry_permitted", "replay_authorized", "authorizes_any_action"))):
        raise Refusal("evidence_task_binding")
    if host.verify_acceptance_runner(task["parameters"]["runner_id"],
            canonical({k: v for k, v in evidence.items() if k != "signature"}),
            evidence["signature"]) is not True:
        raise Refusal("evidence_signature")
    try:
        started = dt.datetime.fromisoformat(evidence["started_at"].replace("Z", "+00:00")).timestamp()
        completed = dt.datetime.fromisoformat(evidence["completed_at"].replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, OverflowError) as exc:
        raise Refusal("evidence_time") from exc
    if not issued <= started <= expires or not started <= completed <= started + 3600:
        raise Refusal("evidence_time")
    result = evidence["executor_result"]
    fields = RESULT | ({"c13_evidence_sha256"} if task["action_id"] == C14_ACTION else set())
    if type(result) is not dict or set(result) != fields:
        raise Refusal("result_schema")
    if any(result[k] != task["parameters"][k] for k in fields & set(task["parameters"])):
        raise Refusal("result_source_binding")
    if type(evidence["gate_results"]) is not dict or set(evidence["gate_results"]) != {"isolated_acceptance"}:
        raise Refusal("gate_results")
    artifacts = {}
    for name, limit in (("junit", 8_000_000), ("stdout", 2_000_000), ("manifest", 64_000)):
        content = host.read_house_artifact(task["task_id"], task["nonce"], name)
        if (type(content) is not bytes or len(content) > limit or
                not isinstance(result[name + "_sha256"], str) or
                not HEX64.fullmatch(result[name + "_sha256"]) or
                digest(content) != result[name + "_sha256"]):
            raise Refusal("artifact_integrity")
        artifacts[name] = content
    try:
        manifest = json.loads(artifacts["manifest"])
        root = ET.fromstring(artifacts["junit"])
        suites = [root] if root.tag == "testsuite" else list(root) if root.tag == "testsuites" else []
        counts = [sum(int(s.attrib.get(key, "0")) for s in suites)
                  for key in ("tests", "failures", "errors", "skipped")]
    except (UnicodeError, json.JSONDecodeError, ET.ParseError, ValueError, TypeError) as exc:
        raise Refusal("artifact_parse") from exc
    if not suites or any(s.tag != "testsuite" for s in suites):
        raise Refusal("junit_schema")
    required = {"task_id", "nonce", "candidate_sha", "application_tree", "test_scope_sha256",
                "runner_id", "junit_sha256", "stdout_sha256", "command"}
    if (type(manifest) is not dict or set(manifest) != required or
            not isinstance(manifest["command"], str) or not manifest["command"] or
            any(manifest[k] != task["parameters"].get(k, task.get(k)) for k in
                ("task_id", "nonce", "candidate_sha", "application_tree", "test_scope_sha256", "runner_id")) or
            any(manifest[k] != result[k] for k in ("junit_sha256", "stdout_sha256"))):
        raise Refusal("manifest_binding")
    if (any(type(result[k]) is not int or result[k] < 0 for k in
            ("test_count", "failure_count", "error_count", "skipped_count")) or
            counts != [result[k] for k in ("test_count", "failure_count", "error_count", "skipped_count")]):
        raise Refusal("junit_counts")
    if (result["verdict"] == "PASS_SCOPED" and
            (evidence["status"] != "SUCCESS" or counts[0] == 0 or any(counts[1:]) or
             evidence["gate_results"]["isolated_acceptance"] != "PASS_SCOPED")):
        raise Refusal("pass_without_tests")
    if result["verdict"] not in ("PASS_SCOPED", "FAIL", "BLOCKED"):
        raise Refusal("verdict")
    return result
