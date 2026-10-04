"""A Builder completion that carries its own review round.

The step this removes
---------------------
Until now the normal path stopped at the Draft pull request: an Owner (or Eason) had to
notice it and open a `C14 · REVIEW · ...` issue before any review ran. That is the last
human hop in

    C01-C12 Issue -> Runtime -> Builder -> Draft PR -> C14 -> C13 -> round decision

and this module is what removes it. A Builder run that created a Draft pull request now
enqueues the C14 half itself, at the moment its own result is sealed - and the C13 half
then follows from the sealed C14 exactly as U7B proved.

Ordering, and why it is the same ordering as C14 -> C13
------------------------------------------------------
The hook runs in `c1_result_pull.complete_after_pull`, BETWEEN the seal and
`Runtime.complete(Builder)`. That is deliberate and it is the whole crash story:

    enqueue C14  ->  crash  ->  restart  ->  same deterministic key  ->  same C14 task
                 ->  then complete the Builder

Completing first would mean a crash in between leaves a finished Builder task whose review
never existed, and nothing would ever come back for it. Enqueueing first uses the Runtime's
own `idempotency_key` as the transaction coordinator, so no second journal is needed.

Where the candidate comes from - and where it must NOT come from
----------------------------------------------------------------
The Builder's `c1_result.json` is sealed by the agent job's post-steps, which run BEFORE
the safe-outputs job creates the pull request. It therefore cannot carry a PR number, and
neither can any amount of reading it. So the candidate is resolved from two things the RUN
itself produced, in this order:

  1. `safe-outputs-items` - gh-aw's own record of what its safe-outputs job actually did.
     The `create_pull_request` entry in it carries the number and URL of the pull request
     that was created, written by the job that created it. This is why nothing is searched,
     inferred from a title, or guessed by recency: the run says what it did.
  2. three read-only GETs against that pull request - its base branch, its head commit, and
     (from that commit) the `application/` tree - plus its changed-file list. Every one of
     them is read through `c1_candidate_reads`, the same definition the Owner's Review issue
     path uses.

A Builder run that created NO pull request is a legitimate outcome, and it is answered as
one: the Builder completes, and no review task exists. What is NOT legitimate - a run whose
record cannot be read, a pull request that is not a Draft, aimed somewhere other than main,
or a candidate whose tree will not resolve - is refused, and the Builder task is left
UNCOMPLETED rather than being completed as if everything were fine.

Delivery is not a verdict, and a review is not a deploy
-------------------------------------------------------
An enqueued C14 means "this candidate is to be reviewed", nothing more. The round's verdict
is decided by the C13/C14 workflow and recorded by `c1_c13c14_review`; nothing here
authorises a merge, a release or a deployment, and the candidate document says so itself
(`authorizes_any_action: false`).
"""
from __future__ import annotations

import json

from c1_candidate_reads import (
    CandidatePrBaseIsNotMain,
    candidate_test_inventory,
    resolve_application_tree,
)
from c1_execution_contract import (
    BUILDER_OWNER_CS,
    C14_REVIEW_KIND,
    REPO,
    RESULT_KIND,
    Refused,
    build_review_task_payload,
    review_request_id,
    review_round_identity,
    task_idempotency_key,
)

# The candidate document's own class. It is not a task contract - it is the answer to "what
# did this Builder run produce", and it is what the round below is derived from.
BUILDER_CANDIDATE_VERSION = 1
BUILDER_CANDIDATE_KIND = "go-builder-candidate-v1"

# gh-aw's own record of the safe outputs its run applied, and the member inside it. Named
# rather than discovered: a scan of "whatever artifacts the run has" would accept a
# differently-shaped one, and the whole point is that the PR number is not inferred.
SAFE_OUTPUTS_ARTIFACT = "safe-outputs-items"
SAFE_OUTPUTS_MEMBER = "safe-output-items.jsonl"
CREATED_PULL_REQUEST = "create_pull_request"

# The cell that reviews a Builder's candidate, and the kind its task carries. Asked of the
# contract at import time only for the constant, which is a name; the boundary itself
# (C14 owns C14_REVIEW_V1) stays where it already is.
CANDIDATE_REVIEW_CELL = "C14"
CANDIDATE_REVIEW_KIND = C14_REVIEW_KIND
# One attempt, like every other class: a second attempt of the same round is a second paid
# model call, and that decision is not a completion hook's.
CANDIDATE_REVIEW_MAX_ATTEMPTS = 1
# The branch a review candidate must be aimed at. The same value the Review issue path uses.
CANDIDATE_BASE_BRANCH = "main"

