"""C13/C14 review transport: the C14 -> C13 sealed round, carried by the Persistent Runtime.

What this is
------------
The Runtime already knows how to run one task through GitHub and back exactly once. What
C13/C14 needed was not a second scheduler - it was *transport identity*: a deterministic
name for each review run, so an ambiguous dispatch is resolved by lookup instead of by a
second POST, and a durable record of what is in flight, so a restart resumes instead of
re-paying.

So this module adds no review logic at all. Everything about *what* a C13/C14 review is -
the rule sources, the verdicts, the prerequisite gate, the sealed bundle and its root, the
round decision - stays in `control-plane/c13-c14-lite/**`, and this module calls those
validators rather than re-deriving any of it. What it owns is the ONE thing Lite does not
have: the mapping between a Lite round and a Runtime execution, and the fact that the C13
half of a round is created from the C14 half and never on its own.

The one ordering that matters
-----------------------------
C14 runs FIRST. C13 is created only when a C14 sealed verdict admits it, and the C13
Runtime task is enqueued BEFORE the C14 Runtime task is completed - see
`c1_result_pull.complete_after_pull`'s `on_result_sealed`. The Runtime's own idempotency
key is the transaction coordinator: a crash in that window is repaired by re-running the
same deterministic enqueue and getting the same C13 task back.

Delivery is not a verdict
-------------------------
`accepted` on the sealed envelope means "the review execution was delivered correctly",
and that is what the Runtime records. `review_verdict` is what the Cell decided. A C14
`FAIL` completes its Runtime task perfectly well and creates no C13 task; only a transport
failure, an unsealed bundle or a broken identity makes the execution itself fail.
"""
from __future__ import annotations

import importlib
import json
import os
import sys

from c1_execution_contract import (
    C13_REVIEW_KIND,
    C14_REVIEW_KIND,
    PROVIDER_GHAW_BUILDER,
    REVIEW_ROUND_DECISION_REJECT,
    REVIEW_ROUND_DECISIONS,
    REVIEW_KINDS,
    REVIEW_OWNER_C,
    REVIEW_RESULT_KIND,
    REVIEW_ROUND_DECISION_MEMBER,
    REVIEW_SEALED_BUNDLE_MEMBER,
    Refused,
    build_review_task_payload,
    c14_admits_c13,
    canonical,
    review_artifact_name,
    sha256_hex,
    task_idempotency_key,
    validate_review_result,
)

# Where the Lite package is installed on the Runtime Host. Configuration, not a caller
# input, and overridable so the same code can be exercised against a checkout.
LITE_SOURCE_DIR_ENV = "C13C14_LITE_SOURCE_DIR"
DEFAULT_LITE_SOURCE_DIR = "/opt/go/c13c14-lite"

# The C13 machine-test inventory used when a round does not name one. Deliberately NOT the
# whole application test tree: a focused inventory is what makes the C13 half cheap enough
# to run per round, and a round that wants a different scope says so.
DEFAULT_MACHINE_INVENTORY = "application/tests"

_LITE_CACHE: dict = {}


def lite(name: str, *, source_dir=None):
    """Import one Lite module from the installed package.

    Deliberately a function and not a module-level import: the Lite package is installed
    at a configured path on the host, and a missing installation must surface as a clear
    refusal at the call site rather than as an import error at process start.
    """
    directory = source_dir or os.environ.get(LITE_SOURCE_DIR_ENV) or DEFAULT_LITE_SOURCE_DIR
    key = (directory, name)
    if key in _LITE_CACHE:
        return _LITE_CACHE[key]
    if directory not in sys.path:
        sys.path.insert(0, directory)
    try:
        module = importlib.import_module(name)
    except ImportError:
        raise Refused("C13C14_LITE_PACKAGE_NOT_INSTALLED:%s" % directory) from None
    _LITE_CACHE[key] = module
    return module


def _parse_json_bytes(raw: bytes, what: str):
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Refused("REVIEW_ARTIFACT_NOT_VALID_JSON:" + what) from None


