"""C1 execution contract: the one place the dispatch and result identities are defined.

Both sides of the C1 path import this module, so the Runtime-side requester and the
GitHub-hosted executor can never drift apart about what a given execution *is*:

  Runtime / Agent  ->  c1_dispatch_outbox.py  ->  dispatch request  ->  GitHub workflow
  GitHub workflow  ->  c1_ai_execution_backend.py  ->  sealed result  ->  Runtime

Fixed by configuration, NEVER by task input:
  repository, workflow file, git ref, model endpoint.

Carried by the task: the task's own payload, plus `runtime_task_id` and `attempt`. For a
task that names its own cell, `owner_c` is carried the same way - as a field of the
payload, canonicalised on the way in - and never chosen by a caller as a free value.

Derived, never sent by a caller as an independent value:
  execution_request_id = sha256(canonical(task binding))

Nothing here performs I/O, holds a credential, or knows about the Runtime database.

--------------------------------------------------------------------- task classes
There are exactly three task classes. They are deliberately separate, and each belongs
to exactly ONE executor:

  SMOKE  kind `AI_WORK_V1`   payload `SMOKE_PAYLOAD`  prompt + accepted output fixed
         The deployed, already-PASS end-to-end smoke. Its binding, its execution
         identity and its acceptance rule are UNCHANGED by this revision: with no
         explicit spec, `task_binding(task, attempt)` still returns the same document
         byte for byte, so the identity the live Runtime Host already recorded for
         `rt_fed1d4626...` attempt 1 still resolves to the same `execution_request_id`.
         That matters: if it changed, an already-answered execution would look like a
         brand new one and a second paid model call would become possible.

  REAL   kind `AI_TASK_V1`   payload = a validated real-task payload  prompt DERIVED
         The first real capability. It carries one real task's execution input, derives
         the prompt from the claimed task's payload, and accepts any well-formed
         non-empty model output instead of one fixed literal. Executed by
         `c1_worker.py` - one OpenAI Responses call per execution. **C1 only**, and it
         stays C1 only: the Responses backend was proven for one cell and this round
         does not widen it.

  REAL   kind `GHAW_BUILDER_V1`  payload = the SAME validated real-task payload
         The same task shape, a different execution: a gh-aw workflow that runs its own
         agent. Owned by `c1_ghaw_builder_worker.py` and by no one else. Its binding
         carries `provider = GITHUB_AGENTIC_WORKFLOWS` instead of the Responses
         endpoint, so the two real classes can never share an execution identity even
         for the same Runtime task and attempt.
         **C1..C12**: one Builder executor serves every normal engineering cell. The
         cell range is not a free parameter - it is `BUILDER_OWNER_CS`, and every gate
         in this channel derives from it.

The classes can never collide: their bindings have different key sets (smoke vs real) or
different kinds and providers (the two real classes), so no payload can derive a binding
belonging to another class. That is what keeps one class's result from being accepted as
another's.

------------------------------------------------------------- canonical cell identity
The deployed kernel's responsibility set is

    C_IDS = tuple(f"C{i}" for i in range(1, 15))        # runtime.py:20

so `owner_c` is `C1`..`C14`. The Owner's own cell names are zero-padded (`C01`..`C14`).
There is exactly ONE canonical internal representation - the kernel's - and exactly one
place where the external spelling is folded into it: `canonical_cell_id()`. Nothing
downstream ever sees both spellings, so no task can acquire two keys.

Knowing a canonical name and being allowed to run it are two different questions. The
kernel has 14 cells; a Builder serves 12 of them. `canonical_cell_id()` therefore still
recognises `C13` and `C14` - refusing them there would break the global parser every
other consumer relies on - and it is the executor's own owner set (`allowed_owner_cs`)
that excludes them. C13 and C14 are the two control-only cells: the workbench's own
`application/src/go_hotel/workbench/definitions.py` marks them `control_only=True`, and
`test_c1_cell_generalization` binds this module's owner set to that definition rather
than letting the two drift apart.

------------------------------------------------------------- real task payload shape
A real payload carries only what executing the AI needs, split by role so that adding a
field later is a conscious decision:

  binding input   schema_version, cell_id, external_task_id
                  Participate in `execution_request_id`; `external_task_id` is also the
                  caller's stable task key and the base of the idempotency key.
  execution input objective, scope
                  What the DERIVED prompt is built from. Nothing else reaches the model.
  trace only      source_anchor, issue_number
                  Recorded in the binding for auditability. NOT in the prompt: the
                  executor may not act on them, and handing them to the model would
                  invite it to reason about provenance it cannot verify.
  refused         candidate_sha, artifact_id, pr_number, c14_verdict, c13_verdict,
                  run_id, github_run_id, execution_request_id, output, output_sha256,
                  result, accepted, status
                  All produced *after* the execution, or by the Runtime itself.
                  Accepting them at enqueue time would let a caller assert a result
                  before one exists, so they are rejected outright.
"""
from __future__ import annotations

import hashlib
import json
import re

SCHEMA_VERSION = 1

# ---------------------------------------------------------------- fixed topology
REPO = "yuguangzhi3836-glitch/GO"
WORKFLOW_FILE = "c1-ai-execution-backend-v1.yml"
# The ref a dispatch is sent against. `workflow_dispatch` only triggers when the
# workflow file exists on the DEFAULT branch, so this is not a free choice.
REF = "main"
DISPATCH_ENDPOINT = "/repos/%s/actions/workflows/%s/dispatches" % (REPO, WORKFLOW_FILE)
RUNS_ENDPOINT = "/repos/%s/actions/runs" % REPO


def dispatch_endpoint(workflow_file: str) -> str:
    """The dispatch URL for one workflow file.

    A workflow file is part of the *transport target*, not part of the execution
    identity: it is added to a request after `execution_request_id` has been hashed, and
    a dispatch that lands on the wrong workflow does not create a different execution -
    it creates the same execution run by the wrong executor. That is why the target has
    to be bound to the executor and checked, rather than being read off the request.
    """
    return "/repos/%s/actions/workflows/%s/dispatches" % (REPO, workflow_file)


def dispatch_endpoint_for_kind(task_kind: str) -> str:
    """The dispatch URL the class's own executor owns. Never chosen by a caller."""
    return dispatch_endpoint(workflow_file_for_kind(task_kind))


# ------------------------------------------------- canonical responsibility identity
# The kernel's own canonical spelling: `C1`, never `C01`.
OWNER_C = "C1"

# The two executor boundaries, stated once. A kind belongs to exactly one executor, and
# the cells that executor may run are part of that boundary rather than a separate rule.
#
#   Responses-API executor : AI_WORK_V1, AI_TASK_V1 -> C1 only      (unchanged)
#   gh-aw Builder executor : GHAW_BUILDER_V1        -> C1..C12
#
# C13 and C14 are the two control-only cells and belong to NEITHER set. They are the
# Independent QA/Release cell and the constitutional/legal/regulatory control cell; the
# workbench definition marks both `control_only=True`, and a Builder is not what either
# of them is. Excluding them here is the first of three independent gates - the worker's
# claim list, this validator, and the workflow's pre-agent gate - so no prompt, typo or
# mis-issued enqueue can turn a Builder into a control-cell executor.
LEGACY_OWNER_CS = (OWNER_C,)
BUILDER_OWNER_CS = tuple("C%d" % index for index in range(1, 13))

# The Owner writes `C01`, `C02`, ... The kernel only knows `C1`, `C2`, ...
_EXTERNAL_PADDED_CELL = re.compile(r"^C0([1-9])$")
_CANONICAL_CELL = re.compile(r"^C([1-9]|1[0-4])$")


