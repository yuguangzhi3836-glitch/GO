"""C1 execution contract: the one place the dispatch and result identities are defined.

Both sides of the C1 path import this module, so the Runtime-side requester and the
GitHub-hosted executor can never drift apart about what a given execution *is*:

  Runtime / Agent  ->  c1_dispatch_outbox.py  ->  dispatch request  ->  GitHub workflow
  GitHub workflow  ->  c1_ai_execution_backend.py  ->  sealed result  ->  Runtime

Fixed by configuration, NEVER by task input:
  repository, workflow file, git ref, owner cell, task kind, payload, model endpoint.

Carried by the task (the only things a Runtime task may influence):
  runtime_task_id, attempt.

Derived, never sent by a caller as an independent value:
  execution_request_id = sha256(canonical(task binding + fixed binding))

Nothing here performs I/O, holds a credential, or knows about the Runtime database.
"""
from __future__ import annotations

import hashlib
import json

SCHEMA_VERSION = 1

# ---------------------------------------------------------------- fixed topology
REPO = "yuguangzhi3836-glitch/GO"
WORKFLOW_FILE = "c1-ai-execution-backend-v1.yml"
# The ref a dispatch is sent against. `workflow_dispatch` only triggers when the
# workflow file exists on the DEFAULT branch, so this is not a free choice.
REF = "main"
DISPATCH_ENDPOINT = "/repos/%s/actions/workflows/%s/dispatches" % (REPO, WORKFLOW_FILE)
RUNS_ENDPOINT = "/repos/%s/actions/runs" % REPO

# ---------------------------------------------------------------- fixed task shape
OWNER_C = "C1"
KIND = "AI_WORK_V1"
SMOKE_ID = "C1_REAL_AI_WORKER_V1"
PAYLOAD = {"schema_version": 1, "smoke_id": SMOKE_ID}
IDEMPOTENCY_KEY = "c1-real-ai-worker-v1:smoke:1"
EXPECTED_OUTPUT = "GO_C1_REAL_AI_WORKER_V1_OK"

# Provider identity and endpoint are fixed in the executor, not requested by anyone.
PROVIDER = "OPENAI_RESPONSES_API"
API_URL = "https://api.openai.com/v1/responses"
PROMPT = (
    "This is a bounded infrastructure smoke test. "
    "Reply with exactly GO_C1_REAL_AI_WORKER_V1_OK and nothing else."
)

REQUEST_KIND = "c1-ai-execution-request"
RESULT_KIND = "c1-ai-execution-result"

# The ONLY workflow inputs a dispatch may carry. Everything else is fixed config.
DISPATCH_INPUT_NAMES = ("runtime_task_id", "attempt", "execution_request_id")

# The exact field set of a sealed result. `failure_reason` is allowed only when the
# execution did not succeed; anything else is a refusal, not a warning.
RESULT_FIELDS = frozenset({
    "version", "kind", "runtime_task_id", "attempt", "execution_request_id",
    "github_run_id", "github_run_attempt", "provider", "model", "response_id",
    "status", "output_sha256", "output", "accepted", "reused_terminal_result",
    "authorizes_any_action",
})
RESULT_STATUSES = ("SUCCEEDED", "FAILED")