def validate_review_payload_for_request(request) -> dict:
    task_kind = request.get("task_kind")
    if task_kind not in REVIEW_KINDS:
        raise Refused("REVIEW_PAYLOAD_ON_A_NON_REVIEW_TASK")
    source = request["payload"]
    return build_review_task_payload(
        cell_id=source["cell_id"],
        external_task_id=source["external_task_id"],
        candidate_sha=source["candidate_sha"],
        application_tree=source["application_tree"],
        issue_number=source["issue_number"],
        review_request_id=source["review_request_id"],
        ledger_round_id=source["ledger_round_id"],
        c14_task_id=source["c14_task_id"],
        c13_task_id=source["c13_task_id"],
        machine_inventory=source.get("machine_inventory"),
        ai_model=source.get("ai_model"),
        c14_run_id=source.get("c14_run_id"),
        c14_runtime_task_id=source.get("c14_runtime_task_id"),
        allowed_owner_cs=(REVIEW_OWNER_C[task_kind],),
    )


def verify_sealed_bundle(raw: bytes, task_kind: str, *, source_dir=None) -> dict:
    """Check a sealed review bundle with the Lite validators - never re-implemented here."""
    bundle_module = lite("lite_bundle", source_dir=source_dir)
    errors = lite("lite_errors", source_dir=source_dir)
    document = _parse_json_bytes(raw, REVIEW_SEALED_BUNDLE_MEMBER[task_kind])
    expected_cell = REVIEW_OWNER_C[task_kind]
    if not isinstance(document, dict) or document.get("cell_id") != expected_cell:
        raise Refused("REVIEW_BUNDLE_IS_NOT_THIS_CELLS:%s" % expected_cell)
    try:
        bundle_module.validate(document)
        bundle_module.verify_root(document)
    except errors.Reject as rejection:
        # Tampered, unbound or structurally invalid: never a verdict, always a refusal.
        raise Refused("REVIEW_BUNDLE_REJECTED:" + rejection.reason) from None
    return document


def _require_bundle_matches_payload(bundle, payload) -> None:
    """The sealed bundle must be about exactly the round the payload names.

    The bundle is already self-consistent - Lite proved that. This is the other half: the
    task that was dispatched and the record that came back must be the same task.
    """
    for field in ("candidate_sha", "application_tree", "task_id"):
        if bundle[field] != payload[field if field != "task_id" else "external_task_id"]:
            raise Refused("REVIEW_BUNDLE_%s_MISMATCH" % field.upper())
    if bundle["issue_number"] is not None and bundle["issue_number"] != payload["issue_number"]:
        raise Refused("REVIEW_BUNDLE_ISSUE_NUMBER_MISMATCH")


def review_artifact_members(task_kind: str) -> tuple:
    """The named files this class's artifact must contain. Not "whatever is in the zip"."""
    members = [REVIEW_SEALED_BUNDLE_MEMBER[task_kind]]
    if task_kind == C13_REVIEW_KIND:
        members.append(REVIEW_ROUND_DECISION_MEMBER)
    return tuple(members)


