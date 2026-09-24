"""Fail-closed task and evidence boundary for C13-first acceptance.

The host owns signing keys, durable storage, runner identity and artifact bytes.
This module has no transport, keys, shell, network or deployment capability.
"""
from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from typing import Protocol

from acceptance_gate import (C13_ACTION, C14_ACTION, C13_ENVIRONMENT,
                             C14_ENVIRONMENT, Refusal)

HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
TASK_FIELDS = {"task_id", "action_id", "environment", "runner_id", "candidate_sha",
               "application_tree", "test_scope_sha256", "issued_at", "expires_at",
               "network", "providers", "payments", "deployment", "production"}
EVIDENCE_FIELDS = {"task_id", "action_id", "environment", "runner_id", "candidate_sha",
                   "application_tree", "test_scope_sha256", "verdict", "junit_sha256",
                   "stdout_sha256", "manifest_sha256", "test_count", "failure_count",
                   "error_count", "skipped_count"}
ARTIFACT_NAMES = ("junit", "stdout", "manifest")
MANIFEST_FIELDS = {"task_id", "action_id", "environment", "runner_id", "candidate_sha",
                   "application_tree", "test_scope_sha256", "junit_sha256", "stdout_sha256", "command"}


class Host(Protocol):
    def sign_task(self, canonical_bytes: bytes) -> str: ...
    def verify_task_signature(self, canonical_bytes: bytes, signature: str) -> bool: ...
    def publish_task(self, task_id: str, envelope: dict) -> None: ...
    def read_task(self, task_id: str) -> dict: ...
    def read_evidence(self, task_id: str) -> dict: ...
    def verify_runner_signature(self, runner_id: str, canonical_bytes: bytes, signature: str) -> bool: ...
    def read_artifact(self, task_id: str, name: str) -> bytes: ...


def canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _shape(value: object, fields: set[str], reason: str) -> dict:
    if type(value) is not dict or set(value) != fields:
        raise Refusal(reason)
    return value


def _envelope(value: object, fields: set[str], reason: str) -> tuple[dict, str]:
    item = _shape(value, {"payload", "signature"}, reason)
    payload = _shape(item["payload"], fields, reason)
    if not isinstance(item["signature"], str) or not item["signature"]:
        raise Refusal(reason)
    return payload, item["signature"]


def _bound(payload: dict, admission: dict) -> None:
    for key in ("action_id", "environment", "runner_id", "candidate_sha",
                "application_tree", "test_scope_sha256"):
        if payload.get(key) != admission.get(key):
            raise Refusal("source_or_scope_mismatch")
    if (not isinstance(payload["candidate_sha"], str) or
            not HEX40.fullmatch(payload["candidate_sha"]) or
            not isinstance(payload["application_tree"], str) or
            not HEX40.fullmatch(payload["application_tree"]) or
            not isinstance(payload["test_scope_sha256"], str) or
            not HEX64.fullmatch(payload["test_scope_sha256"])):
        raise Refusal("source_format")


def _task(payload: dict, admission: dict) -> None:
    _bound(payload, admission)
    pair = (payload["action_id"], payload["environment"])
    if pair not in ((C13_ACTION, C13_ENVIRONMENT), (C14_ACTION, C14_ENVIRONMENT)):
        raise Refusal("action_environment")
    if set(payload) != TASK_FIELDS | ({"c13_evidence_sha256"} if pair[0] == C14_ACTION else set()):
        raise Refusal("task_schema")
    if pair[0] == C14_ACTION and (payload["c13_evidence_sha256"] != admission.get("c13_evidence_sha256") or
            not isinstance(payload["c13_evidence_sha256"], str) or
            not HEX64.fullmatch(payload["c13_evidence_sha256"])):
        raise Refusal("c13_prerequisite")
    for key in ("network", "providers", "payments", "deployment", "production"):
        if payload[key] != "disabled" or admission.get(key) != "disabled":
            raise Refusal("capability")
    if not isinstance(payload["runner_id"], str) or not payload["runner_id"]:
        raise Refusal("runner_id")
    if (not isinstance(payload["task_id"], str) or
            not re.fullmatch(r"go-(c13|c14)-acceptance-[0-9a-f]{32}", payload["task_id"])):
        raise Refusal("task_id")
    prefix = "go-c13-acceptance-" if payload["action_id"] == C13_ACTION else "go-c14-acceptance-"
    identity = {k: payload[k] for k in ("action_id", "environment", "runner_id", "candidate_sha",
                                        "application_tree", "test_scope_sha256")}
    if pair[0] == C14_ACTION:
        identity["c13_evidence_sha256"] = payload["c13_evidence_sha256"]
    if payload["task_id"] != prefix + hashlib.sha256(canonical(identity)).hexdigest()[:32]:
        raise Refusal("task_identity")
    for key in ("issued_at", "expires_at"):
        if type(payload[key]) is not int or payload[key] < 0:
            raise Refusal("task_time")
    if not 0 < payload["expires_at"] - payload["issued_at"] <= 3600:
        raise Refusal("task_time")