# ------------------------------------------------------------------- refusals
# The one answer that is not a failure: the Builder legitimately created no pull request.
REASON_NO_CANDIDATE = "NO_CANDIDATE_PR"
REASON_RECORD_MISSING = "BUILDER_SAFE_OUTPUT_RECORD_MISSING"
REASON_RECORD_INVALID = "BUILDER_SAFE_OUTPUT_RECORD_INVALID"
REASON_PR_AMBIGUOUS = "BUILDER_CREATED_MORE_THAN_ONE_PULL_REQUEST"
REASON_PR_NUMBER_INVALID = "BUILDER_CANDIDATE_PR_NUMBER_INVALID"
REASON_PR_URL_INVALID = "BUILDER_CANDIDATE_PR_URL_INVALID"
REASON_PR_FROM_ANOTHER_REPO = "BUILDER_CANDIDATE_PR_IS_FROM_ANOTHER_REPOSITORY"
REASON_NOT_DRAFT = "BUILDER_CANDIDATE_IS_NOT_A_DRAFT"
REASON_WITHOUT_AN_ISSUE = "BUILDER_CANDIDATE_WITHOUT_AN_ORIGINATING_ISSUE"
REASON_IDENTITY = "BUILDER_CANDIDATE_IDENTITY_MISMATCH"
REASON_RUN_ID = "BUILDER_CANDIDATE_RUN_ID_MISMATCH"
REASON_DOCUMENT = "BUILDER_CANDIDATE_DOCUMENT_INVALID"

# Every field the candidate document may carry, and every field it must. A closed set: a
# document with an extra key is refused rather than stored, so "what a candidate is" cannot
# grow a field nobody validated.
CANDIDATE_FIELDS = frozenset({
    "version", "kind",
    "runtime_task_id", "attempt", "execution_request_id", "github_run_id",
    "pr_number", "pr_url",
    "candidate_sha", "base_ref", "draft",
    "application_tree", "machine_inventory",
    "authorizes_any_action",
})
CANDIDATE_REQUIRED = tuple(sorted(CANDIDATE_FIELDS))


def _is_sha1(value) -> bool:
    if not isinstance(value, str) or len(value.strip()) != 40:
        return False
    stripped = value.strip().lower()
    return all(character in "0123456789abcdef" for character in stripped)


# ------------------------------------------- the run's own record of what it created
def read_created_pull_request(client, run_id: int):
    """The pull request THIS run created, or None, or a refusal.

    `client.download_artifact_members` is the existing artifact transport: an absent
    artifact comes back as None. Absent is a refusal here rather than "no pull request",
    because a successful Builder run always uploads this record - treating a missing record
    as an absent candidate would turn a broken read into a silent skip of the review.

    More than one `create_pull_request` entry is impossible under the workflow's own
    `max: 1`, so it is refused rather than resolved by taking the first.
    """
    got = client.download_artifact_members(run_id, SAFE_OUTPUTS_ARTIFACT,
                                          (SAFE_OUTPUTS_MEMBER,))
    if got is None:
        raise Refused(REASON_RECORD_MISSING)
    raw = got["members"][SAFE_OUTPUTS_MEMBER]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise Refused(REASON_RECORD_INVALID) from None

    created = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            raise Refused(REASON_RECORD_INVALID) from None
        if not isinstance(item, dict):
            raise Refused(REASON_RECORD_INVALID)
        if item.get("type") == CREATED_PULL_REQUEST:
            created.append(item)
    if not created:
        return None
    if len(created) > 1:
        raise Refused(REASON_PR_AMBIGUOUS)

    record = created[0]
    number = record.get("number")
    if type(number) is not int or number <= 0:
        raise Refused(REASON_PR_NUMBER_INVALID)
    url = record.get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise Refused(REASON_PR_URL_INVALID)
    repository = record.get("repo")
    if repository is not None and repository != REPO:
        raise Refused(REASON_PR_FROM_ANOTHER_REPO)
    return {"pr_number": number, "pr_url": url}