class Refused(Exception):
    """Fail-closed refusal carrying a stable machine-readable reason code."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def canonical_cell_id(external) -> str:
    """Fold an external cell spelling onto the kernel's canonical one.

    The ONLY boundary where the two spellings meet, and total: every accepted input maps
    to exactly one canonical value, and the function is idempotent
    (`canonical_cell_id(canonical_cell_id(x)) == canonical_cell_id(x)`), so re-normalising
    can never produce a second key.

        canonical_cell_id("C1")  == "C1"
        canonical_cell_id("C01") == "C1"
        canonical_cell_id("C14") == "C14"

    Anything that is not a real cell refuses rather than being coerced, so a typo cannot
    quietly become a new responsibility domain.
    """
    if not isinstance(external, str):
        raise Refused("CELL_ID_NOT_A_STRING")
    value = external.strip().upper()
    padded = _EXTERNAL_PADDED_CELL.match(value)
    if padded:
        return "C" + padded.group(1)
    if _CANONICAL_CELL.match(value):
        return value
    raise Refused("CELL_ID_NOT_A_KNOWN_RESPONSIBILITY_DOMAIN")


def assert_canonical_cell_id(value) -> str:
    """Refuse a value that is not already canonical.

    For values travelling *inside* the system. An internal caller that passes the
    external spelling trips this instead of silently creating a second identity for the
    same cell - which is the point of having one canonical representation.
    """
    if not isinstance(value, str) or canonical_cell_id(value) != value:
        raise Refused("CELL_ID_NOT_CANONICAL")
    return value


# ---------------------------------------------------------------- smoke task (V1)
KIND = "AI_WORK_V1"
SMOKE_ID = "C1_REAL_AI_WORKER_V1"
SMOKE_PAYLOAD = {"schema_version": 1, "smoke_id": SMOKE_ID}
# Kept under its original name: the workflow, the backend and the tests import it, and
# it still means "the fixed payload of the deployed smoke".
PAYLOAD = SMOKE_PAYLOAD
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

# The ONLY workflow inputs a smoke dispatch may carry. Everything else is fixed config.
DISPATCH_INPUT_NAMES = ("runtime_task_id", "attempt", "execution_request_id")
# A real dispatch additionally carries its kind and payload: the executor runs in a
# different process and a different checkout, so its prompt cannot be re-derived without
# them. It still never carries a model, an endpoint, a ref or a repository.
REAL_DISPATCH_INPUT_NAMES = DISPATCH_INPUT_NAMES + ("task_kind", "task_payload")
# The gh-aw Builder carries its owner cell as well. It is not a free input: it is copied
# from the binding's `owner_c`, which the validator derived from the payload's `cell_id`
# and checked against BUILDER_OWNER_CS. Sending it explicitly is what lets the workflow
# independently check `owner_c == canonical(task_payload.cell_id)` and refuse before the
# agent starts - a second gate that is worth one more wire field, because the two values
# travel by different routes and can therefore disagree if anything upstream is wrong.
# The Responses real class keeps the two-name real set: its backend has no such gate and
# this round does not change it.
GHAW_BUILDER_INPUT_NAMES = REAL_DISPATCH_INPUT_NAMES + ("owner_c",)

# The exact field set of a sealed result. `failure_reason` is allowed only when the
# execution did not succeed; anything else is a refusal, not a warning.
RESULT_FIELDS = frozenset({
    "version", "kind", "runtime_task_id", "attempt", "execution_request_id",
    "github_run_id", "github_run_attempt", "provider", "model", "response_id",
    "status", "output_sha256", "output", "accepted", "reused_terminal_result",
    "authorizes_any_action",
})
RESULT_STATUSES = ("SUCCEEDED", "FAILED")

# ---------------------------------------------------------------- real task (V1)
REAL_TASK_KIND = "AI_TASK_V1"
REAL_PAYLOAD_SCHEMA_VERSION = 1

TASK_CLASS_SMOKE = "SMOKE"
TASK_CLASS_REAL = "REAL"
TASK_CLASS_REVIEW = "REVIEW"

# The role of each real-task payload field, as data rather than as prose.
TASK_PAYLOAD_BINDING_INPUT = ("schema_version", "cell_id", "external_task_id")
TASK_PAYLOAD_EXECUTION_INPUT = ("objective", "scope")
TASK_PAYLOAD_TRACE_ONLY = ("source_anchor", "issue_number")
TASK_PAYLOAD_FIELDS = frozenset(
    TASK_PAYLOAD_BINDING_INPUT + TASK_PAYLOAD_EXECUTION_INPUT + TASK_PAYLOAD_TRACE_ONLY)
TASK_PAYLOAD_REQUIRED = ("schema_version", "cell_id", "external_task_id",
                         "objective", "scope")
# Post-execution facts, or Runtime internals. Never an enqueue input.
TASK_PAYLOAD_REFUSED = frozenset({
    "candidate_sha", "artifact_id", "pr_number", "c14_verdict", "c13_verdict",
    "run_id", "github_run_id", "execution_request_id", "output", "output_sha256",
    "result", "accepted", "status",
})

MAX_EXTERNAL_TASK_ID = 200
MAX_OBJECTIVE = 4000
MAX_SCOPE = 4000
MAX_SOURCE_ANCHOR = 200

# ------------------------------------------------------------- gh-aw Builder (V1)
# The kind the formal gh-aw Builder executor owns, and the ONLY kind it may claim.
#
# Why a separate kind rather than reusing `AI_TASK_V1`: a task kind is what decides
# which executor picks a task up. `Runtime.claim()` filters on kind and hands each
# matching task to whichever worker asks for it, so two executors sharing one kind is
# not a sharing arrangement - it is a race, and the loser is whichever executor was
# restarted. One kind therefore belongs to exactly ONE executor:
#
#     AI_WORK_V1, AI_TASK_V1   -> c1_worker.py               (the Responses-API executor)
#     GHAW_BUILDER_V1          -> c1_ghaw_builder_worker.py  (the gh-aw Builder executor)
#
# Nothing here routes a task; this module only names the kinds. The ownership sets live
# with the executors themselves, and `test_c1_executor_boundary` asserts they are
# disjoint, so neither executor can silently grow into the other's kinds.
#
# It carries the same real-task payload as `AI_TASK_V1` - the objective and the scope are
# what the Builder is asked to work on - so nothing about the task shape is new. What is
# new is that its execution is a different kind of execution: a gh-aw workflow that runs
# its own agent, not a single OpenAI Responses call. That difference is recorded in the
# binding (`provider`), which is why the two classes can never produce the same
# `execution_request_id`.
GHAW_BUILDER_KIND = "GHAW_BUILDER_V1"
PROVIDER_GHAW_BUILDER = "GITHUB_AGENTIC_WORKFLOWS"
# The workflow a gh-aw Builder dispatch is aimed at. DECLARED, NOT REGISTERED: this round
# deliberately adds no workflow file and sends no dispatch (that is U1). It is declared
# here because leaving a task's own recorded dispatch target pointing at the Responses
# backend would be a false record of where that task goes.
GHAW_BUILDER_WORKFLOW_FILE = "c1-gh-aw-builder-v1.lock.yml"

# ------------------------------------------------- C13/C14 review transport (U7B)
# C13 and C14 are the two control-only cells. Their work is not engineering work: a
# review reads a frozen candidate and returns a sealed verdict, with no Draft PR, no
# edit and no test authoring - so it is NOT a GHAW_BUILDER_V1 task and is never routed
# to the Builder executor. It is also not a new kind of *Runtime* work: the kernel is
# unchanged, and these are two more kinds of the SAME Runtime, claimed by ONE special
# review executor (`c1_c13c14_review_worker.py`).
#
# Each kind belongs to exactly one cell, and that cell is a fixed function of the
# kind - not a payload field, not a caller choice. C14 runs FIRST and alone; C13 is
# only ever created after a C14 sealed verdict admits it, which is why the two are
# separate kinds rather than one "REVIEW" kind with a role flag.
#
# The execution backend is the EXISTING Lite workflow for that cell. Adding transport
# identity to them is not adding a workflow: no review logic is reimplemented here and
# no second dispatcher exists.
C14_REVIEW_KIND = "C14_REVIEW_V1"
C13_REVIEW_KIND = "C13_REVIEW_V1"
REVIEW_KINDS = (C14_REVIEW_KIND, C13_REVIEW_KIND)
# kind -> the one cell that kind may belong to. The single definition of the review
# ownership boundary; every gate in this channel reads it.
REVIEW_OWNER_C = {C14_REVIEW_KIND: "C14", C13_REVIEW_KIND: "C13"}
# kind -> the existing Lite workflow that executes it. Fixed config, never a request.
REVIEW_WORKFLOW_FILE = {
    C14_REVIEW_KIND: "c14-rule-compliance.yml",
    C13_REVIEW_KIND: "c13-quality-acceptance.yml",
}
# The single artifact each Cell's workflow publishes alongside its bundle. It is ONE
# name per role, so "which artifact is this class's output" has one answer.
REVIEW_ARTIFACT_PREFIX = {C14_REVIEW_KIND: "c13c14-lite-c14-",
                          C13_REVIEW_KIND: "c13c14-lite-c13-"}
REVIEW_SEALED_BUNDLE_MEMBER = {C14_REVIEW_KIND: "c14_bundle.json",
                               C13_REVIEW_KIND: "c13_bundle.json"}
REVIEW_ROUND_DECISION_MEMBER = "round_decision.json"
# The OPTIONAL wire inputs each Cell's EXISTING workflow declares - the ones this contract
# may put on the request but must not put on every kind's dispatch.
#
# GitHub does not ignore an undeclared `workflow_dispatch` input: it refuses the dispatch
# outright (422), so a live C14 round would never leave the Runtime. The wire set must
# therefore be a SUBSET of what the receiving workflow declares, and that is a fact about
# each Cell's own workflow rather than about the payload - `machine_inventory` is the C13
# machine-test inventory and only the C13 workflow declares it, while `ai_model` is declared
# by both. The payload still carries `machine_inventory` for a C14 round, because that is
# how the C13 half is derived from the C14 half; it simply must not travel to C14.
REVIEW_WIRE_OPTIONAL = {
    C14_REVIEW_KIND: ("ai_model",),
    C13_REVIEW_KIND: ("machine_inventory", "ai_model"),
}


def is_review_kind(task_kind) -> bool:
    return task_kind in REVIEW_KINDS


def review_artifact_name(task_kind: str, candidate_sha: str) -> str:
    """Which artifact of this class's run carries the sealed bundle."""
    if task_kind not in REVIEW_WORKFLOW_FILE:
        raise Refused("TASK_KIND_UNKNOWN")
    return REVIEW_ARTIFACT_PREFIX[task_kind] + candidate_sha


