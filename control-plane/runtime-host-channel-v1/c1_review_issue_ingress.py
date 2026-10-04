"""Formal Review Issue ingress: `C14 · REVIEW · ...` -> Runtime.enqueue(C14_REVIEW_V1).

The last human step this replaces
---------------------------------
Until now a C13/C14 round entered the Runtime only when an operator ran
`deliver_review_round.py` by hand for one named candidate. That is the step this module
removes: the Owner creates an ordinary GitHub issue, and the SAME resident consumer that
already admits Builder work admits this too.

    Owner: C14 · REVIEW · <description>
           Candidate PR: #394
           Candidate SHA: 0cb92ac7900cd177be383a4429a2759007119a10
      -> [ this module ] -> Runtime.enqueue(C14_REVIEW_V1)

Nothing else about the round changes. The C14 executor, the sealed bundle, the
prerequisite gate, the C13 half and the round decision are exactly what U7B proved; this
module stops at "the C14 task entered the Runtime", and every field it fills is derived
rather than asked for.

What the Owner supplies, and what they must NOT have to
-------------------------------------------------------
Two lines. The PR number and the commit being reviewed - and the commit is not optional
detail, it is the whole point: a review that reads "PR #394" and then re-reads the PR's
head on every poll would silently start reviewing a different commit the moment the
branch moved, while still calling it the same round. So the candidate is FROZEN by the
issue, and a PR whose head has moved past it is REFUSED rather than followed.

Everything else - the `application/` tree, the round id, the Lite task ids, the request id
and the machine-test inventory - is derived here. A human-facing form that asked for six
identifiers would be a form nobody fills in correctly, and the identifiers would then be
whatever the human guessed.

Two gates, and they are deliberately not the same gate
------------------------------------------------------
A Builder issue is admitted against `source_anchor == current main`, because a Builder task
is DISPATCHED with `ref = main` and will be executed on whatever main is at that moment.

A Review issue is admitted against `candidate_sha == this PR's head`, because a review's
candidate is BY DEFINITION often not main - that is what makes it a candidate. Reusing the
Builder's current-main gate here would refuse exactly the reviews it exists to run. What
the two share is the shape of the check: a value the issue froze, compared with strict
equality against the value the platform reports now, and a refusal - never a repair - when
they disagree.

Read-only, and only ever read-only
----------------------------------
Four GETs at most per review issue: the pull request, its file list, the frozen commit and
that commit's root tree. No verb but GET, no comment, no label, no state change. The
client lives in the consumer (`GitHubIssuesReader`), which is the only transport this
process has, so this module is a pure parser/planner that a test can drive with a stub.

Out of scope on purpose
-----------------------
Review execution, result adoption, verdicts, round decisions and issue comments are all
later stages and all already exist. This module creates ONE C14 task, and the C13 half
remains something only a sealed, admissible C14 can produce - `enqueue_c13_when_c14_admits`
in `c1_c13c14_review`. An issue cannot create a C13 task however it is written.
"""
from __future__ import annotations

import os
import re

from c1_execution_contract import (
    C14_REVIEW_KIND,
    Refused,
    allowed_owner_cs_for_kind,
    build_review_task_payload,
    canonical,
    canonical_cell_id,
    review_request_id,
    sha256_hex,
    task_idempotency_key,
)
from c1_issue_ingress import (
    CANONICAL_SHA1,
    INGRESS_ENABLED_ENV,
    TITLE_CELL,
    TITLE_SEPARATOR,
    ingress_enabled,
)

# ---------------------------------------------------------------- the issue shape
# The cell and the marker are the two halves of "this is a review request". `REVIEW` is a
# literal and not a task-id shape, because the round's identity is derived from the FROZEN
# CANDIDATE, not typed by the Owner - which is precisely why the Owner cannot get it wrong.
REVIEW_CELL = "C14"
REVIEW_MARKER = "REVIEW"
# The two body lines. Both are required: a PR without a frozen commit is the drift this
# ingress exists to prevent, and a commit without its PR cannot be checked against
# anything.
CANDIDATE_PR_MARKER = "candidate pr:"
CANDIDATE_SHA_MARKER = "candidate sha:"