# ------------------------------------------------------------- the candidate document
def _round_call(candidate, issue_number: int) -> dict:
    """The one Runtime call this candidate justifies, built by the contract.

    Every identity is derived - the round from provenance and the frozen candidate, the
    request id from those two, the idempotency key from the kind and the cell's Lite task
    id. None of them is chosen here, which is what makes a repeated completion free: the
    same Builder result re-processed produces the same key, so the kernel answers with the
    task it already has instead of creating a second round.
    """
    identity = review_round_identity(issue_number, candidate["candidate_sha"])
    request_id = review_request_id(candidate["candidate_sha"], identity["ledger_round_id"])
    payload = build_review_task_payload(
        cell_id=CANDIDATE_REVIEW_CELL,
        external_task_id=identity["c14_task_id"],
        candidate_sha=candidate["candidate_sha"],
        application_tree=candidate["application_tree"],
        issue_number=issue_number,
        review_request_id=request_id,
        ledger_round_id=identity["ledger_round_id"],
        c14_task_id=identity["c14_task_id"],
        c13_task_id=identity["c13_task_id"],
        machine_inventory=candidate.get("machine_inventory"),
        allowed_owner_cs=(CANDIDATE_REVIEW_CELL,),
    )
    return {
        "owner_c": payload["cell_id"],
        "kind": CANDIDATE_REVIEW_KIND,
        "payload": payload,
        "idempotency_key": task_idempotency_key(
            CANDIDATE_REVIEW_KIND, payload["cell_id"], payload["external_task_id"]),
        "max_attempts": CANDIDATE_REVIEW_MAX_ATTEMPTS,
    }


def check_candidate_document(candidate, *, run_id, binding, document) -> dict:
    """Refuse a candidate that is not exactly the run and task it claims to belong to.

    Every check here is one the task list requires, and each of them is a fact the candidate
    cannot establish about itself: the run it came from, the Runtime task that ran it, the
    exact execution identity, and the shape of the pull request it names. Fail closed - a
    candidate that is not this Builder's is never reviewed under this Builder's name.
    """
    if type(candidate) is not dict:
        raise Refused(REASON_DOCUMENT)
    unknown = set(candidate) - CANDIDATE_FIELDS
    if unknown:
        raise Refused(REASON_DOCUMENT + ":UNKNOWN_FIELD:" + ",".join(sorted(unknown)))
    missing = [name for name in CANDIDATE_REQUIRED if name not in candidate]
    if missing:
        raise Refused(REASON_DOCUMENT + ":MISSING_FIELD:" + ",".join(missing))

    if candidate["version"] != BUILDER_CANDIDATE_VERSION or \
            candidate["kind"] != BUILDER_CANDIDATE_KIND:
        raise Refused(REASON_DOCUMENT + ":KIND_OR_VERSION")

    # The Runtime identity triple, from the task that was actually executed and the result
    # that was actually sealed. One source each, compared with each other.
    if candidate["runtime_task_id"] != binding["runtime_task_id"] or \
            candidate["execution_request_id"] != document["execution_request_id"] or \
            candidate["attempt"] != document["attempt"]:
        raise Refused(REASON_IDENTITY)

    # The GitHub run this candidate came from is the run whose artifact was read - and the
    # run the sealed result itself names.
    if candidate["github_run_id"] != run_id or \
            candidate["github_run_id"] != document["github_run_id"]:
        raise Refused(REASON_RUN_ID)

    if type(candidate["pr_number"]) is not int or candidate["pr_number"] <= 0 or \
            not isinstance(candidate["pr_url"], str) or \
            not candidate["pr_url"].startswith("https://"):
        raise Refused(REASON_PR_NUMBER_INVALID)
    if not _is_sha1(candidate["candidate_sha"]):
        raise Refused(REASON_DOCUMENT + ":CANDIDATE_SHA")
    if candidate["base_ref"] != CANDIDATE_BASE_BRANCH:
        raise Refused(REASON_DOCUMENT + ":BASE_REF")
    if candidate["draft"] is not True:
        raise Refused(REASON_NOT_DRAFT)
    if not _is_sha1(candidate["application_tree"]):
        raise Refused(REASON_DOCUMENT + ":APPLICATION_TREE")
    inventory = candidate["machine_inventory"]
    if inventory is not None and (not isinstance(inventory, str) or not inventory.strip()):
        raise Refused(REASON_DOCUMENT + ":MACHINE_INVENTORY")
    # Not "should be false" - must be false, and must be there to be checked. A candidate is
    # a request for a review, and a review is not an authorisation.
    if candidate["authorizes_any_action"] is not False:
        raise Refused(REASON_DOCUMENT + ":AUTHORIZES_ANY_ACTION")
    return candidate