def _require_round_decision(raw: bytes, *, verdict: str) -> dict:
    """The C13 artifact's own round decision, validated as the consequence of the verdict.

    The round decision is DERIVED evidence, and a negative one is not a defect. The Lite
    chain decides `BLOCK` for a C13 that is not `PASS_SCOPED` - that is exactly what
    `--allow-incomplete` records instead of turning a FAIL into a workflow failure - so
    "the round was not accepted" and "the review was not delivered" are two different
    facts, and this function must not merge them.

    What it checks is what the transport is entitled to check:

      * it is an object the Lite chain could have produced, and it authorises nothing;
      * `REJECT` IS a refusal: the Lite chain raises it only for tampered, unbound or
        identity-conflicting evidence, so there is no trustworthy round to adopt;
      * `ACCEPT` may only accompany `PASS_SCOPED` - an accepted round over a failing C13
        is a contradiction, not a delivery;
      * `BLOCK` is recorded and is a delivered review. When the C13 verdict is not
        `PASS_SCOPED` it is the correct consequence, so the Runtime task succeeds with
        the verdict recorded and nothing is authorised.

    This is not a second rule set: it is the three-line consequence of the gates
    `lite_chain.verify_round` already applies, and the test suite proves the mapping by
    running the REAL chain for PASS_SCOPED / FAIL / BLOCKED.
    """
    document = _parse_json_bytes(raw, REVIEW_ROUND_DECISION_MEMBER)
    if not isinstance(document, dict):
        raise Refused("REVIEW_ROUND_DECISION_NOT_AN_OBJECT")
    if document.get("authorizes_any_action") is not False:
        raise Refused("REVIEW_ROUND_DECISION_MUST_NOT_AUTHORIZE_ANY_ACTION")
    decision = document.get("decision")
    if decision not in REVIEW_ROUND_DECISIONS:
        raise Refused("REVIEW_ROUND_DECISION_UNKNOWN")
    if decision == REVIEW_ROUND_DECISION_REJECT:
        raise Refused("REVIEW_ROUND_DECISION_REJECTED:%s"
                      % ",".join(str(item.get("reason"))
                                 for item in (document.get("rejects") or [])))
    if decision == "ACCEPT" and verdict != "PASS_SCOPED":
        raise Refused("REVIEW_ROUND_ACCEPTED_WITH_A_NON_PASS_C13:%s" % verdict)
    return document


def _require_c13_follows_the_c14_this_runtime_delivered(c13_bundle, payload, outbox,
                                                        request_id, *, source_dir=None) -> dict:
    """Cross-check the C13 half against the C14 record this Runtime actually received.

    Three independent things must line up, and none of them can be produced from the C13
    side alone:

      * the C13 bundle's own prerequisite stanza must name the C14 root that the sealed
        C14 envelope this Runtime recorded actually has - so a C13 bundle can only have
        been sealed over a C14 record that really ran;
      * the C14 execution the C13 round names must be the one this Runtime delivered,
        identified by its run id and its verdict; and
      * the two runs must be different runs - two cells, two fresh executions.
    """
    errors = lite("lite_errors", source_dir=source_dir)
    earlier = outbox.terminal_for_task(payload["c14_runtime_task_id"],
                                       exclude_request_id=request_id)
    if earlier is None:
        raise Refused("REVIEW_C13_WITHOUT_A_COMPLETED_C14_TASK")
    c14_envelope = earlier["result"]
    if not isinstance(c14_envelope, dict) or \
            c14_envelope.get("kind") != REVIEW_RESULT_KIND or \
            c14_envelope.get("owner_c") != REVIEW_OWNER_C[C14_REVIEW_KIND]:
        raise Refused("REVIEW_C13_PREDECESSOR_IS_NOT_A_C14_REVIEW")
    if c14_envelope.get("github_run_id") != payload["c14_run_id"]:
        raise Refused("REVIEW_C13_NAMES_A_DIFFERENT_C14_RUN")
    if c14_envelope.get("review_verdict") not in errors.C14_PREREQUISITE_OK:
        raise Refused("REVIEW_C13_ADMITTED_BY_A_NON_ADMISSIBLE_C14")
    prerequisite = c13_bundle["c14_prerequisite"]
    if prerequisite["c14_root"] != c14_envelope["sealed_bundle_root"]:
        raise Refused("REVIEW_C13_PREREQUISITE_ROOT_IS_NOT_THE_SEALED_C14_ROOT")
    if prerequisite["c14_candidate_sha"] != payload["candidate_sha"]:
        raise Refused("REVIEW_C13_PREREQUISITE_IS_FOR_ANOTHER_CANDIDATE")
    return c14_envelope