# The task class this ingress produces, and the cells allowed to own it - asked of the
# contract so that "C14_REVIEW_V1 belongs to C14" has one answer, the same one the
# executor's claim boundary uses.
REVIEW_INGRESS_KIND = C14_REVIEW_KIND
REVIEW_INGRESS_OWNER_CS = allowed_owner_cs_for_kind(REVIEW_INGRESS_KIND)
# One attempt, for the same reason every other class uses one: a second attempt of the
# same review is a second paid model call, and that decision is not an issue scanner's.
REVIEW_INGRESS_MAX_ATTEMPTS = 1

# The PR's base branch must be the default branch. A review round's verdict is a statement
# about a candidate destined for main, and a PR aimed anywhere else is a different question.
REVIEW_BASE_BRANCH = "main"

# `#394` and `394` are both accepted; nothing else is. The number is an identity, not prose.
PR_NUMBER = re.compile(r"^#?([0-9]+)$")
# The directory whose tree the C13 machine test runs inside. Exactly the entry the task
# named, and its only legitimate type.
APPLICATION_DIR = "application"
TREE_TYPE = "tree"

# The machine-test inventory is scoped to the candidate's OWN test files. Paths are
# restricted to that shape and nothing else may appear on the wire: the inventory is
# interpolated into a shell command by the C13 workflow, so a path is only ever accepted
# when it is provably a plain path under this one directory.
REVIEW_TEST_PATH = re.compile(r"^application/tests/[A-Za-z0-9_./-]+\.py$")
MAX_REVIEW_TEST_FILES = 20
# Mirrors the contract's own bound on the field, so a scope that could not be carried is
# never built in the first place.
MAX_INVENTORY_CHARS = 400

# ------------------------------------------------------------------- refusals
REASON_PR_NOT_FOUND = "REVIEW_CANDIDATE_PR_NOT_FOUND"
REASON_PR_BASE_NOT_MAIN = "REVIEW_CANDIDATE_BASE_IS_NOT_MAIN"
REASON_HEAD_MOVED = "REVIEW_CANDIDATE_HEAD_MOVED"
REASON_TREE_UNRESOLVED = "REVIEW_APPLICATION_TREE_UNRESOLVED"


class CandidateHeadMoved(Refused):
    """The PR's head is no longer the commit this issue froze.

    Carries the two commit ids the refusal is made of, so the Evidence line shows which
    commit the Owner asked for and which one the PR is at now. They are public commit ids,
    not credentials. Nothing is repaired and nothing is inferred: the answer to a moved
    candidate is a NEW review issue, so that the round a review belongs to is never
    silently redefined.
    """

    def __init__(self, issue_number, candidate_sha, head_sha):
        super().__init__(REASON_HEAD_MOVED)
        self.issue_number = issue_number
        self.candidate_sha = candidate_sha
        self.head_sha = head_sha


class CandidatePrBaseIsNotMain(Refused):
    """The PR is not aimed at the default branch, so it is not this round's candidate."""

    def __init__(self, issue_number, base_ref):
        super().__init__(REASON_PR_BASE_NOT_MAIN)
        self.issue_number = issue_number
        self.base_ref = base_ref

# ------------------------------------------------------------- the cheap pre-filter
def looks_like_review_issue(issue) -> bool:
    """Cheap pre-filter: is this worth handing to the review parser at all?

    It decides nothing about identity. The marker is what it keys on, NOT the cell, and
    that is deliberate: `C13 · REVIEW · ...` is a request the Owner must not be able to
    make, and a filter that silently dropped it would leave no record of the attempt. It
    passes here and is refused by the parser, by name.

    It is also disjoint from `looks_like_builder_issue` by construction - a Builder title's
    middle segment is a task id and this one's is the literal `REVIEW` - so no issue can be
    planned as both, and no review issue can be malformed Builder work.
    """
    if type(issue) is not dict:
        return False
    if "pull_request" in issue:
        return False
    title = issue.get("title")
    if not isinstance(title, str):
        return False
    parts = [p.strip() for p in TITLE_SEPARATOR.split(title.strip())]
    if len(parts) != 3 or not all(parts):
        return False
    return bool(TITLE_CELL.match(parts[0])) and parts[1].upper() == REVIEW_MARKER