def resolve_builder_candidate(*, client, run_id, builder_request) -> dict:
    """Resolve the candidate a completed Builder run produced, or say there is none.

    Returns one of:

        {"created_pull_request": False, "reason": NO_CANDIDATE_PR}
        {"created_pull_request": True, "candidate": {...}, "review": {...}}

    The provenance is the Builder task's OWN originating issue number. A Builder task that
    cannot name one cannot produce a reproducible round - the round id is derived from it -
    so it is refused rather than reviewed under a made-up name.
    """
    payload = builder_request.get("payload") or {}
    issue_number = payload.get("issue_number")
    if type(issue_number) is not int or issue_number <= 0:
        raise Refused(REASON_WITHOUT_AN_ISSUE)

    created = read_created_pull_request(client, run_id)
    if created is None:
        return {"created_pull_request": False, "reason": REASON_NO_CANDIDATE}

    number = created["pr_number"]
    pull = client.read_pull(number)
    base_ref = pull.get("base_ref")
    if base_ref != CANDIDATE_BASE_BRANCH:
        raise CandidatePrBaseIsNotMain(issue_number, base_ref)
    if pull.get("draft") is not True:
        # The Builder's own safe-output configuration creates drafts; a candidate that is
        # already proposed for review is not the same object, and reviewing it would report
        # a verdict about a decision somebody else already took.
        raise Refused(REASON_NOT_DRAFT)
    candidate_sha = pull.get("head_sha")
    if not _is_sha1(candidate_sha):
        raise Refused(REASON_DOCUMENT + ":CANDIDATE_SHA")
    candidate_sha = candidate_sha.strip().lower()

    candidate = {
        "version": BUILDER_CANDIDATE_VERSION,
        "kind": BUILDER_CANDIDATE_KIND,
        "runtime_task_id": builder_request["runtime_task_id"],
        "attempt": builder_request["attempt"],
        "execution_request_id": builder_request["execution_request_id"],
        "github_run_id": run_id,
        "pr_number": number,
        "pr_url": created["pr_url"],
        "candidate_sha": candidate_sha,
        "base_ref": base_ref,
        "draft": True,
        "application_tree": resolve_application_tree(client, candidate_sha),
        "machine_inventory": candidate_test_inventory(client, number),
        "authorizes_any_action": False,
    }
    return {"created_pull_request": True, "candidate": candidate,
            "review": _round_call(candidate, issue_number)}


# ------------------------------------------------------------------- the hook
def enqueue_review_when_the_builder_has_a_candidate(document, binding, outbox, runtime, *,
                                                    client=None) -> dict | None:
    """The Builder's `on_result_sealed` hook: a sealed Builder result plus its candidate.

    Returns None for anything that is not this executor's business (a review result, a cell
    a Builder does not run for), so wiring this hook onto a shared loop is safe.

    The refusal path is the interesting one. `complete_after_pull` calls this BEFORE
    `Runtime.complete(Builder)` and then completes unconditionally, so the only way to keep
    a Builder whose candidate cannot be established from being completed "as if everything
    were fine" is to raise. But a raise on its own would leave the identity in flight and
    the worker would re-drive it forever - so the identity is SETTLED first, with the reason,
    and then the completion is refused. The Runtime task is left RUNNING and its own stale
    recovery escalates it (`max_attempts = 1`), which is where "a human must look at this"
    belongs; the outbox stops holding work, so one bad candidate cannot stall every other
    cell.
    """
    if document.get("kind") != RESULT_KIND:
        return None
    if binding["owner_c"] not in BUILDER_OWNER_CS:
        # Only a Builder cell's completion asks for a review. This hook is Builder-specific,
        # but the check is here as well as at the wiring, because "which class does this
        # completion belong to" is the one thing that must not depend on where it was wired.
        return None
    if client is None:
        raise Refused("BUILDER_CANDIDATE_NEEDS_A_GITHUB_CLIENT")
    request = outbox.stored_request(binding["runtime_task_id"], binding["expected_attempt"])
    if request is None:
        raise Refused("BUILDER_RESULT_WITHOUT_A_STORED_REQUEST")

    run_id = document["github_run_id"]
    try:
        resolved = resolve_builder_candidate(client=client, run_id=run_id,
                                            builder_request=request)
        if not resolved["created_pull_request"]:
            return {"review_enqueued": False, "reason": resolved["reason"]}
        check_candidate_document(resolved["candidate"], run_id=run_id, binding=binding,
                                document=document)
    except Refused as refusal:
        outbox.abandon(request["execution_request_id"],
                       "BUILDER_CANDIDATE_REFUSED:%s" % refusal.reason)
        raise

    call = resolved["review"]
    task_id = runtime.enqueue(call["owner_c"], call["kind"], call["payload"],
                             idempotency_key=call["idempotency_key"],
                             max_attempts=call["max_attempts"])
    return {"review_enqueued": True, "c14_runtime_task_id": task_id,
            "c14_idempotency_key": call["idempotency_key"],
            "candidate": resolved["candidate"]}