def review_request_id(candidate_sha: str, ledger_round_id: str) -> str:
    """The review round's request id, DERIVED so it is stable and cannot be chosen.

    A review round has two admission paths - the manual `deliver_review_round.py` and the
    formal Review Issue ingress - and they must name the same round the same way. So the
    derivation lives here, once, beside the other identities of this channel, rather than
    being restated by whichever caller happens to need it: two copies would be two answers
    to "which round is this", which is the one thing a round identity may not have.

    It only has to be stable, not chosen - which is why nothing takes it as an argument.
    """
    _require_sha1(candidate_sha, "REVIEW_REQUEST_ID_CANDIDATE_SHA_INVALID")
    return "REV-" + hashlib.sha256(
        ("%s|%s" % (candidate_sha, ledger_round_id)).encode("utf-8")).hexdigest()[:24]


# The round's Ledger/Lite identity, derived from the FROZEN candidate and the issue it came
# from - never from a timestamp, a counter or a random id, because the same candidate
# presented twice must be the same round.
#
# Two paths produce rounds and both derive their identity HERE:
#
#   an Owner's `C14 · REVIEW · ...` issue  -> the issue number is the provenance
#   a Builder run that just opened a PR    -> the Builder's OWN originating issue number
#
# The second is why this is a function of the issue number rather than of "the review
# issue": naming a round is one question, and a second derivation would be a second answer
# to it - which is the one thing a round identity may not have.
#
# WHY A REVISION, AND WHY IT IS THE HUMAN'S
# -----------------------------------------
# A review round executes ONCE (`max_attempts = 1`). That is a property of a round, not of
# the system: the failure it prevents is a failed review being silently retried on the same
# inputs until it happens to pass, which is not a review.
#
# A DIFFERENT, REAL failure is the one that has no answer here: a C14 legitimately returns
# FAIL, the FAIL is about the review BRIEF (the pull-request description claimed something
# the diff contradicts), a human corrects the brief - and the round's inputs are now
# different while the issue number and the candidate SHA are not, so the identity still
# addresses the OLD round and no second review can exist. The candidate is unchanged and
# correct; only the question asked about it changed.
#
# So the revision is a suffix on the SAME derivation rather than a second one: revision 1
# is the historical identity, byte for byte, and revision n>1 appends `-R<n>`. Every
# derived name - the round id, both Lite task ids, and therefore the request id and the
# Runtime idempotency key - moves together, because they are all derived from this one
# string. Nothing else about a round changes: a revision-n round is still one attempt.
#
# It is NEVER automatic. Nothing in this channel may increment it - not a failed verdict,
# not a retry counter, not a timer. Only a human editing the Review issue can raise it,
# which is what makes "a new round" a human statement that the inputs changed rather than a
# machine's guess that they might have.
MAX_REVIEW_REVISION = 99


def review_round_identity(issue_number: int, candidate_sha: str, revision: int = 1) -> dict:
    """The round id and its two Lite task ids, derived from provenance and candidate.

    The candidate's first twelve hex characters, not the issue title: a second issue raised
    for a DIFFERENT candidate is a different round even if it describes the same PR, and
    re-raising the same one is the same round.

    `revision` defaults to the historical round. Revision 1 produces exactly the string this
    function has always produced; revision n>1 appends `-R<n>`. The Builder path never
    passes it, so a Builder round is always revision 1 and a Builder cannot commission a
    re-review of its own output.
    """
    if type(issue_number) is not int or issue_number <= 0:
        raise Refused("ISSUE_NUMBER_INVALID")
    _require_sha1(candidate_sha, "REVIEW_CANDIDATE_SHA_INVALID")
    # `type(...) is not int` already excludes bool, which is an int subclass and must never
    # be accepted as "revision 1".
    if type(revision) is not int or revision < 1 or revision > MAX_REVIEW_REVISION:
        raise Refused("REVIEW_REVISION_INVALID")
    short = candidate_sha.strip().lower()[:12]
    ledger_round_id = "FORMAL-REVIEW-I%d-%s" % (issue_number, short)
    if revision != 1:
        ledger_round_id = "%s-R%d" % (ledger_round_id, revision)
    return {
        "ledger_round_id": ledger_round_id,
        "c14_task_id": ledger_round_id + "-C14",
        "c13_task_id": ledger_round_id + "-C13",
    }


# The C13 machine-test inventory, derived from what a candidate CHANGED. `machine_inventory`
# is never a field a caller fills in from taste, and the alternative default - the whole
# `application/tests` tree - is 274 files including suites no other workflow runs, inside a
# job with a forty minute ceiling.
#
# Paths are restricted to exactly this shape and nothing else may appear on the wire: the
# value is interpolated into a shell command by the C13 workflow, so a path is only ever
# accepted when it is provably a plain path under this one directory. Removed paths are
# dropped too - a file that no longer exists cannot be collected by pytest.
REVIEW_TEST_PATH = re.compile(r"^application/tests/[A-Za-z0-9_./-]+\.py$")
MAX_REVIEW_TEST_FILES = 20
MAX_REVIEW_INVENTORY_CHARS = 400


def review_test_inventory(changed_files):
    """The candidate's own added/modified test paths, or None when it changed none.

    None is a real answer: it leaves the C13 workflow's own declared default standing,
    which is a scope decision that workflow already owns.
    """
    selected = []
    for entry in changed_files or ():
        if not isinstance(entry, dict):
            continue
        name = entry.get("filename")
        if not isinstance(name, str) or not REVIEW_TEST_PATH.match(name):
            continue
        if entry.get("status") == "removed":
            continue
        selected.append(name)
    selected = sorted(set(selected))[:MAX_REVIEW_TEST_FILES]
    while selected and len(" ".join(selected)) > MAX_REVIEW_INVENTORY_CHARS:
        selected.pop()
    return " ".join(selected) or None


# Every task kind this contract knows. A kind outside this set has no payload shape, no
# prompt and no acceptance rule, and is refused rather than guessed at.
KNOWN_TASK_KINDS = (KIND, REAL_TASK_KIND, GHAW_BUILDER_KIND) + REVIEW_KINDS


def provider_for_kind(task_kind: str) -> str:
    """The executor identity fixed for a task class. NEVER a caller input.

    It is inside `task_binding`, so it is part of the execution identity: a task executed
    by a single Responses call and a task executed by a gh-aw workflow can never resolve
    to the same `execution_request_id`.
    """
    if task_kind == GHAW_BUILDER_KIND or task_kind in REVIEW_KINDS:
        return PROVIDER_GHAW_BUILDER
    if task_kind in (KIND, REAL_TASK_KIND):
        return PROVIDER
    raise Refused("TASK_KIND_UNKNOWN")


def workflow_file_for_kind(task_kind: str) -> str:
    """The workflow a dispatch for this class is aimed at. Fixed config, never a request.

    Only reached for a class this contract knows; the smoke and real-task values are the
    one this channel has always used, byte for byte.
    """
    if task_kind == GHAW_BUILDER_KIND:
        return GHAW_BUILDER_WORKFLOW_FILE
    if task_kind in REVIEW_KINDS:
        return REVIEW_WORKFLOW_FILE[task_kind]
    if task_kind in (KIND, REAL_TASK_KIND):
        return WORKFLOW_FILE
    raise Refused("TASK_KIND_UNKNOWN")


