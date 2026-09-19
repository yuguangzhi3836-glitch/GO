"""Fail-closed, C13-only independent acceptance contract.

This module is deliberately offline: it creates no deployment, provider, payment,
secret, Hong Kong, or production capability.  A host-side signer and registered
isolated runner must supply the signed task/evidence envelopes.
"""
from __future__ import annotations

import hashlib
import json

ACTION = "GO_C13_INDEPENDENT_ACCEPTANCE"
ENVIRONMENT = "GO-ISOLATED-ACCEPTANCE-01"
REQUIRED = {"candidate_sha", "application_tree", "c14_receipt_id"}
FORBIDDEN = {"command", "argv", "image", "service", "path", "env", "secret", "payment", "provider", "hong_kong", "production", "deploy"}


class Refusal(ValueError):
    pass


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def validate_request(request: dict) -> dict:
    allowed = {"schema_version", "action_id", "candidate_sha", "application_tree", "c14_receipt_id"}
    if set(request) != allowed:
        raise Refusal("schema_fields")
    if request["schema_version"] != "1" or request["action_id"] != ACTION:
        raise Refusal("action_not_enabled_in_channel")
    if not REQUIRED.issubset(request) or any(not isinstance(request[k], str) for k in REQUIRED):
        raise Refusal("invalid_source_binding")
    if any(k in request for k in FORBIDDEN):
        raise Refusal("caller_controlled_execution")
    if len(request["candidate_sha"]) != 40 or len(request["application_tree"]) != 40:
        raise Refusal("invalid_source_binding")
    if not request["c14_receipt_id"].isdigit():
        raise Refusal("invalid_c14_receipt")
    return request


def derive_task(request: dict, runner: dict) -> dict:
    validate_request(request)
    # Runner identity is registry-owned; callers cannot select or alter it.
    expected = {"runner_id", "qualification", "environment", "independence_attested_for"}
    if set(runner) != expected or runner["qualification"] != "C13_INDEPENDENT" or runner["environment"] != ENVIRONMENT:
        raise Refusal("runner_not_qualified")
    required_independence = {"implementation", "c14"}
    if not required_independence.issubset(set(runner["independence_attested_for"])):
        raise Refusal("runner_not_independent")
    binding = {k: request[k] for k in REQUIRED}
    task_id = "go-c13-" + hashlib.sha256(canonical(binding)).hexdigest()[:20]
    return {"schema_version": "1", "task_id": task_id, "action_id": ACTION,
            "environment": ENVIRONMENT, "runner_id": runner["runner_id"],
            "parameters": {"source": binding, "profile": "frozen-tests-isolated-postgres-v1",
                           "network": "disabled", "providers": "disabled", "payments": "disabled",
                           "deployment": "disabled", "production": "disabled"}}