def issue_task(admission: dict, now: int, host: Host) -> dict:
    """Publish only a signed, read-back-verified test task; no release action."""
    if type(admission) is not dict or set(admission) not in (TASK_FIELDS - {"task_id", "issued_at", "expires_at"},
            TASK_FIELDS - {"task_id", "issued_at", "expires_at"} | {"c13_evidence_sha256"}):
        raise Refusal("admission_schema")
    if admission["action_id"] == C14_ACTION:
        if (not isinstance(admission.get("c13_evidence_sha256"), str) or
                not HEX64.fullmatch(admission["c13_evidence_sha256"])):
            raise Refusal("c13_prerequisite")
    elif "c13_evidence_sha256" in admission:
        raise Refusal("admission_schema")
    identity = {k: admission[k] for k in ("action_id", "environment", "runner_id", "candidate_sha",
                                          "application_tree", "test_scope_sha256")}
    if admission["action_id"] == C14_ACTION:
        identity["c13_evidence_sha256"] = admission["c13_evidence_sha256"]
    prefix = "go-c13-acceptance-" if admission["action_id"] == C13_ACTION else "go-c14-acceptance-"
    if type(now) is not int:
        raise Refusal("task_time")
    task = {**identity, "task_id": prefix + hashlib.sha256(canonical(identity)).hexdigest()[:32],
            "issued_at": now, "expires_at": now + 1800,
            **{k: "disabled" for k in ("network", "providers", "payments", "deployment", "production")}}
    _task(task, admission)
    signature = host.sign_task(canonical(task))
    if not isinstance(signature, str) or not signature:
        raise Refusal("task_signer_unconfigured")
    envelope = {"payload": task, "signature": signature}
    host.publish_task(task["task_id"], envelope)
    task_fields = TASK_FIELDS | ({"c13_evidence_sha256"} if task["action_id"] == C14_ACTION else set())
    observed, observed_signature = _envelope(host.read_task(task["task_id"]), task_fields, "task_readback")
    _task(observed, admission)
    if observed != task or observed_signature != signature or not host.verify_task_signature(canonical(observed), observed_signature):
        raise Refusal("task_readback")
    return envelope


def read_evidence(task_envelope: dict, admission: dict, now: int, host: Host) -> dict:
    """Accept only signed evidence and exact raw artifacts read from host storage."""
    item = _shape(task_envelope, {"payload", "signature"}, "task_schema")
    task_fields = TASK_FIELDS | ({"c13_evidence_sha256"} if type(item["payload"]) is dict and
                                  item["payload"].get("action_id") == C14_ACTION else set())
    task, signature = _envelope(task_envelope, task_fields, "task_schema")
    _task(task, admission)
    if type(now) is not int or not task["issued_at"] <= now <= task["expires_at"]:
        raise Refusal("task_expired")
    if not host.verify_task_signature(canonical(task), signature):
        raise Refusal("task_signature")
    if host.read_task(task["task_id"]) != task_envelope:
        raise Refusal("task_readback")
    evidence_fields = EVIDENCE_FIELDS | ({"c13_evidence_sha256"} if task["action_id"] == C14_ACTION else set())
    evidence, runner_signature = _envelope(host.read_evidence(task["task_id"]), evidence_fields, "evidence_schema")
    _bound(evidence, admission)
    if any(evidence[k] != task[k] for k in ("task_id", "action_id", "environment", "runner_id")):
        raise Refusal("evidence_task_binding")
    if task["action_id"] == C14_ACTION and evidence["c13_evidence_sha256"] != task["c13_evidence_sha256"]:
        raise Refusal("c13_prerequisite")
    if not host.verify_runner_signature(task["runner_id"], canonical(evidence), runner_signature):
        raise Refusal("evidence_signature")
    artifacts = {}
    for name in ARTIFACT_NAMES:
        raw = host.read_artifact(task["task_id"], name)
        digest = evidence[name + "_sha256"]
        if (type(raw) is not bytes or not isinstance(digest, str) or
                len(raw) > {"junit": 8_000_000, "stdout": 2_000_000, "manifest": 64_000}[name] or
                not HEX64.fullmatch(digest) or hashlib.sha256(raw).hexdigest() != digest):
            raise Refusal("artifact_integrity")
        artifacts[name] = raw
    try:
        manifest = json.loads(artifacts["manifest"])
        _shape(manifest, MANIFEST_FIELDS, "manifest_schema")
        if (not isinstance(manifest["command"], str) or not manifest["command"] or
                any(manifest[k] != evidence[k] for k in MANIFEST_FIELDS - {"command"})):
            raise Refusal("manifest_binding")
        root = ET.fromstring(artifacts["junit"])
        suites = [root] if root.tag == "testsuite" else list(root) if root.tag == "testsuites" else []
        if not suites or any(s.tag != "testsuite" for s in suites):
            raise Refusal("junit_schema")
        counts = {k: sum(int(s.attrib.get(k, "0")) for s in suites)
                  for k in ("tests", "failures", "errors", "skipped")}
    except (UnicodeError, json.JSONDecodeError, ET.ParseError, TypeError, ValueError, OverflowError) as exc:
        if isinstance(exc, Refusal):
            raise
        raise Refusal("artifact_parse") from exc
    if tuple(counts.values()) != tuple(evidence[k] for k in
            ("test_count", "failure_count", "error_count", "skipped_count")):
        raise Refusal("junit_counts")
    if evidence["verdict"] not in ("PASS_SCOPED", "FAIL", "BLOCKED"):
        raise Refusal("verdict")
    for key in ("test_count", "failure_count", "error_count", "skipped_count"):
        if type(evidence[key]) is not int or evidence[key] < 0:
            raise Refusal("test_counts")
    if (evidence["verdict"] == "PASS_SCOPED" and
            (evidence["test_count"] == 0 or any(evidence[k] for k in ("failure_count", "error_count", "skipped_count")))):
        raise Refusal("pass_without_complete_tests")
    return evidence