def allowed_owner_cs_for_kind(task_kind: str) -> tuple:
    """The cells a task of this kind may belong to. ONE definition of each boundary.

    Deliberately a function of the kind rather than a parameter a caller supplies: the
    kinds an executor claims already determine the cells it may run for, so letting a
    caller pass its own owner set would let an executor widen its own boundary. Every
    caller - the payload validator, the claim gate, the worker's owner list - reads this
    one answer, which is why there is no second copy of "C1..C12" anywhere.

        GHAW_BUILDER_V1  -> C1..C12      (the Builder executor's cells)
        AI_WORK_V1,      -> C1           (the Responses executor; unchanged)
        AI_TASK_V1
    """
    if task_kind == GHAW_BUILDER_KIND:
        return BUILDER_OWNER_CS
    if task_kind in REVIEW_KINDS:
        return (REVIEW_OWNER_C[task_kind],)
    if task_kind in (KIND, REAL_TASK_KIND):
        return LEGACY_OWNER_CS
    raise Refused("TASK_KIND_UNKNOWN")


def canonical(document) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prompt_sha256(prompt: str | None = None) -> str:
    """Hash of the prompt an execution will actually send.

    With no argument: the fixed smoke prompt, exactly as before. A real task passes the
    prompt derived from its own payload.
    """
    return sha256_hex(PROMPT if prompt is None else prompt)


def output_sha256(output: str) -> str:
    return sha256_hex(output)


def require_runtime_facts(runtime_task_id, attempt) -> tuple:
    if not isinstance(runtime_task_id, str) or not runtime_task_id:
        raise Refused("RUNTIME_TASK_ID_MISSING")
    if type(attempt) is not int or attempt < 1:
        raise Refused("ATTEMPT_NOT_POSITIVE_INT")
    return runtime_task_id, attempt


