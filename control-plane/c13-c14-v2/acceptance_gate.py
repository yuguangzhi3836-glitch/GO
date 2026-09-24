"""Source-only C13-first / isolated-HK-C14 admission rules.

The Command Center host supplies verified source and evidence facts. This module
derives bounded decisions; it cannot sign, dispatch, or execute a task.
"""
from __future__ import annotations

import re
from typing import Protocol

HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
C13_ACTION = "GO_C13_FIRST_ACCEPTANCE"
C14_ACTION = "HK_ISOLATED_C14_RETEST"
C13_ENVIRONMENT = "GO-ISOLATED-ACCEPTANCE-01"
C14_ENVIRONMENT = "HK-ISOLATED-ACCEPTANCE-01"


class Refusal(ValueError):
    pass


class Host(Protocol):
    def authorize_candidate(self, candidate_sha: str, application_tree: str) -> bool: ...
    def qualify_actor(self, role: str, candidate_sha: str) -> dict: ...
    def verify_c13_evidence(self, reference: str) -> dict: ...


def _source(request: dict, fields: set[str], host: Host) -> tuple[str, str]:
    if type(request) is not dict or set(request) != fields:
        raise Refusal("request_fields")
    sha, tree = request["candidate_sha"], request["application_tree"]
    if not isinstance(sha, str) or not HEX40.fullmatch(sha) or not isinstance(tree, str) or not HEX40.fullmatch(tree):
        raise Refusal("source_format")
    if host.authorize_candidate(sha, tree) is not True:
        raise Refusal("source_not_authorized")
    return sha, tree


def _runner(host: Host, role: str, sha: str, environment: str) -> str:
    actor = host.qualify_actor(role, sha)
    if type(actor) is not dict or set(actor) != {"id", "role", "environment", "independent_of", "registered"}:
        raise Refusal("actor_schema")
    separated = {"implementation"} if role == "C13" else {"implementation", "c13"}
    if (not isinstance(actor["independent_of"], list) or
            any(not isinstance(value, str) for value in actor["independent_of"])):
        raise Refusal("actor_not_qualified")
    if (actor["registered"] is not True or actor["role"] != role or
            actor["environment"] != environment or not isinstance(actor["id"], str) or
            not actor["id"] or
            not separated.issubset(set(actor["independent_of"]))):
        raise Refusal("actor_not_qualified")
    return actor["id"]


def c13_admission(request: dict, host: Host) -> dict:
    """Admit a first formal test, never assert that it passed."""
    sha, tree = _source(request, {"candidate_sha", "application_tree", "test_scope_sha256"}, host)
    digest = request["test_scope_sha256"]
    if not isinstance(digest, str) or not HEX64.fullmatch(digest):
        raise Refusal("test_scope_digest")
    runner = _runner(host, "C13", sha, C13_ENVIRONMENT)
    return {"action_id": C13_ACTION, "environment": C13_ENVIRONMENT, "runner_id": runner,
            "candidate_sha": sha, "application_tree": tree, "test_scope_sha256": digest,
            "network": "disabled", "providers": "disabled", "payments": "disabled",
            "deployment": "disabled", "production": "disabled"}


def c14_admission(request: dict, host: Host) -> dict:
    """Admit an HK isolated retest only after a verified C13 PASS for the same scope."""
    sha, tree = _source(request, {"candidate_sha", "application_tree", "test_scope_sha256", "c13_evidence_reference"}, host)
    digest, ref = request["test_scope_sha256"], request["c13_evidence_reference"]
    if not isinstance(digest, str) or not HEX64.fullmatch(digest):
        raise Refusal("test_scope_digest")
    if not isinstance(ref, str) or not ref:
        raise Refusal("c13_reference")
    evidence = host.verify_c13_evidence(ref)
    required = {"candidate_sha", "application_tree", "test_scope_sha256", "verdict", "actor_id", "verified", "evidence_sha256"}
    if type(evidence) is not dict or set(evidence) != required:
        raise Refusal("c13_evidence_schema")
    if evidence["verified"] is not True or evidence["verdict"] != "PASS_SCOPED" or not isinstance(evidence["actor_id"], str) or not evidence["actor_id"]:
        raise Refusal("c13_not_passed")
    if (evidence["candidate_sha"], evidence["application_tree"], evidence["test_scope_sha256"]) != (sha, tree, digest):
        raise Refusal("c13_binding")
    if not isinstance(evidence["evidence_sha256"], str) or not HEX64.fullmatch(evidence["evidence_sha256"]):
        raise Refusal("c13_evidence_digest")
    runner = _runner(host, "C14", sha, C14_ENVIRONMENT)
    if runner == evidence["actor_id"]:
        raise Refusal("same_acceptance_actor")
    return {"action_id": C14_ACTION, "environment": C14_ENVIRONMENT, "runner_id": runner,
            "candidate_sha": sha, "application_tree": tree, "test_scope_sha256": digest,
            "c13_evidence_sha256": evidence["evidence_sha256"], "network": "disabled",
            "providers": "disabled", "payments": "disabled", "deployment": "disabled", "production": "disabled"}