# ------------------------------------------------------------------- the parser
def _read_marked(body: str, marker: str):
    """Every value an explicit `MARKER value` line carries, in order.

    Returns a list of the distinct values found, so the caller can tell "absent" from
    "stated twice and disagreeing" - both refusals, for different reasons, and neither
    resolved by preference.
    """
    found = []
    for raw in body.splitlines():
        line = raw.strip().lstrip("-*+").strip()
        if line.lower().startswith(marker):
            value = line[len(marker):].strip().strip("`").strip()
            if value:
                found.append(value)
    return found


def parse_review_issue(issue) -> dict:
    """Parse one already-open Review issue into the facts a round needs, or refuse.

    Fails closed on everything. In particular the cell must be the review cell: `C13 ·
    REVIEW · ...` is refused by name rather than ignored, because "the Owner tried to
    commission the second half directly" is a fact worth recording, and because a C13 task
    may only ever be produced by an admissible sealed C14.
    """
    if type(issue) is not dict:
        raise Refused("ISSUE_NOT_AN_OBJECT")
    if "pull_request" in issue:
        raise Refused("ISSUE_IS_A_PULL_REQUEST")
    if issue.get("state") != "open":
        raise Refused("ISSUE_NOT_OPEN")

    number = issue.get("number")
    if type(number) is not int or number <= 0:
        raise Refused("ISSUE_NUMBER_INVALID")

    title = issue.get("title")
    if not isinstance(title, str) or not title.strip():
        raise Refused("ISSUE_TITLE_INVALID")
    parts = [p.strip() for p in TITLE_SEPARATOR.split(title.strip())]
    if len(parts) != 3 or not all(parts):
        raise Refused("REVIEW_TITLE_NOT_THREE_SEGMENTS")
    cell, marker, _description = parts
    if not TITLE_CELL.match(cell):
        raise Refused("REVIEW_TITLE_CELL_NOT_FOUND")
    if marker.upper() != REVIEW_MARKER:
        raise Refused("REVIEW_TITLE_MARKER_NOT_FOUND")
    if canonical_cell_id(cell) != REVIEW_CELL:
        # The one control-only cell a review may be commissioned for. A C13 review is not
        # something an issue can start.
        raise Refused("REVIEW_TITLE_CELL_IS_NOT_THE_REVIEW_CELL")

    body = issue.get("body")
    if not isinstance(body, str) or not body.strip():
        raise Refused("ISSUE_BODY_EMPTY")

    pr_values = _read_marked(body, CANDIDATE_PR_MARKER)
    if not pr_values:
        raise Refused("REVIEW_CANDIDATE_PR_NOT_FOUND")
    if len(set(pr_values)) > 1:
        raise Refused("REVIEW_CANDIDATE_PR_AMBIGUOUS")
    match = PR_NUMBER.match(pr_values[0])
    if not match:
        raise Refused("REVIEW_CANDIDATE_PR_INVALID")
    pr_number = int(match.group(1))
    if pr_number <= 0:
        raise Refused("REVIEW_CANDIDATE_PR_INVALID")

    sha_values = _read_marked(body, CANDIDATE_SHA_MARKER)
    if not sha_values:
        raise Refused("REVIEW_CANDIDATE_SHA_NOT_FOUND")
    lowered = sorted({value.lower() for value in sha_values})
    if len(lowered) > 1:
        raise Refused("REVIEW_CANDIDATE_SHA_AMBIGUOUS")
    if not CANONICAL_SHA1.match(lowered[0]):
        raise Refused("REVIEW_CANDIDATE_SHA_INVALID")

    return {"issue_number": number, "candidate_pr_number": pr_number,
            "candidate_sha": lowered[0]}


# ------------------------------------------------------------------ round identity
def round_identity(issue_number: int, candidate_sha: str) -> dict:
    """The round's Ledger/Lite identity, derived from the issue and the FROZEN candidate.

    Deterministic by construction, which is what makes re-polling free: the same issue and
    the same candidate produce the same round, the same two Lite task ids and therefore the
    same Runtime idempotency key, so the kernel answers a repeat with the task it already
    has rather than creating a second one.

    The candidate's first twelve hex characters, not the issue title or a timestamp: a
    second issue raised for a DIFFERENT candidate is a different round even if it describes
    the same PR, and re-raising the same one is the same round.
    """
    if type(issue_number) is not int or issue_number <= 0:
        raise Refused("ISSUE_NUMBER_INVALID")
    if not isinstance(candidate_sha, str) or not CANONICAL_SHA1.match(candidate_sha.lower()):
        raise Refused("REVIEW_CANDIDATE_SHA_INVALID")
    short = candidate_sha.lower()[:12]
    ledger_round_id = "FORMAL-REVIEW-I%d-%s" % (issue_number, short)
    return {
        "ledger_round_id": ledger_round_id,
        "c14_task_id": ledger_round_id + "-C14",
        "c13_task_id": ledger_round_id + "-C13",
    }