def review_artifact_loader(outbox, *, source_dir=None):
    """A `pull_result` artifact loader for the review classes.

    It fetches the Lite workflow's own bundle artifact by the name that workflow already
    publishes, takes the NAMED members out of it, verifies the sealed bundle with the Lite
    validators, applies the half-round cross-checks, and returns the Runtime transport
    envelope as the bytes `pull_result` expects. One extra read of the run is made so the
    envelope can carry the run attempt - the same fact the Lite readback records.
    """

    def load(client, run_id, request):
        task_kind = request.get("task_kind")
        if task_kind not in REVIEW_KINDS:
            raise Refused("REVIEW_ARTIFACT_LOADER_ON_A_NON_REVIEW_TASK")
        payload = validate_review_payload_for_request(request)
        name = review_artifact_name(task_kind, payload["candidate_sha"])
        got = client.download_artifact_members(run_id, name, review_artifact_members(task_kind))
        if got is None:
            return None
        members = got["members"]
        digests = got["digests"]
        bundle_raw = members[REVIEW_SEALED_BUNDLE_MEMBER[task_kind]]
        bundle = verify_sealed_bundle(bundle_raw, task_kind, source_dir=source_dir)
        _require_bundle_matches_payload(bundle, payload)
        # Only the C13 half publishes a round decision; the C14 half has no round yet.
        round_decision = None
        if task_kind == C13_REVIEW_KIND:
            round_decision = _require_round_decision(
                members[REVIEW_ROUND_DECISION_MEMBER], verdict=bundle["verdict"])
            _require_c13_follows_the_c14_this_runtime_delivered(
                bundle, payload, outbox, request["execution_request_id"],
                source_dir=source_dir)

        run = client.get_run(run_id) or {}
        envelope = {
            "version": 1,
            "kind": REVIEW_RESULT_KIND,
            "owner_c": REVIEW_OWNER_C[task_kind],
            "runtime_task_id": request["runtime_task_id"],
            "attempt": request["attempt"],
            "execution_request_id": request["execution_request_id"],
            "github_run_id": run_id,
            "github_run_attempt": run.get("run_attempt", 1) or 1,
            "provider": PROVIDER_GHAW_BUILDER,
            "review_verdict": bundle["verdict"],
            "deployment_eligible": False,
            "accepted": True,
            "authorizes_any_action": False,
            "candidate_sha": payload["candidate_sha"],
            "application_tree": payload["application_tree"],
            "issue_number": payload["issue_number"],
            "review_request_id": payload["review_request_id"],
            "ledger_round_id": payload["ledger_round_id"],
            "sealed_bundle_root": bundle["C14_ROOT" if task_kind == C14_REVIEW_KIND
                                       else "C13_ROOT"],
            "sealed_bundle_sha256": sha256_hex(bundle_raw.decode("utf-8")),
            "artifacts": {member: digest.split("sha256:")[-1]
                          for member, digest in digests.items()},
            "status": "SUCCEEDED",
            # Derived evidence, carried verbatim so the round's own conclusion is
            # auditable. It is deliberately NOT reduced to "eligible": one half of a
            # round never establishes eligibility, and it never authorises anything.
            "round_decision": round_decision,
        }
        body = canonical(envelope)
        return {"bytes": body.encode("utf-8"),
                "digest": "sha256:" + sha256_hex(body),
                "github_run_id": run_id}

    return load