# ------------------------------------------------------------- real task payload
def _bounded_text(value, *, limit: int, reason: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Refused(reason)
    text = value.strip()
    if len(text) > limit:
        raise Refused(reason + "_TOO_LONG")
    return text


def validate_task_payload(payload, *, allowed_owner_cs=LEGACY_OWNER_CS) -> dict:
    """Normalise and validate a real-task payload, or refuse it.

    Returns the payload with `cell_id` folded onto the canonical spelling, so what is
    bound, what is stored and what reaches the prompt all agree on one value.

    Three questions, kept separate because they have three different answers:

      1. shape     - is this a real-task payload at all? (field set, required fields,
                     schema version, bounded text)
      2. canonical - which cell is `cell_id` really? (`canonical_cell_id()`, which knows
                     all fourteen and is shared with everything else that reads a cell)
      3. boundary  - may THIS executor run for that cell? (`allowed_owner_cs`)

    Only the third is executor-specific, so only the third is a parameter. The default is
    the Responses executor's own set, which is what every existing caller meant and what
    keeps `AI_TASK_V1` at C1-only without a second validator existing anywhere. A caller
    that runs for a wider range passes its own set - it can only narrow the question, not
    widen the parser, because step 2 has already happened by the time step 3 runs.
    """
    if type(payload) is not dict:
        raise Refused("TASK_PAYLOAD_NOT_AN_OBJECT")
    unknown = set(payload) - TASK_PAYLOAD_FIELDS
    refused = sorted(unknown & TASK_PAYLOAD_REFUSED)
    if refused:
        # Naming the field makes the refusal actionable instead of mysterious.
        raise Refused("TASK_PAYLOAD_REFUSED_FIELD:" + ",".join(refused))
    if unknown:
        raise Refused("TASK_PAYLOAD_UNKNOWN_FIELD:" + ",".join(sorted(unknown)))
    missing = [name for name in TASK_PAYLOAD_REQUIRED if name not in payload]
    if missing:
        raise Refused("TASK_PAYLOAD_MISSING_FIELD:" + ",".join(missing))
    if payload["schema_version"] != REAL_PAYLOAD_SCHEMA_VERSION:
        raise Refused("TASK_PAYLOAD_SCHEMA_VERSION_UNSUPPORTED")

    normalised = {
        "schema_version": REAL_PAYLOAD_SCHEMA_VERSION,
        "cell_id": canonical_cell_id(payload["cell_id"]),
        "external_task_id": _bounded_text(
            payload["external_task_id"], limit=MAX_EXTERNAL_TASK_ID,
            reason="TASK_PAYLOAD_EXTERNAL_TASK_ID_INVALID"),
        "objective": _bounded_text(payload["objective"], limit=MAX_OBJECTIVE,
                                   reason="TASK_PAYLOAD_OBJECTIVE_INVALID"),
        "scope": _bounded_text(payload["scope"], limit=MAX_SCOPE,
                               reason="TASK_PAYLOAD_SCOPE_INVALID"),
    }
    if normalised["cell_id"] not in allowed_owner_cs:
        # A real cell this executor does not serve. The reason names the boundary rather
        # than one cell, because "not C1" stopped being the whole truth the moment a
        # second executor existed with twelve cells - and it is the boundary, not the
        # spelling, that a caller got wrong.
        raise Refused("TASK_PAYLOAD_CELL_NOT_OWNED_BY_THIS_EXECUTOR")
    for name in TASK_PAYLOAD_TRACE_ONLY:
        if name not in payload:
            continue
        value = payload[name]
        if name == "issue_number":
            if type(value) is not int or value <= 0:
                raise Refused("TASK_PAYLOAD_ISSUE_NUMBER_INVALID")
        else:
            value = _bounded_text(value, limit=MAX_SOURCE_ANCHOR,
                                  reason="TASK_PAYLOAD_SOURCE_ANCHOR_INVALID")
        normalised[name] = value
    return normalised


def build_task_payload(*, cell_id, external_task_id, objective, scope,
                       source_anchor=None, issue_number=None,
                       allowed_owner_cs=LEGACY_OWNER_CS) -> dict:
    """Compose a real-task payload from the fields a caller actually has.

    `cell_id` may be given in either spelling; it is canonicalised here, so the caller
    never has to know which one the kernel uses. `allowed_owner_cs` is the composing
    caller's own boundary and is passed straight through to validation - the caller that
    knows which executor this task is for is the only one that can state it.
    """
    payload = {
        "schema_version": REAL_PAYLOAD_SCHEMA_VERSION,
        "cell_id": cell_id,
        "external_task_id": external_task_id,
        "objective": objective,
        "scope": scope,
    }
    if source_anchor is not None:
        payload["source_anchor"] = source_anchor
    if issue_number is not None:
        payload["issue_number"] = issue_number
    return validate_task_payload(payload, allowed_owner_cs=allowed_owner_cs)


def task_idempotency_key(task_kind, cell_id, external_task_id) -> str:
    """The Runtime-side idempotency key for one external task, per executor kind.

    Derived, not chosen, so the same external task presented twice cannot become two
    Runtime tasks. Reuses the Runtime's own `idempotency_key` mechanism - there is no
    second de-duplication system anywhere in this channel.

    The kind is part of the key because the Runtime's UNIQUE(idempotency_key) is the only
    de-duplication there is: two executors deriving the same key for the same external
    task would collapse into ONE Runtime task, which would then carry whichever kind was
    enqueued first and be invisible to the other executor for as long as it existed.
    Deriving the key from the kind as well keeps "the same task for a different executor"
    a different task, which is what it is.
    """
    if task_kind == REAL_TASK_KIND:
        prefix = "c1-ai-task-v1"
    elif task_kind == GHAW_BUILDER_KIND:
        prefix = "c1-ghaw-builder-v1"
    elif task_kind in REVIEW_KINDS:
        # One key namespace for both review kinds: a C14 round and its C13 round are
        # one review of one candidate, and the per-cell task ids already distinguish
        # them. The cell is still part of the key (below), so a C14 and a C13 round can
        # never collapse into one Runtime task.
        prefix = "c1-c13c14-review-v1"
    else:
        raise Refused("TASK_KIND_UNKNOWN")
    return "%s:%s:%s" % (
        prefix,
        canonical_cell_id(cell_id),
        _bounded_text(external_task_id, limit=MAX_EXTERNAL_TASK_ID,
                      reason="TASK_PAYLOAD_EXTERNAL_TASK_ID_INVALID"))


def real_idempotency_key(cell_id, external_task_id) -> str:
    """The `AI_TASK_V1` idempotency key, unchanged: `c1-ai-task-v1:<cell>:<task id>`."""
    return task_idempotency_key(REAL_TASK_KIND, cell_id, external_task_id)


# --------------------------------------------------------------- prompt derivation
def prompt_for_task(task_kind: str, payload) -> str:
    """The prompt an execution of this kind sends, derived from the task's own payload.

    The smoke prompt is the existing fixed literal. A real prompt is a pure function of
    the payload's execution-input fields, so two different payloads cannot produce the
    same prompt and the same payload always produces the same bytes - which is what makes
    `prompt_sha256` a meaningful commitment inside the binding.

    The opening line names the cell from the payload rather than hard-coding it. For C1
    that renders exactly the bytes this function has always produced - `GO C1 ...` - so
    the live C01 execution identity is unchanged, while a C12 task no longer opens with a
    claim about C1 that is simply false.
    """
    if task_kind == KIND:
        return PROMPT
    if task_kind == REAL_TASK_KIND:
        normalised = validate_task_payload(
            payload, allowed_owner_cs=allowed_owner_cs_for_kind(task_kind))
        return (
            "GO %s real task (AI_TASK_V1).\n"
            "cell: %s\nexternal_task_id: %s\n"
            "\nOBJECTIVE\n%s\n"
            "\nSCOPE\n%s\n"
            "\nAnswer the objective within the scope. Reply with the task result as plain "
            "text and nothing else. You have no authority to change money, state, "
            "deployment, release or configuration, and you must not claim any."
            % (normalised["cell_id"], normalised["cell_id"],
               normalised["external_task_id"],
               normalised["objective"], normalised["scope"]))
    if task_kind in REVIEW_KINDS:
        # A review derives its own brief from its workflow; this literal exists only so
        # the execution identity commits to what the round is about. It is deliberately
        # different from both other literals: two classes producing the same bytes would
        # defeat the `prompt_sha256` commitment. The transport identity is absent on
        # purpose - a review's prompt must not depend on how it was delivered.
        normalised = validate_review_task_payload(
            payload, allowed_owner_cs=allowed_owner_cs_for_kind(task_kind))
        return (
            "GO %s sealed review round (%s).\n"
            "round: %s cell: %s external_task_id: %s\n"
            "candidate: %s application_tree: %s issue: %s\n"
            "\nReview the frozen candidate within this cell's own remit. You have no "
            "authority to change money, state, deployment, release or configuration, "
            "and you must not claim any."
            % (normalised["cell_id"], task_kind, normalised["ledger_round_id"],
               normalised["cell_id"], normalised["external_task_id"],
               normalised["candidate_sha"], normalised["application_tree"],
               normalised["issue_number"]))
    if task_kind == GHAW_BUILDER_KIND:
        # The gh-aw Builder derives its own prompt from its workflow; this one exists so
        # the execution identity has a commitment to what this task asked for. It is a
        # different literal from the real-task prompt on purpose: two classes that
        # happened to produce the same bytes would defeat the `prompt_sha256` commitment.
        normalised = validate_task_payload(
            payload, allowed_owner_cs=allowed_owner_cs_for_kind(task_kind))
        return (
            "GO %s gh-aw Builder task (GHAW_BUILDER_V1).\n"
            "cell: %s\nexternal_task_id: %s\n"
            "\nOBJECTIVE\n%s\n"
            "\nSCOPE\n%s\n"
            "\nDeliver the objective within the scope. You have no authority to change "
            "money, state, deployment, release or configuration, and you must not claim "
            "any."
            % (normalised["cell_id"], normalised["cell_id"],
               normalised["external_task_id"],
               normalised["objective"], normalised["scope"]))
    raise Refused("TASK_KIND_UNKNOWN")


# --------------------------------------------------------------------- task specs
def task_spec(task_kind: str, payload) -> dict:
    """A normalised description of one task class, safe to store and re-read.

    Explicit rather than re-derived from a kind string at each use: this is what lets the
    resume leg rebuild an execution identity without the Runtime, because the spec is
    stored beside the outbox row.

    The payload is validated against the OWNER BOUNDARY of its own kind, which is what
    makes "a C13 Builder task" unrepresentable rather than merely discouraged: no spec
    carrying one can be built, so none can be bound, stored or dispatched.
    """
    if task_kind == KIND:
        if payload != PAYLOAD:
            raise Refused("SMOKE_PAYLOAD_MISMATCH")
        return {"task_class": TASK_CLASS_SMOKE, "task_kind": KIND, "payload": PAYLOAD}
    if task_kind in REVIEW_KINDS:
        # The review class: its own payload shape, its own result envelope, its own
        # executor - and its own row of the task table, one row per kind, so C14 and C13
        # can never be confused for one another.
        return {"task_class": TASK_CLASS_REVIEW, "task_kind": task_kind,
                "payload": validate_review_task_payload(
                    payload, allowed_owner_cs=allowed_owner_cs_for_kind(task_kind))}
    if task_kind in (REAL_TASK_KIND, GHAW_BUILDER_KIND):
        # One real-task payload shape, two executors. The spec keeps the kind, so the
        # class travels with the identity and a resume does not have to guess which
        # executor a row belonged to.
        return {"task_class": TASK_CLASS_REAL, "task_kind": task_kind,
                "payload": validate_task_payload(
                    payload, allowed_owner_cs=allowed_owner_cs_for_kind(task_kind))}
    raise Refused("TASK_KIND_UNKNOWN")


SMOKE_SPEC = {"task_class": TASK_CLASS_SMOKE, "task_kind": KIND, "payload": PAYLOAD}

# ------------------------------------------------------ C13/C14 review round (V1)
# A review round is described by the EXISTING Lite identity - candidate, application
# tree, issue, request id, ledger round and the two ledger task ids - plus the two
# things the execution backend needs that the Lite identity does not carry (the frozen
# machine-test inventory for C13, and the model name).
#
# The Runtime transport identity (runtime_task_id / attempt / execution_request_id /
# owner_c) is deliberately NOT part of this payload. It is the envelope the transport
# adds on the wire, and it is a fact about *delivery*; letting it into the payload would
# let a delivery detail change what the review is about - and, because the payload is
# inside the hashed binding, a re-delivery would look like a different review.
REVIEW_PAYLOAD_SCHEMA_VERSION = 1
REVIEW_PAYLOAD_FIELDS = frozenset({
    "schema_version", "cell_id", "external_task_id",
    "candidate_sha", "application_tree", "issue_number",
    "review_request_id", "ledger_round_id", "c14_task_id", "c13_task_id",
    "machine_inventory", "ai_model", "c14_run_id", "c14_runtime_task_id", "frozen_base",
})
REVIEW_PAYLOAD_REQUIRED = (
    "schema_version", "cell_id", "external_task_id", "candidate_sha",
    "application_tree", "issue_number", "review_request_id", "ledger_round_id",
    "c14_task_id", "c13_task_id")
# The C13 round is the *second* half and is bound to the C14 execution it follows; a C13
# payload that cannot name its C14 run cannot be verified against it.
REVIEW_PAYLOAD_REQUIRED_C13 = REVIEW_PAYLOAD_REQUIRED + ("c14_run_id",
                                                        "c14_runtime_task_id")
# Produced by the review, or by the Runtime. Accepting any of these at enqueue time
# would let a caller assert a verdict before one exists.
REVIEW_PAYLOAD_REFUSED = frozenset({
    "verdict", "review_verdict", "deployment_eligible", "authorizes_any_action",
    "runtime_task_id", "attempt", "execution_request_id", "owner_c",
    "github_run_id", "github_run_attempt", "result", "accepted", "status",
    "c14_runtime_task_id",
    "sealed_bundle", "sealed_bundle_root", "sealed_bundle_sha256",
})

MAX_REVIEW_ID = 200
MAX_MACHINE_INVENTORY = 2048
MAX_AI_MODEL = 200
_SHA1_HEX = re.compile(r"^[0-9a-f]{40}$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def _require_sha1(value, reason: str) -> str:
    if not isinstance(value, str) or not _SHA1_HEX.match(value.strip().lower()):
        raise Refused(reason)
    return value.strip().lower()


def validate_review_task_payload(payload, *, allowed_owner_cs=LEGACY_OWNER_CS) -> dict:
    """Normalise and validate a review-round payload, or refuse it.

    Same three questions as `validate_task_payload` - shape, canonical cell, executor
    boundary - because a review task is a task of this channel like any other. What
    differs is the shape, and only the shape.
    """
    if type(payload) is not dict:
        raise Refused("REVIEW_PAYLOAD_NOT_AN_OBJECT")
    unknown = set(payload) - REVIEW_PAYLOAD_FIELDS
    refused = sorted(unknown & REVIEW_PAYLOAD_REFUSED)
    if refused:
        raise Refused("REVIEW_PAYLOAD_REFUSED_FIELD:" + ",".join(refused))
    if unknown:
        raise Refused("REVIEW_PAYLOAD_UNKNOWN_FIELD:" + ",".join(sorted(unknown)))
    missing = [name for name in REVIEW_PAYLOAD_REQUIRED if name not in payload]
    if missing:
        raise Refused("REVIEW_PAYLOAD_MISSING_FIELD:" + ",".join(missing))
    if payload["schema_version"] != REVIEW_PAYLOAD_SCHEMA_VERSION:
        raise Refused("REVIEW_PAYLOAD_SCHEMA_VERSION_UNSUPPORTED")

    cell_id = canonical_cell_id(payload["cell_id"])
    if cell_id not in allowed_owner_cs:
        # C13 and C14 are two different reviews of two different things; a C14 payload on a
        # C13 executor (or the reverse) is a boundary error, not a spelling one.
        raise Refused("REVIEW_PAYLOAD_CELL_NOT_OWNED_BY_THIS_EXECUTOR")

    normalised = {
        "schema_version": REVIEW_PAYLOAD_SCHEMA_VERSION,
        "cell_id": cell_id,
        "external_task_id": _bounded_text(
            payload["external_task_id"], limit=MAX_REVIEW_ID,
            reason="REVIEW_PAYLOAD_EXTERNAL_TASK_ID_INVALID"),
        "candidate_sha": _require_sha1(payload["candidate_sha"],
                                      "REVIEW_PAYLOAD_CANDIDATE_SHA_INVALID"),
        "application_tree": _require_sha1(payload["application_tree"],
                                          "REVIEW_PAYLOAD_APPLICATION_TREE_INVALID"),
        "review_request_id": _bounded_text(
            payload["review_request_id"], limit=MAX_REVIEW_ID,
            reason="REVIEW_PAYLOAD_REQUEST_ID_INVALID"),
        "ledger_round_id": _bounded_text(
            payload["ledger_round_id"], limit=MAX_REVIEW_ID,
            reason="REVIEW_PAYLOAD_LEDGER_ROUND_ID_INVALID"),
        "c14_task_id": _bounded_text(
            payload["c14_task_id"], limit=MAX_REVIEW_ID,
            reason="REVIEW_PAYLOAD_C14_TASK_ID_INVALID"),
        "c13_task_id": _bounded_text(
            payload["c13_task_id"], limit=MAX_REVIEW_ID,
            reason="REVIEW_PAYLOAD_C13_TASK_ID_INVALID"),
    }
    issue_number = payload["issue_number"]
    if type(issue_number) is not int or issue_number <= 0:
        raise Refused("REVIEW_PAYLOAD_ISSUE_NUMBER_INVALID")
    normalised["issue_number"] = issue_number
    # The transport's own task id IS this cell's Lite task id: the two identities name the
    # same task from two sides, and letting them disagree is what would let one round be
    # executed twice under two names.
    expected_task_id = normalised["c14_task_id"] if cell_id == "C14" else normalised["c13_task_id"]
    if normalised["external_task_id"] != expected_task_id:
        raise Refused("REVIEW_PAYLOAD_EXTERNAL_TASK_ID_IS_NOT_THE_CELLS_LITE_TASK_ID")
    if "frozen_base" in payload:
        normalised["frozen_base"] = validate_frozen_review_base(payload["frozen_base"])
    if "machine_inventory" in payload:
        normalised["machine_inventory"] = _bounded_text(
            payload["machine_inventory"], limit=MAX_MACHINE_INVENTORY,
            reason="REVIEW_PAYLOAD_MACHINE_INVENTORY_INVALID")
    if "ai_model" in payload:
        normalised["ai_model"] = _bounded_text(
            payload["ai_model"], limit=MAX_AI_MODEL,
            reason="REVIEW_PAYLOAD_AI_MODEL_INVALID")
    if "c14_run_id" in payload:
        value = payload["c14_run_id"]
        if type(value) is not int or value <= 0:
            raise Refused("REVIEW_PAYLOAD_C14_RUN_ID_INVALID")
        normalised["c14_run_id"] = value
    if "c14_runtime_task_id" in payload:
        normalised["c14_runtime_task_id"] = _bounded_text(
            payload["c14_runtime_task_id"], limit=MAX_REVIEW_ID,
            reason="REVIEW_PAYLOAD_C14_RUNTIME_TASK_ID_INVALID")
    # A kind-level requirement, checked here rather than at the caller: the C13 half of a
    # round cannot be formed without naming the C14 execution it follows - the GitHub run
    # (which the workflow requires) AND the Runtime task (which is what lets this side
    # cross-check the sealed C14 root against the record this Runtime actually received,
    # with no second lookup).
    if cell_id == "C13":
        for name in REVIEW_PAYLOAD_REQUIRED_C13:
            if name not in normalised:
                raise Refused("REVIEW_PAYLOAD_MISSING_FIELD:" + name)
    return normalised


def validate_frozen_review_base(value):
    """Explicit opt-in baseline; never inferred from a non-main PR."""
    if type(value) is not dict or set(value) != {"ref", "sha", "pr_number"}:
        raise Refused("REVIEW_FROZEN_BASE_INVALID")
    ref = value["ref"]
    if (not isinstance(ref, str) or len(ref) > 200
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]*", ref)
            or any(part in ("", ".", "..") or part.endswith(".lock")
                   for part in ref.split("/")) or ".." in ref or ref.endswith(".")):
        raise Refused("REVIEW_FROZEN_BASE_REF_INVALID")
    if type(value["pr_number"]) is not int or value["pr_number"] <= 0:
        raise Refused("REVIEW_FROZEN_BASE_PR_INVALID")
    return {"ref": ref, "sha": _require_sha1(value["sha"], "REVIEW_FROZEN_BASE_SHA_INVALID"),
            "pr_number": value["pr_number"]}


def build_review_task_payload(*, cell_id, external_task_id, candidate_sha, application_tree,
                             issue_number, review_request_id, ledger_round_id,
                             c14_task_id, c13_task_id, machine_inventory=None,
                             ai_model=None, c14_run_id=None, c14_runtime_task_id=None, frozen_base=None,
                             allowed_owner_cs=LEGACY_OWNER_CS) -> dict:
    payload = {
        "schema_version": REVIEW_PAYLOAD_SCHEMA_VERSION,
        "cell_id": cell_id,
        "external_task_id": external_task_id,
        "candidate_sha": candidate_sha,
        "application_tree": application_tree,
        "issue_number": issue_number,
        "review_request_id": review_request_id,
        "ledger_round_id": ledger_round_id,
        "c14_task_id": c14_task_id,
        "c13_task_id": c13_task_id,
    }
    if frozen_base is not None:
        payload["frozen_base"] = frozen_base
    if machine_inventory is not None:
        payload["machine_inventory"] = machine_inventory
    if ai_model is not None:
        payload["ai_model"] = ai_model
    if c14_run_id is not None:
        payload["c14_run_id"] = c14_run_id
    if c14_runtime_task_id is not None:
        payload["c14_runtime_task_id"] = c14_runtime_task_id
    return validate_review_task_payload(payload, allowed_owner_cs=allowed_owner_cs)


# ------------------------------------------------ sealed review result (transport envelope)
# The Runtime is told TWO different things and they must never be confused:
#
#   accepted          the review EXECUTION was delivered correctly - the run succeeded and
#                     a sealed bundle was received and verified. This is what
#                     `Runtime.complete(success=...)` records, because it is a statement
#                     about delivery, which is what the Runtime is for.
#   review_verdict    what the Cell decided about the CANDIDATE. FAIL and BLOCKED are
#                     perfectly good deliveries: the review ran and produced a sealed,
#                     valid verdict that happens to be negative.
#
# A negative verdict is therefore NOT a transport failure, and a transport failure is
# never reported as a verdict.
REVIEW_RESULT_KIND = "c1-c13c14-review-result"
REVIEW_RESULT_FIELDS = frozenset({
    "version", "kind", "owner_c", "runtime_task_id", "attempt", "execution_request_id",
    "github_run_id", "github_run_attempt", "provider",
    "review_verdict", "deployment_eligible", "accepted", "authorizes_any_action",
    "candidate_sha", "application_tree", "issue_number",
    "review_request_id", "ledger_round_id",
    "sealed_bundle_root", "sealed_bundle_sha256", "artifacts", "status",
    "round_decision",
})
REVIEW_VERDICTS = {
    C14_REVIEW_KIND: ("PASS_SCOPED", "NOT_APPLICABLE", "FAIL", "BLOCKED"),
    C13_REVIEW_KIND: ("PASS_SCOPED", "FAIL", "BLOCKED"),
}
# The round decision a C13 run publishes. It is DERIVED evidence: the Lite chain's own
# `Decision.as_dict()` over the two sealed bundles. The transport checks its shape and
# its consistency with the sealed verdict; it does not require it to be ACCEPT, because
# a negative verdict is a delivered review, not a delivery failure. Only REJECT - which
# the Lite chain raises for tampered, unbound or identity-conflicting evidence - is a
# chain-integrity failure.
REVIEW_ROUND_DECISIONS = ("ACCEPT", "BLOCK", "REJECT")
REVIEW_ROUND_DECISION_REJECT = "REJECT"

# A C14 verdict that unlocks the C13 half. The tuple itself is declared in the Lite chain
# (`lite_errors.C14_PREREQUISITE_OK`); this is the same two names, restated here because
# this module may not import the Lite package. `test_c1_c13c14_review_transport` binds the
# two together so they cannot drift.
C14_ADMITS_C13 = ("PASS_SCOPED", "NOT_APPLICABLE")


def validate_review_result(document, *, runtime_task_id, attempt, execution_request_id_,
                           task_kind: str) -> dict:
    """Validate the sealed review envelope against the exact task it claims to belong to.

    Structure and binding only, plus the two platform facts this channel insists on: the
    execution ran on the GitHub Agentic Workflows provider, and it authorises nothing.
    Whether the *bundle* inside is a valid sealed C14/C13 record is decided by the Lite
    validators, which the caller composes on top of this - this function never re-implements
    a review rule.
    """
    if task_kind not in REVIEW_VERDICTS:
        raise Refused("REVIEW_RESULT_TASK_KIND_UNKNOWN")
    if type(document) is not dict:
        raise Refused("REVIEW_RESULT_NOT_AN_OBJECT")
    extra = set(document) - REVIEW_RESULT_FIELDS
    if extra:
        if extra != {"failure_reason"} or document.get("accepted") is not False:
            raise Refused("REVIEW_RESULT_UNEXPECTED_FIELDS")
    missing = REVIEW_RESULT_FIELDS - set(document)
    if missing:
        raise Refused("REVIEW_RESULT_MISSING_FIELDS")
    if document["version"] != SCHEMA_VERSION or document["kind"] != REVIEW_RESULT_KIND:
        raise Refused("REVIEW_RESULT_KIND_OR_VERSION_MISMATCH")
    if document["owner_c"] != REVIEW_OWNER_C[task_kind]:
        raise Refused("REVIEW_RESULT_OWNER_CELL_MISMATCH")
    if document["runtime_task_id"] != runtime_task_id:
        raise Refused("REVIEW_RESULT_TASK_MISMATCH")
    if document["attempt"] != attempt:
        raise Refused("REVIEW_RESULT_ATTEMPT_MISMATCH")
    if document["execution_request_id"] != execution_request_id_:
        raise Refused("REVIEW_RESULT_EXECUTION_REQUEST_ID_MISMATCH")
    if document["provider"] != PROVIDER_GHAW_BUILDER:
        raise Refused("REVIEW_RESULT_PROVIDER_MISMATCH")
    if document["review_verdict"] not in REVIEW_VERDICTS[task_kind]:
        raise Refused("REVIEW_RESULT_VERDICT_UNKNOWN_FOR_THIS_CELL")
    if document["authorizes_any_action"] is not False:
        raise Refused("REVIEW_RESULT_MUST_NOT_AUTHORIZE_ANY_ACTION")
    if type(document["deployment_eligible"]) is not bool:
        raise Refused("REVIEW_RESULT_DEPLOYMENT_ELIGIBLE_NOT_BOOLEAN")
    if document["deployment_eligible"] is True:
        # Being eligible is a statement about evidence, and this channel never makes it
        # from a single half of a round: only the full C14+C13 chain does, and even then it
        # authorises nothing. A sealed bundle reported here is not that.
        raise Refused("REVIEW_RESULT_MUST_NOT_CLAIM_DEPLOYMENT_ELIGIBILITY")
    if type(document["accepted"]) is not bool:
        raise Refused("REVIEW_RESULT_ACCEPTED_NOT_BOOLEAN")
    expected_status = "SUCCEEDED" if document["accepted"] else "FAILED"
    if document["status"] != expected_status:
        raise Refused("REVIEW_RESULT_STATUS_INCONSISTENT_WITH_ACCEPTED")
    if type(document["github_run_id"]) is not int or document["github_run_id"] <= 0:
        raise Refused("REVIEW_RESULT_GITHUB_RUN_ID_INVALID")
    if type(document["github_run_attempt"]) is not int or document["github_run_attempt"] < 1:
        raise Refused("REVIEW_RESULT_GITHUB_RUN_ATTEMPT_INVALID")
    _require_sha1(document["candidate_sha"], "REVIEW_RESULT_CANDIDATE_SHA_INVALID")
    _require_sha1(document["application_tree"], "REVIEW_RESULT_APPLICATION_TREE_INVALID")
    if type(document["issue_number"]) is not int or document["issue_number"] <= 0:
        raise Refused("REVIEW_RESULT_ISSUE_NUMBER_INVALID")
    for name in ("review_request_id", "ledger_round_id"):
        _bounded_text(document[name], limit=MAX_REVIEW_ID,
                      reason="REVIEW_RESULT_" + name.upper() + "_INVALID")
    if not isinstance(document["sealed_bundle_root"], str) or             not _SHA256_HEX.match(document["sealed_bundle_root"]):
        raise Refused("REVIEW_RESULT_SEALED_BUNDLE_ROOT_INVALID")
    if not isinstance(document["sealed_bundle_sha256"], str) or             not _SHA256_HEX.match(document["sealed_bundle_sha256"]):
        raise Refused("REVIEW_RESULT_SEALED_BUNDLE_SHA256_INVALID")
    artifacts = document["artifacts"]
    if not isinstance(artifacts, dict) or not artifacts:
        raise Refused("REVIEW_RESULT_ARTIFACTS_INVALID")
    for name, value in artifacts.items():
        if not isinstance(name, str) or not name:
            raise Refused("REVIEW_RESULT_ARTIFACT_NAME_INVALID")
        if not isinstance(value, str) or not _SHA256_HEX.match(value):
            raise Refused("REVIEW_RESULT_ARTIFACT_DIGEST_INVALID:" + name)
    round_decision = document["round_decision"]
    if task_kind == C14_REVIEW_KIND:
        # The C14 half publishes no round decision: there is no round yet.
        if round_decision is not None:
            raise Refused("REVIEW_RESULT_C14_MUST_NOT_CARRY_A_ROUND_DECISION")
    else:
        if not isinstance(round_decision, dict):
            raise Refused("REVIEW_RESULT_ROUND_DECISION_MISSING")
        if round_decision.get("authorizes_any_action") is not False:
            raise Refused("REVIEW_ROUND_DECISION_MUST_NOT_AUTHORIZE_ANY_ACTION")
        if round_decision.get("decision") not in REVIEW_ROUND_DECISIONS:
            raise Refused("REVIEW_ROUND_DECISION_UNKNOWN")
        # Shape only. Whether this decision is the *consequence* of the sealed verdict is
        # decided beside the Lite chain, in `c1_c13c14_review` - and a BLOCK is a
        # perfectly ordinary outcome there.
        if round_decision["decision"] == "ACCEPT" and \
                document["review_verdict"] != "PASS_SCOPED":
            raise Refused("REVIEW_RESULT_ACCEPTED_ROUND_WITH_A_NON_PASS_VERDICT")
    if not document["accepted"] and "failure_reason" not in document:
        raise Refused("REVIEW_RESULT_FAILED_WITHOUT_A_REASON")
    return document


def c14_admits_c13(verdict: str) -> bool:
    """Whether a sealed C14 verdict unlocks the C13 half of the round.

    C14 runs FIRST and only its acceptable outcomes admit C13. FAIL and BLOCKED do not:
    the C14 runtime task completes normally and records its verdict, and no C13 task is
    created - a negative review is a result, not a delivery failure.
    """
    return verdict in C14_ADMITS_C13

# The two kinds this channel owns. Anything else is not ours to execute.
CLAIMABLE_KINDS = (KIND, REAL_TASK_KIND)


def spec_from_request(request) -> dict:
    """Recover the spec from a stored dispatch request, for the resume leg."""
    if type(request) is not dict:
        raise Refused("REQUEST_NOT_AN_OBJECT")
    return task_spec(request.get("task_kind", KIND), request.get("payload", PAYLOAD))


def prompt_for_spec(spec) -> str:
    return prompt_for_task(spec["task_kind"], spec["payload"])


# ----------------------------------------------------------------------- identity
def task_binding(runtime_task_id, attempt, spec=None) -> dict:
    """The canonical binding whose hash IS the execution identity.

    With no `spec` this is the deployed smoke binding byte for byte: same keys, same
    values, same canonical JSON. Nothing in this revision may change that, because the
    execution identity of the already-completed live smoke is derived from it.
    """
    runtime_task_id, attempt = require_runtime_facts(runtime_task_id, attempt)
    if spec is None or spec["task_class"] == TASK_CLASS_SMOKE:
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
    payload = spec["payload"]
    task_kind = spec["task_kind"]
    # `task_kind` and `provider` are read from the spec rather than fixed here: the class
    # is what decides them, and both are inside the hash. For `AI_TASK_V1` this produces
    # the same document, byte for byte, that it always has - the class is exactly the one
    # this branch used to assume.
    #
    # `owner_c` is the payload's own canonical cell, not a constant. It has already been
    # validated against the kind's owner boundary by `task_spec`, so this is not a second
    # gate - it is the one place the cell enters the identity, which is what makes two
    # cells' otherwise identical tasks resolve to two different executions. For C1 the
    # payload's cell IS "C1", so the live C01 binding is unchanged byte for byte.
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": REQUEST_KIND,
        "owner_c": payload["cell_id"],
        "task_kind": task_kind,
        "payload": payload,
        "payload_sha256": sha256_hex(canonical(payload)),
        "external_task_id": payload["external_task_id"],
        "runtime_task_id": runtime_task_id,
        "attempt": attempt,
        "provider": provider_for_kind(task_kind),
        "prompt_sha256": prompt_sha256(prompt_for_spec(spec)),
    }