class Refused(Exception):
    """Fail-closed refusal carrying a stable machine-readable reason code."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def canonical(document) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"))


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prompt_sha256() -> str:
    return sha256_hex(PROMPT)


def output_sha256(output: str) -> str:
    return sha256_hex(output)


def require_runtime_facts(runtime_task_id, attempt) -> tuple:
    if not isinstance(runtime_task_id, str) or not runtime_task_id:
        raise Refused("RUNTIME_TASK_ID_MISSING")
    if type(attempt) is not int or attempt < 1:
        raise Refused("ATTEMPT_NOT_POSITIVE_INT")
    return runtime_task_id, attempt


def task_binding(runtime_task_id, attempt) -> dict:
    runtime_task_id, attempt = require_runtime_facts(runtime_task_id, attempt)
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": REQUEST_KIND,
        "owner_c": OWNER_C,
        "task_kind": KIND,
        "smoke_id": SMOKE_ID,
        "payload": PAYLOAD,
        "idempotency_key": IDEMPOTENCY_KEY,
        "runtime_task_id": runtime_task_id,
        "attempt": attempt,
        "provider": PROVIDER,
        "prompt_sha256": prompt_sha256(),
    }


def execution_request_id(runtime_task_id, attempt) -> str:
    """Deterministic: same task + same attempt => same id, always, on both sides."""
    return sha256_hex(canonical(task_binding(runtime_task_id, attempt)))


def build_dispatch_request(runtime_task_id, attempt) -> dict:
    """The canonical request the Runtime forms before anything is sent anywhere."""
    request = dict(task_binding(runtime_task_id, attempt))
    request["execution_request_id"] = execution_request_id(runtime_task_id, attempt)
    request["repo"] = REPO
    request["workflow_file"] = WORKFLOW_FILE
    request["ref"] = REF
    return request


def dispatch_inputs(request: dict) -> dict:
    """The wire inputs. Exactly the identity triple - no prompt, model or URL."""
    return {
        "runtime_task_id": request["runtime_task_id"],
        "attempt": request["attempt"],
        "execution_request_id": request["execution_request_id"],
    }


def run_identity_name(runtime_task_id, attempt, request_id) -> str:
    """The deterministic run name the workflow sets, used to resolve a run by lookup.

    A dispatch whose HTTP outcome is unknown must be resolved by looking for this
    name, never by sending a second POST.
    """
    return "C1 %s %s %s" % (runtime_task_id, attempt, request_id)


# ------------------------------------------------------------------- result side
def validate_result(document, *, runtime_task_id, attempt, execution_request_id_) -> dict:
    """Validate a sealed result against the exact task identity it claims to belong to.

    Fails closed on: wrong field set, wrong kind/version, wrong task, wrong attempt,
    wrong execution_request_id, inconsistent accepted/status, mismatched output hash.
    """
    if type(document) is not dict:
        raise Refused("RESULT_NOT_AN_OBJECT")
    keys = set(document)
    if not keys >= RESULT_FIELDS:
        raise Refused("RESULT_MISSING_FIELDS")
    extra = keys - RESULT_FIELDS
    if extra:
        if extra != {"failure_reason"} or document.get("accepted") is not False:
            raise Refused("RESULT_UNEXPECTED_FIELDS")
    if document["version"] != SCHEMA_VERSION or document["kind"] != RESULT_KIND:
        raise Refused("RESULT_KIND_OR_VERSION_MISMATCH")
    if document["runtime_task_id"] != runtime_task_id:
        raise Refused("RESULT_TASK_MISMATCH")
    if document["attempt"] != attempt:
        raise Refused("RESULT_ATTEMPT_MISMATCH")
    if document["execution_request_id"] != execution_request_id_:
        raise Refused("RESULT_EXECUTION_REQUEST_ID_MISMATCH")
    if document["status"] not in RESULT_STATUSES:
        raise Refused("RESULT_STATUS_UNKNOWN")
    if type(document["accepted"]) is not bool:
        raise Refused("RESULT_ACCEPTED_NOT_BOOLEAN")
    if document["authorizes_any_action"] is not False:
        raise Refused("RESULT_MUST_NOT_AUTHORIZE_ANY_ACTION")
    expected_status = "SUCCEEDED" if document["accepted"] else "FAILED"
    if document["status"] != expected_status:
        raise Refused("RESULT_STATUS_INCONSISTENT_WITH_ACCEPTED")
    if type(document["github_run_id"]) is not int or document["github_run_id"] <= 0:
        raise Refused("RESULT_GITHUB_RUN_ID_INVALID")
    if type(document["github_run_attempt"]) is not int or document["github_run_attempt"] < 1:
        raise Refused("RESULT_GITHUB_RUN_ATTEMPT_INVALID")
    if document["provider"] != PROVIDER:
        raise Refused("RESULT_PROVIDER_MISMATCH")
    if document["output_sha256"] != output_sha256(document["output"]):
        raise Refused("RESULT_OUTPUT_HASH_MISMATCH")
    if document["accepted"]:
        if document["output"] != EXPECTED_OUTPUT:
            raise Refused("RESULT_ACCEPTED_WITHOUT_THE_EXPECTED_OUTPUT")
        if not document["response_id"]:
            raise Refused("RESULT_MISSING_RESPONSE_ID")
    if not document["accepted"] and "failure_reason" not in document:
        raise Refused("RESULT_FAILED_WITHOUT_A_REASON")
    return document