def make_result_validator(outbox, *, source_dir=None):
    """The validator injected into the outbox for a review execution.

    The composite the requirement asks for: the Runtime's own envelope contract
    (`validate_review_result`, which binds the identity and forbids authorisation) PLUS the
    Lite chain's admissibility, re-checked against the bytes this Runtime actually holds.
    Nothing is taken on trust and no review rule is restated.
    """

    def validate(document, *, runtime_task_id, attempt, execution_request_id_, task_kind):
        validate_review_result(document, runtime_task_id=runtime_task_id, attempt=attempt,
                               execution_request_id_=execution_request_id_,
                               task_kind=task_kind)
        request = outbox.stored_request(runtime_task_id, attempt)
        if request is None:
            raise Refused("REVIEW_RESULT_WITHOUT_A_STORED_REQUEST")
        payload = validate_review_payload_for_request(request)
        for name in ("candidate_sha", "application_tree", "issue_number"):
            if document[name] != payload[name]:
                raise Refused("REVIEW_RESULT_%s_MISMATCH" % name.upper())
        if document["review_request_id"] != payload["review_request_id"]:
            raise Refused("REVIEW_RESULT_REQUEST_ID_MISMATCH")
        if document["ledger_round_id"] != payload["ledger_round_id"]:
            raise Refused("REVIEW_RESULT_LEDGER_ROUND_MISMATCH")
        if document["github_run_id"] == payload.get("c14_run_id"):
            raise Refused("REVIEW_C13_RUN_IS_THE_C14_RUN")
        return document

    return validate


def c13_payload_from_c14(c14_payload: dict, c14_envelope: dict) -> dict:
    """The C13 half of a round, derived from the C14 half and nothing else.

    Every identity is carried from the C14 task - the frozen candidate, the round, the
    ledger task ids - so the two halves cannot describe two different rounds. The only new
    facts are the C14 execution the C13 round follows.
    """
    return build_review_task_payload(
        cell_id="C13",
        external_task_id=c14_payload["c13_task_id"],
        candidate_sha=c14_payload["candidate_sha"],
        application_tree=c14_payload["application_tree"],
        issue_number=c14_payload["issue_number"],
        review_request_id=c14_payload["review_request_id"],
        ledger_round_id=c14_payload["ledger_round_id"],
        c14_task_id=c14_payload["c14_task_id"],
        c13_task_id=c14_payload["c13_task_id"],
        machine_inventory=c14_payload.get("machine_inventory") or DEFAULT_MACHINE_INVENTORY,
        ai_model=c14_payload.get("ai_model"),
        c14_run_id=c14_envelope["github_run_id"],
        c14_runtime_task_id=c14_envelope["runtime_task_id"],
        allowed_owner_cs=(REVIEW_OWNER_C[C13_REVIEW_KIND],),
    )


def enqueue_c13_when_c14_admits(document, binding, outbox, runtime) -> dict | None:
    """The `on_result_sealed` hook: turn an admissible sealed C14 into a C13 task.

    Runs BETWEEN the seal and `Runtime.complete(C14)`, which is the whole point - see
    `complete_after_pull`. It is idempotent by construction: the C13 idempotency key is
    derived from the C13 cell and its Lite task id, both carried from the C14 payload, so
    re-running this after a crash returns the same C13 Runtime task instead of creating a
    second one - and a second one would be a second paid review.
    """
    if document.get("kind") != REVIEW_RESULT_KIND:
        return None
    if binding["owner_c"] != REVIEW_OWNER_C[C14_REVIEW_KIND]:
        # Only the C14 half creates the C13 half. A C13 execution is terminal by itself.
        return None
    verdict = document["review_verdict"]
    if not c14_admits_c13(verdict):
        # A negative C14 is a complete result, not a delivery failure: the C14 Runtime task
        # completes with its verdict recorded, and no C13 task is created.
        return {"c13_enqueued": False, "c14_verdict": verdict,
                "reason": "C14_VERDICT_DOES_NOT_ADMIT_C13"}
    request = outbox.stored_request(binding["runtime_task_id"], binding["expected_attempt"])
    if request is None:
        raise Refused("C14_RESULT_WITHOUT_A_STORED_REQUEST")
    payload = c13_payload_from_c14(request["payload"], document)
    key = task_idempotency_key(C13_REVIEW_KIND, payload["cell_id"],
                               payload["external_task_id"])
    task_id = runtime.enqueue(payload["cell_id"], C13_REVIEW_KIND, payload,
                              idempotency_key=key, max_attempts=1)
    return {"c13_enqueued": True, "c13_runtime_task_id": task_id,
            "c13_idempotency_key": key, "c14_verdict": verdict}