# -------------------------------------------------------- resolution (read-only GETs)
def resolve_candidate(reader, parsed) -> dict:
    """Resolve the frozen candidate against the live PR, or refuse.

    The PR is read once and only to answer two questions: is it aimed at the default
    branch, and is its head still the commit the issue froze. Nothing here follows the PR
    forward - a head that has moved is a refusal, so a review can never be silently
    re-pointed at work the Owner did not ask to review.
    """
    try:
        pull = reader.read_pull(parsed["candidate_pr_number"])
    except Refused as refusal:
        # A missing PR is the common case and gets its own name rather than the transport's:
        # `#500` was reviewed by nobody because it does not exist.
        if refusal.reason in ("GITHUB_HTTP_404", "PULL_NOT_AN_OBJECT"):
            raise Refused(REASON_PR_NOT_FOUND) from None
        raise
    base_ref = pull.get("base_ref")
    if base_ref != REVIEW_BASE_BRANCH:
        raise CandidatePrBaseIsNotMain(parsed["issue_number"], base_ref)
    head_sha = pull.get("head_sha")
    if not isinstance(head_sha, str) or head_sha.lower() != parsed["candidate_sha"]:
        raise CandidateHeadMoved(parsed["issue_number"], parsed["candidate_sha"],
                                 head_sha if isinstance(head_sha, str) else None)
    return pull


def resolve_application_tree(reader, candidate_sha: str) -> str:
    """The `application/` git tree of the FROZEN candidate commit, or a refusal.

    Two reads, both at the frozen commit: its root tree, then the entry named
    `application` inside it. There is no fallback to main's tree, a local checkout or a
    cached value, because all three would make the C13 machine test run against something
    other than the commit the Owner asked to review - and a review of the wrong tree that
    reports a verdict is worse than a review that refuses to start.
    """
    try:
        root_tree = reader.read_commit_tree(candidate_sha)
        entries = reader.read_tree(root_tree)
    except Refused:
        raise Refused(REASON_TREE_UNRESOLVED) from None
    for entry in entries:
        if entry.get("path") == APPLICATION_DIR and entry.get("type") == TREE_TYPE:
            sha = entry.get("sha")
            if isinstance(sha, str) and CANONICAL_SHA1.match(sha.lower()):
                return sha.lower()
    raise Refused(REASON_TREE_UNRESOLVED)


def candidate_test_inventory(reader, pr_number: int):
    """The candidate's own test files, as the C13 machine-test inventory.

    `machine_inventory` is not a field the Owner fills in, so the system decides it, and the
    decision that needs no policy of its own is "the tests this candidate changed". The
    alternative - the C13 workflow's declared default - is the entire `application/tests`
    tree: 274 files, including integration, journey and payments suites, none of which is
    run by any other workflow, inside a job with a 40 minute ceiling. Admitting a formal
    review onto that scope would spend a paid execution on a run that cannot finish, and
    would record the resulting failure as a verdict about the candidate.

    So the scope is the candidate's added and modified test paths. Paths that do not match
    that exact shape are dropped rather than passed through - the value reaches a shell
    command in the C13 workflow, and a review ingress that could put an arbitrary string
    there would be handing a candidate's diff a shell. Removed paths are dropped too: a
    file that no longer exists cannot be collected by pytest. The list is bounded by count
    and by the contract's own field limit; when the candidate changes no test at all this
    returns None and the Cell's declared default stands, which is a scope decision the
    workflow already owns.
    """
    try:
        files = reader.read_pull_files(pr_number)
    except Refused:
        return None
    selected = []
    for entry in files:
        if not isinstance(entry, dict):
            continue
        name = entry.get("filename")
        if not isinstance(name, str) or not REVIEW_TEST_PATH.match(name):
            continue
        if entry.get("status") == "removed":
            continue
        selected.append(name)
    selected = sorted(set(selected))[:MAX_REVIEW_TEST_FILES]
    while selected and len(" ".join(selected)) > MAX_INVENTORY_CHARS:
        selected.pop()
    return " ".join(selected) or None


