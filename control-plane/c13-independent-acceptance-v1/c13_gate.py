"""Draft-only, fail-closed C13 independent-acceptance contract.

This module creates no installation, signing, dispatch, deployment, provider,
payment, secret, Hong Kong, Final Release, or Production capability.
"""
from __future__ import annotations

import hashlib
import json

ACTION = "GO_C13_INDEPENDENT_ACCEPTANCE"
ENVIRONMENT = "GO-ISOLATED-ACCEPTANCE-01"
FIXED_CANDIDATE_SHA = "0c3da07bc32009dee16c69125111f8e4ea9d546b"
FIXED_APPLICATION_TREE = "9206696542000e020601f14233c339cfec6b364c"
FIXED_C14_RECEIPT_ID = "5740342803"
HOST_RUNNER_REGISTRY = {
    "isolated-c13-01": {
        "qualification": "C13_INDEPENDENT",
        "environment": ENVIRONMENT,
        "independence_attested_for": frozenset({"implementation", "c14"}),
    }
}


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
    binding = (request["candidate_sha"], request["application_tree"], request["c14_receipt_id"])
    if binding != (FIXED_CANDIDATE_SHA, FIXED_APPLICATION_TREE, FIXED_C14_RECEIPT_ID):
        raise Refusal("source_binding_not_authorized")
    return request


def registered_runner_id() -> str:
    matching = [runner_id for runner_id, record in HOST_RUNNER_REGISTRY.items()
                if record["qualification"] == "C13_INDEPENDENT"
                and record["environment"] == ENVIRONMENT
                and {"implementation", "c14"}.issubset(record["independence_attested_for"])]
    if len(matching) != 1:
        raise Refusal("runner_not_qualified")
    return matching[0]


def derive_task(request: dict) -> dict:
    validate_request(request)
    runner_id = registered_runner_id()
    binding = {"candidate_sha": FIXED_CANDIDATE_SHA,
               "application_tree": FIXED_APPLICATION_TREE,
               "c14_receipt_id": FIXED_C14_RECEIPT_ID}
    task_id = "go-c13-" + hashlib.sha256(canonical(binding)).hexdigest()[:20]
    return {"schema_version": "1", "task_id": task_id, "action_id": ACTION,
            "environment": ENVIRONMENT, "runner_id": runner_id,
            "parameters": {"source": binding, "profile": "frozen-tests-isolated-postgres-v1",
                           "network": "disabled", "providers": "disabled", "payments": "disabled",
                           "deployment": "disabled", "production": "disabled"}}