def execution_request_id(runtime_task_id, attempt, spec=None) -> str:
    """Deterministic: same task + same attempt + same spec => same id, on both sides."""
    return sha256_hex(canonical(task_binding(runtime_task_id, attempt, spec)))


def build_dispatch_request(runtime_task_id, attempt, spec=None) -> dict:
    """The canonical request the Runtime forms before anything is sent anywhere.

    `repo`, `workflow_file` and `ref` are transport configuration, added *after* the
    identity is hashed, so they are not part of `execution_request_id` - which is exactly
    why the class that will execute the task has to be visible in the binding instead
    (`task_kind`, `provider`, `owner_c`), not in the target it is sent to.
    """
    request = dict(task_binding(runtime_task_id, attempt, spec))
    request["execution_request_id"] = sha256_hex(canonical(request))
    request["repo"] = REPO
    request["workflow_file"] = workflow_file_for_kind(request.get("task_kind", KIND))
    request["ref"] = REF
    return request


def dispatch_inputs(request: dict) -> dict:
    """The wire inputs.

    A smoke dispatch carries exactly the identity triple - no prompt, model or URL. A real
    dispatch additionally carries its kind and payload, because the executor runs
    elsewhere and must be able to re-derive the same identity and the same prompt from
    what it receives.

    The gh-aw Builder additionally carries `owner_c`, copied from the binding - not
    recomputed here and not taken from the caller. The validator upstream has already
    proved it is the payload's canonical cell, so this module and the workflow agree on
    the cell by construction; the workflow re-checks it anyway, because two values that
    travel by different routes are worth comparing at the far end.
    """
    inputs = {
        "runtime_task_id": request["runtime_task_id"],
        "attempt": request["attempt"],
        "execution_request_id": request["execution_request_id"],
    }
    task_kind = request.get("task_kind", KIND)
    if task_kind in (REAL_TASK_KIND, GHAW_BUILDER_KIND):
        inputs["task_kind"] = task_kind
        inputs["task_payload"] = canonical(validate_task_payload(
            request["payload"], allowed_owner_cs=allowed_owner_cs_for_kind(task_kind)))
    if task_kind == GHAW_BUILDER_KIND:
        inputs["owner_c"] = request["owner_c"]
    if task_kind in REVIEW_KINDS:
        # The existing Lite workflow inputs, plus ONE transport envelope. It is one input
        # because `workflow_dispatch` allows at most ten and the C13 workflow already needs
        # all ten for its own identity - and because the quartet is delivery metadata: the
        # workflow builds its deterministic run name from it and checks its own owner cell
        # against it, and for nothing else. In particular it never reaches the review brief,
        # so it cannot change a verdict. `c14_run_id` rides in the same envelope: it is
        # another execution's identity, which is what the envelope is for.
        payload = validate_review_task_payload(
            request["payload"], allowed_owner_cs=allowed_owner_cs_for_kind(task_kind))
        transport = {
            "owner_c": request["owner_c"],
            "runtime_task_id": request["runtime_task_id"],
            "attempt": request["attempt"],
            "execution_request_id": request["execution_request_id"],
        }
        if "c14_run_id" in payload:
            transport["c14_run_id"] = payload["c14_run_id"]
        # Optional review binding rides in the existing envelope to preserve the
        # ten-input platform limit. Unlike transport identity it IS review data.
        if "frozen_base" in payload:
            transport["frozen_base"] = payload["frozen_base"]
        inputs = {
            "runtime_transport": canonical(transport),
            "candidate_sha": payload["candidate_sha"],
            "application_tree": payload["application_tree"],
            "issue_number": str(payload["issue_number"]),
            "request_id": payload["review_request_id"],
            "ledger_round_id": payload["ledger_round_id"],
            "c14_task_id": payload["c14_task_id"],
            "c13_task_id": payload["c13_task_id"],
        }
        # Only the optional inputs THIS cell's workflow actually declares. See
        # REVIEW_WIRE_OPTIONAL: a name the receiving workflow does not define makes GitHub
        # refuse the whole dispatch, so the payload's optional fields are filtered by the
        # workflow they are about to be sent to rather than forwarded wholesale.
        for name in REVIEW_WIRE_OPTIONAL[task_kind]:
            if name in payload:
                inputs[name] = payload[name]
    return inputs