# --------------------------------------------------------------------- planning
def _plan(parsed, *, application_tree, machine_inventory, environ) -> dict:
    identity = round_identity(parsed["issue_number"], parsed["candidate_sha"])
    request_id = review_request_id(parsed["candidate_sha"], identity["ledger_round_id"])
    payload = build_review_task_payload(
        cell_id=REVIEW_CELL,
        external_task_id=identity["c14_task_id"],
        candidate_sha=parsed["candidate_sha"],
        application_tree=application_tree,
        issue_number=parsed["issue_number"],
        review_request_id=request_id,
        ledger_round_id=identity["ledger_round_id"],
        c14_task_id=identity["c14_task_id"],
        c13_task_id=identity["c13_task_id"],
        machine_inventory=machine_inventory,
        allowed_owner_cs=REVIEW_INGRESS_OWNER_CS,
    )
    # Derived from the KIND as well as the task, exactly as the Builder ingress does, so a
    # review round cannot share a Runtime task with anything else that might claim it.
    idempotency_key = task_idempotency_key(
        REVIEW_INGRESS_KIND, payload["cell_id"], payload["external_task_id"])
    enabled = ingress_enabled(environ)
    return {
        "action": "SHADOW_PLAN" if enabled else "DISABLED",
        "enabled": enabled,
        "enqueued": False,
        "issue_number": parsed["issue_number"],
        "candidate_pr_number": parsed["candidate_pr_number"],
        "candidate_sha": parsed["candidate_sha"],
        "application_tree": application_tree,
        "ledger_round_id": identity["ledger_round_id"],
        "machine_inventory": machine_inventory,
        "machine_inventory_source": ("candidate_changed_tests" if machine_inventory
                                     else "workflow_default"),
        "payload_sha256": sha256_hex(canonical(payload)),
        "would_enqueue": {
            "owner_c": payload["cell_id"],
            "kind": REVIEW_INGRESS_KIND,
            "payload": payload,
            "idempotency_key": idempotency_key,
            "max_attempts": REVIEW_INGRESS_MAX_ATTEMPTS,
        },
    }


def plan_review_ingress(issue, *, reader, environ=None) -> dict:
    """Compute the Runtime call this Review issue would produce. Never enqueues.

    There is no Runtime parameter here on purpose, for the same reason the Builder ingress
    has none: this function is not able to enqueue anything, in any configuration.
    """
    parsed = parse_review_issue(issue)
    resolve_candidate(reader, parsed)
    application_tree = resolve_application_tree(reader, parsed["candidate_sha"])
    inventory = candidate_test_inventory(reader, parsed["candidate_pr_number"])
    return _plan(parsed, application_tree=application_tree,
                 machine_inventory=inventory, environ=environ)


def ingest_review(issue, *, reader, runtime=None, environ=None) -> dict:
    """Plan, and enqueue only when explicitly enabled and given a Runtime.

    One C14 task, and only ever one. The C13 half is not this module's business at any
    point: it is created by the review executor from a sealed, admissible C14, and an
    ingress that could enqueue it would make "C13 follows C14" a caller's promise instead of
    a property of the system.
    """
    plan = plan_review_ingress(issue, reader=reader, environ=environ)
    if not plan["enabled"]:
        return plan
    if runtime is None:
        raise Refused("RUNTIME_REQUIRED_WHEN_INGRESS_ENABLED")

    call = plan["would_enqueue"]
    task_id = runtime.enqueue(
        call["owner_c"],
        call["kind"],
        call["payload"],
        idempotency_key=call["idempotency_key"],
        max_attempts=call["max_attempts"],
    )
    result = dict(plan)
    result.update({"action": "ENQUEUED", "enqueued": True, "runtime_task_id": task_id})
    return result


# The single enable switch is the ingress's own, deliberately not a second one: "Runtime
# ingress" is one decision, and two switches would be two answers to it.
ENABLE_SWITCH = INGRESS_ENABLED_ENV


def enabled(environ=None) -> bool:
    """This ingress is enabled exactly when the channel's ingress switch is on."""
    return ingress_enabled(os.environ if environ is None else environ)
