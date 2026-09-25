"""Restricted C14 runner core; host supplies a registered isolated executor.

This source has no signing key, host shell access, Git transport, or deployment
capability. The HK host must install and attest the sandbox implementation.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from acceptance_gate import C14_ACTION, C14_ENVIRONMENT, Refusal
from c13_attestation import CANDIDATE, TREE, SCOPE
from house_bridge import canonical, digest, iso, frozen_junit_counts
from evidence_time import utc_epoch

SCOPE_COMMANDS = (
    "pytest -q tests/payments/test_c11_flight_idempotency_recovery.py tests/test_depth48_flight_changes.py",
    "python -B ci/next_depth/c11_postgres.py --evidence-dir $RUNNER_TEMP/go-c13-flight",
)
assert digest(canonical(list(SCOPE_COMMANDS))) == SCOPE
PARAM_FIELDS = {"candidate_sha", "application_tree", "test_scope_sha256", "runner_id", "c13_evidence_sha256"}
SANDBOX_FIELDS = {"candidate_sha", "application_tree", "test_scope_sha256", "postgres_version",
                  "network", "providers", "payments", "deployment", "production", "junit", "stdout"}


def execute(task: dict, epoch: int, host) -> dict:
    """Consume one verified Task and return only a signed C14 evidence record.

    ``run_fixed_isolated_suite`` must implement an offline source checkout and
    disposable PostgreSQL 18.4 sandbox. Its implementation and host policy are
    still installation prerequisites, never supplied by the Request caller.
    """
    if type(task) is not dict or set(task) != {"schema_version", "task_id", "nonce", "issued_at", "expires_at",
                                          "authority", "environment", "action_id", "parameters", "signature"}:
        raise Refusal("runner_task_schema")
    p = task["parameters"]
    if (task["schema_version"] != "1" or task["authority"] != "GO-COMMAND-CENTER" or
            task["action_id"] != C14_ACTION or task["environment"] != C14_ENVIRONMENT or
            type(p) is not dict or set(p) != PARAM_FIELDS or
            (p["candidate_sha"], p["application_tree"], p["test_scope_sha256"]) !=
            (CANDIDATE, TREE, SCOPE) or p["runner_id"] != host.registered_runner_id() or
            not isinstance(p["c13_evidence_sha256"], str) or
            not re.fullmatch(r"[0-9a-f]{64}", p["c13_evidence_sha256"])):
        raise Refusal("runner_scope")
    if (type(epoch) is not int or host.verify_house_task(canonical({k: v for k, v in task.items() if k != "signature"}),
                                                         task["signature"]) is not True or
            host.read_house_task(task["task_id"]) != canonical(task) + b"\n" or
            not host.task_is_fresh(task, epoch)):
        raise Refusal("runner_task_authority")
    issued = utc_epoch(task["issued_at"], "runner_task_time")
    expires = utc_epoch(task["expires_at"], "runner_task_time")
    if issued < 0 or expires - issued != 900 or not issued <= epoch <= expires:
        raise Refusal("runner_task_time")
    # Require an installed host clock before consuming the one-use claim.
    if not callable(getattr(host, "now_epoch", None)):
        raise Refusal("runner_clock_unavailable")
    # Persistent, single-use claim before any sandbox work; a retry is refused.
    if host.claim_task_once(task["task_id"], task["nonce"]) is not True:
        raise Refusal("runner_replay")
    run = host.run_fixed_isolated_suite(CANDIDATE, TREE, SCOPE_COMMANDS)
    completed_epoch = host.now_epoch()
    if type(completed_epoch) is not int or not epoch <= completed_epoch <= epoch + 3600:
        raise Refusal("runner_completion_time")
    if type(run) is not dict or set(run) != SANDBOX_FIELDS:
        raise Refusal("runner_sandbox_report")
    if ((run["candidate_sha"], run["application_tree"], run["test_scope_sha256"]) !=
            (CANDIDATE, TREE, SCOPE) or run["postgres_version"] != "18.4" or
            any(run[name] is not False for name in ("network", "providers", "payments", "deployment", "production"))):
        raise Refusal("runner_isolation")
    junit, stdout = run["junit"], run["stdout"]
    if type(junit) is not bytes or not 0 < len(junit) <= 8_000_000 or type(stdout) is not bytes or len(stdout) > 2_000_000:
        raise Refusal("runner_raw_artifacts")
    counts = frozen_junit_counts(junit)
    verdict = "PASS_SCOPED" if counts[1:] == [0, 0, 0] else "FAIL"
    manifest = {"task_id": task["task_id"], "nonce": task["nonce"],
                "candidate_sha": CANDIDATE, "application_tree": TREE,
                "test_scope_sha256": SCOPE, "runner_id": p["runner_id"],
                "junit_sha256": digest(junit), "stdout_sha256": digest(stdout),
                "command": "registered frozen flight suite + isolated PostgreSQL 18.4"}
    blobs = {"junit": junit, "stdout": stdout, "manifest": canonical(manifest)}
    result = {**p, "verdict": verdict, "test_count": counts[0],
              "failure_count": counts[1], "error_count": counts[2], "skipped_count": counts[3],
              **{name + "_sha256": digest(blob) for name, blob in blobs.items()}}
    unsigned = {"schema_version": "1", "task_id": task["task_id"], "nonce": task["nonce"],
                "action_id": C14_ACTION, "environment": C14_ENVIRONMENT,
                "status": "SUCCESS" if verdict == "PASS_SCOPED" else "FAILED",
                "started_at": iso(epoch), "completed_at": iso(completed_epoch),
                "agent_version": host.agent_version(), "executor_version": host.runner_version(),
                "executor_result": result, "gate_results": {"isolated_acceptance": verdict},
                "retry_permitted": False, "replay_authorized": False,
                "authorizes_any_action": False}
    signature = host.sign_acceptance_evidence(canonical(unsigned))
    if not isinstance(signature, str) or not signature or host.verify_acceptance_runner(
            p["runner_id"], canonical(unsigned), signature) is not True:
        raise Refusal("runner_signature")
    evidence = {**unsigned, "signature": signature}
    for name, blob in blobs.items():
        host.publish_house_artifact(task["task_id"], task["nonce"], name, blob)
    host.publish_house_evidence(task["task_id"], task["nonce"], canonical(evidence) + b"\n")
    return evidence