def run_identity_name(runtime_task_id, attempt, request_id, owner_c=OWNER_C) -> str:
    """The deterministic run name the workflow sets, used to resolve a run by lookup.

    A dispatch whose HTTP outcome is unknown must be resolved by looking for this
    name, never by sending a second POST.

    The cell leads, and defaults to C1 so that every existing caller - and every run name
    the live Runtime Host has already recorded - keeps the exact bytes it had. A C12
    execution resolves under `C12 <task> <attempt> <request_id>`; the request id already
    differs between cells, and the leading cell makes that visible in the one place a
    human looks when a lookup fails.
    """
    return "%s %s %s %s" % (owner_c, runtime_task_id, attempt, request_id)


# ------------------------------------------------------------------- result side
def validate_result(document, *, runtime_task_id, attempt, execution_request_id_,
                    task_kind: str = KIND) -> dict:
    """Validate a sealed result against the exact task identity it claims to belong to.

    Fails closed on: wrong field set, wrong kind/version, wrong task, wrong attempt,
    wrong execution_request_id, inconsistent accepted/status, mismatched output hash.

    `task_kind` selects two things, and both of them are facts about the class rather
    than about the text:
      * SMOKE - the output must be the fixed smoke literal (unchanged, so the deployed
        smoke keeps the acceptance rule it has always had);
      * REAL (`AI_TASK_V1` and `GHAW_BUILDER_V1`) - any non-empty model output is
        accepted, together with the provider the class's own executor reports. Judging
        the quality of that output is not this contract's job, and no fixed literal may
        be reintroduced here: what ties a result to its task is the identity triple, not
        the text.
    """
    if task_kind not in KNOWN_TASK_KINDS:
        raise Refused("RESULT_TASK_KIND_UNKNOWN")
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
    if document["provider"] != provider_for_kind(task_kind):
        raise Refused("RESULT_PROVIDER_MISMATCH")
    if not isinstance(document["output"], str):
        raise Refused("RESULT_OUTPUT_NOT_A_STRING")
    if document["output_sha256"] != output_sha256(document["output"]):
        raise Refused("RESULT_OUTPUT_HASH_MISMATCH")
    if document["accepted"]:
        if task_kind == KIND:
            if document["output"] != EXPECTED_OUTPUT:
                raise Refused("RESULT_ACCEPTED_WITHOUT_THE_EXPECTED_OUTPUT")
        elif not document["output"].strip():
            # A real task may return any text, but "no text at all" is not an answer -
            # accepting it would make an empty transcript indistinguishable from a
            # completed execution.
            raise Refused("RESULT_ACCEPTED_WITH_AN_EMPTY_OUTPUT")
        if not document["response_id"]:
            raise Refused("RESULT_MISSING_RESPONSE_ID")
    if not document["accepted"] and "failure_reason" not in document:
        raise Refused("RESULT_FAILED_WITHOUT_A_REASON")
    return document
