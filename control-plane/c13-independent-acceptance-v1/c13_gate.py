"""Draft-only C13 task derivation with host-bound trust verification.

This module cannot install a Runner or validate a receipt by itself.  Both facts
must be verified by a separately operated, immutable host trust boundary.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Protocol

ACTION = "GO_C13_INDEPENDENT_ACCEPTANCE"
ENVIRONMENT = "GO-ISOLATED-ACCEPTANCE-01"
FIXED_CANDIDATE_SHA = "0c3da07bc32009dee16c69125111f8e4ea9d546b"
FIXED_APPLICATION_TREE = "f6d329352dd8484010036448810a927d5eec4be7"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")


class Refusal(ValueError):
    pass


class HostTrustBoundary(Protocol):
    """Implemented outside this PR by the reviewed host control plane."""

    def verify_c14_receipt(self, receipt_reference: str, binding: dict) -> dict: ...

    def select_independent_runner(self, binding: dict) -> dict: ...


class UnconfiguredHostTrustBoundary:
    """Safe default: a source checkout has no authority to restore a Runner."""

    def verify_c14_receipt(self, receipt_reference: str, binding: dict) -> dict:
        raise Refusal("host_trust_boundary_unconfigured")

    def select_independent_runner(self, binding: dict) -> dict:
        raise Refusal("host_trust_boundary_unconfigured")


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def validate_request(request: dict) -> dict:
    allowed = {"schema_version", "action_id", "candidate_sha", "application_tree", "c14_receipt_reference"}
    if set(request) != allowed:
        raise Refusal("schema_fields")
    if request["schema_version"] != "1" or request["action_id"] != ACTION:
        raise Refusal("action_not_enabled_in_channel")
    if not _HEX40.fullmatch(request["candidate_sha"]) or not _HEX40.fullmatch(request["application_tree"]):
        raise Refusal("source_identity_format")
    if not isinstance(request["c14_receipt_reference"], str) or not request["c14_receipt_reference"]:
        raise Refusal("receipt_reference_format")
    if (request["candidate_sha"], request["application_tree"]) != (FIXED_CANDIDATE_SHA, FIXED_APPLICATION_TREE):
        raise Refusal("source_binding_not_authorized")
    return request


def _binding(request: dict) -> dict:
    return {"candidate_sha": request["candidate_sha"], "application_tree": request["application_tree"]}


def _verified_receipt(host: HostTrustBoundary, request: dict, binding: dict) -> dict:
    receipt = host.verify_c14_receipt(request["c14_receipt_reference"], binding)
    required = {"issuer", "verdict", "candidate_sha", "application_tree", "digest", "signature_verified"}
    if not isinstance(receipt, dict) or not required.issubset(receipt):
        raise Refusal("receipt_schema")
    if receipt["signature_verified"] is not True or receipt["verdict"] != "PASS":
        raise Refusal("receipt_not_signed_pass")
    if not isinstance(receipt["issuer"], str) or not receipt["issuer"]:
        raise Refusal("receipt_issuer")
    if not isinstance(receipt["digest"], str) or not re.fullmatch(r"[0-9a-f]{64}", receipt["digest"]):
        raise Refusal("receipt_digest")
    if (receipt["candidate_sha"], receipt["application_tree"]) != (binding["candidate_sha"], binding["application_tree"]):
        raise Refusal("receipt_binding")
    return receipt


def _qualified_runner(host: HostTrustBoundary, binding: dict) -> dict:
    runner = host.select_independent_runner(binding)
    required = {"runner_id", "qualification", "environment", "independent_of", "registration_verified"}
    if not isinstance(runner, dict) or not required.issubset(runner):
        raise Refusal("runner_schema")
    if runner["registration_verified"] is not True or runner["qualification"] != "C13_INDEPENDENT":
        raise Refusal("runner_not_qualified")
    if runner["environment"] != ENVIRONMENT or not isinstance(runner["runner_id"], str) or not runner["runner_id"]:
        raise Refusal("runner_environment")
    if not {"implementation", "c14"}.issubset(set(runner["independent_of"])):
        raise Refusal("runner_not_independent")
    return runner


def derive_task(request: dict, host: HostTrustBoundary = UnconfiguredHostTrustBoundary()) -> dict:
    validate_request(request)
    binding = _binding(request)
    receipt = _verified_receipt(host, request, binding)
    runner = _qualified_runner(host, binding)
    task_id = "go-c13-" + hashlib.sha256(canonical({"binding": binding, "receipt_digest": receipt["digest"]})).hexdigest()[:20]
    return {"schema_version": "1", "task_id": task_id, "action_id": ACTION,
            "environment": ENVIRONMENT, "runner_id": runner["runner_id"],
            "parameters": {"source": binding, "c14_receipt": {"issuer": receipt["issuer"], "digest": receipt["digest"]},
                           "profile": "frozen-tests-isolated-postgres-v1", "network": "disabled",
                           "providers": "disabled", "payments": "disabled", "deployment": "disabled", "production": "disabled"}}
