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

Everything else - the `application/` tree, the round id, the Lite task ids and request id
is derived here. An optional `Machine inventory:` field freezes required test paths,
including unchanged regressions; without it the candidate's changed tests are used.
A human-facing form that asked for six
identifiers would be a form nobody fills in correctly, and the identifiers would then be
whatever the human guessed.

A corrected review, without a second admission path
---------------------------------------------------
`Review revision: 2` is the one OTHER thing an Owner may write, and it exists because of a
failure this channel could otherwise not answer: C14 legitimately returns FAIL, the FAIL is
about the review BRIEF rather than the candidate, a human fixes the brief on the pull
request - and the issue number and the candidate SHA are both unchanged, so the derived
round id still names the round that already ran. Raising the revision is the human saying
"the question changed"; the whole identity moves as one string, so the new round gets its
own C14 task, its own request id and its own Runtime idempotency key.
It is never automatic: no verdict, counter or timer may raise it. It is omitted on every
ordinary round, and its absence means revision 1, which is byte-identical to the identity
this ingress has always produced.

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

The candidate's BASE is not asked for and not assumed to be main: it is read from the live
pull request and frozen, so a stacked or release-branch candidate is reviewable on its own
terms. `Candidate base ref:` / `Candidate base SHA:` may still be written, and are then an
assertion the live PR has to meet; they are no longer the permission slip that non-main
candidates needed, and leaving them out no longer refuses anything.

Read-only, and only ever read-only
----------------------------------
Without an explicit inventory, five GETs at most per review issue: the pull request, the
frozen commit and that commit's root tree, the candidate's file list, and the compare that
proves the frozen base is an ancestor of the frozen commit. Explicit inventories
instead resolve regular files through cached, depth-bounded frozen tree reads.
No verb but GET, no comment, no label, no state change. The
client lives in the consumer (`GitHubIssuesReader`), which is the only transport this
process has, so this module is a pure parser/planner that a test can drive with a stub.

Out of scope on purpose
-----------------------
Review execution, result adoption, verdicts, round decisions and issue comments are all
later stages and all already exist. New rounds create ONE C14 task; their C13 half
requires an admissible sealed C14. Comments are not an admission API and arbitrary
issues cannot request direct C13 execution.
"""
from __future__ import annotations

import os
import re

from c1_review_inventory import explicit_inventory, require_frozen_inventory

from c1_execution_contract import (
    C14_REVIEW_KIND,
    Refused,
    allowed_owner_cs_for_kind,
    build_review_task_payload,
    canonical,
    canonical_cell_id,
    review_request_id,
    review_round_identity,
    sha256_hex,
    task_idempotency_key,
    validate_frozen_review_base,
)
# Reading the candidate is not this module's business: both paths that need it - an Owner's
# Review issue and a Builder run that just opened a PR - use the ONE definition in
# `c1_candidate_reads`, so re-exported here for the callers that already import it from this
# module's namespace.
from c1_candidate_reads import (  # noqa: F401  (re-exported)
    CandidateHeadMoved,
    CandidatePrBaseIsNotMain,
    REASON_PR_BASE_NOT_MAIN,
    REASON_PR_NOT_FOUND,
    REASON_HEAD_MOVED,
    REASON_TREE_UNRESOLVED,
    resolve_application_tree,
    resolve_candidate,
    candidate_test_inventory,
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
# The one OPTIONAL line. Its absence is the historical round (revision 1), which is why it
# is not "revision defaults to 1" in the payload but "revision 1 IS the identity this
# channel has always derived". A plain decimal, no sign, no zero-padding, no leading zeros:
# `1` and `01` must not be two spellings of the same round.
REVIEW_REVISION_MARKER = "review revision:"
REVIEW_REVISION_TEXT = re.compile(r"^[1-9][0-9]*$")

# The task class this ingress produces, and the cells allowed to own it - asked of the
# contract so that "C14_REVIEW_V1 belongs to C14" has one answer, the same one the
# executor's claim boundary uses.
REVIEW_INGRESS_KIND = C14_REVIEW_KIND
REVIEW_INGRESS_OWNER_CS = allowed_owner_cs_for_kind(REVIEW_INGRESS_KIND)
# One attempt, for the same reason every other class uses one: a second attempt of the
# same review is a second paid model call, and that decision is not an issue scanner's.
REVIEW_INGRESS_MAX_ATTEMPTS = 1

# `#394` and `394` are both accepted; nothing else is. The number is an identity, not prose.
PR_NUMBER = re.compile(r"^#?([0-9]+)$")
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

    # Exactly the lines that STATE the marker, empty values included. This is deliberately
    # not `_read_marked`: that one drops an empty value, which for the candidate lines means
    # "the line was not there" and is refused as NOT_FOUND - but for a revision, dropping it
    # would silently read `Review revision:` (blank) as revision 1, and a human who wrote
    # the marker meant to say something. A stated-but-unreadable revision is refused.
    def stated(marker):
        lines = [line.strip().lstrip("-*+").strip() for line in body.splitlines()]
        return [line[len(marker):].strip().strip("`").strip()
                for line in lines if line.lower().startswith(marker)]

    # The OPTIONAL revision. Absent is not "missing input" - it is revision 1, the round this
    # issue has always named. Stated twice with two different values it is refused rather
    # than resolved by preference, exactly as the candidate lines are: an identity a reader
    # has to guess is not an identity. The same value twice is one revision stated twice.
    revision_values = stated(REVIEW_REVISION_MARKER)
    if len(set(revision_values)) > 1:
        raise Refused("REVIEW_REVISION_AMBIGUOUS")
    revision = 1
    if revision_values:
        if not REVIEW_REVISION_TEXT.match(revision_values[0]):
            raise Refused("REVIEW_REVISION_INVALID")
        revision = int(revision_values[0])

    parsed = {"issue_number": number, "candidate_pr_number": pr_number,
              "candidate_sha": lowered[0], "review_revision": revision}
    refs = stated("candidate base ref:")
    shas = stated("candidate base sha:")
    if refs or shas:
        if len(refs) != 1 or len(shas) != 1:
            raise Refused("REVIEW_FROZEN_BASE_INCOMPLETE_OR_AMBIGUOUS")
        # The two lines are an ASSERTION about the live PR: the round then refuses if the
        # PR is not actually based on exactly this. Stating them is an opt-in to that
        # stricter check (and to naming the machine inventory explicitly), NOT a privilege
        # a non-main candidate needs - a PR on any base is reviewable without them.
        parsed["frozen_base"] = validate_frozen_review_base(
            {"ref": refs[0], "sha": shas[0], "pr_number": pr_number})
        parsed["frozen_base_declared"] = True
    return parsed


# ------------------------------------------------------------------ round identity
def round_identity(issue_number: int, candidate_sha: str, revision: int = 1) -> dict:
    """The round's Ledger/Lite identity, derived from provenance and the FROZEN candidate.

    Deterministic by construction, which is what makes re-polling free: the same issue, the
    same candidate and the same revision produce the same round, the same two Lite task ids
    and therefore the same Runtime idempotency key, so the kernel answers a repeat with the
    task it already has rather than creating a second one.

    `revision` is the human's correction of a round's INPUTS, not a retry counter: it is the
    only thing that can make the same issue and the same candidate name a different round,
    and only an Owner editing the issue can set it. Revision 1 is the historical identity.

    The derivation itself lives in the contract, because this is not the only path that names
    a round: a Builder run that just opened a pull request names one the same way, from its
    OWN originating issue and the candidate it produced. Two derivations would be two answers
    to "which round is this".
    """
    return review_round_identity(issue_number, candidate_sha, revision)


# --------------------------------------------------------------------- planning
def _plan(parsed, *, application_tree, machine_inventory, environ,
          inventory_source=None) -> dict:
    identity = round_identity(parsed["issue_number"], parsed["candidate_sha"],
                              parsed.get("review_revision", 1))
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
        frozen_base=parsed.get("frozen_base"),
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
        # Reported so an operator (and the consumer's log line) can see WHICH round this
        # plan is, rather than having to parse the suffix out of the round id. It is not a
        # payload field: the revision is carried by the round id, which is already in the
        # payload, the request id and the idempotency key.
        "review_revision": parsed.get("review_revision", 1),
        "machine_inventory": machine_inventory,
        "machine_inventory_source": (inventory_source or
                                     ("candidate_changed_tests" if machine_inventory
                                      else "workflow_default")),
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

    `resolve_candidate` freezes the candidate's REAL base - whichever branch the PR is
    aimed at - and writes it back into the parsed facts, so the frozen identity exists
    before the payload is built and therefore enters the payload digest, the wire envelope
    and the C13 half without a second derivation.
    """
    parsed = parse_review_issue(issue)
    inventory = explicit_inventory(issue["body"])
    # Only the ASSERTION mode asks for an explicit inventory. A round that auto-froze the
    # candidate's own base keeps the ordinary scope rule (the candidate's changed tests,
    # else the C13 workflow's declared default) - auto-freezing the base must not quietly
    # turn into a second, heavier requirement.
    if parsed.get("frozen_base_declared") and inventory is None:
        raise Refused("REVIEW_FROZEN_BASE_REQUIRES_EXPLICIT_INVENTORY")
    resolve_candidate(reader, parsed)
    application_tree = resolve_application_tree(reader, parsed["candidate_sha"])
    inventory_source = None
    if inventory is not None:
        require_frozen_inventory(reader, application_tree, inventory,
                                 candidate_sha=parsed["candidate_sha"])
        inventory_source = "explicit_frozen_issue_inventory"
    else:
        inventory = candidate_test_inventory(reader, parsed["candidate_pr_number"])
    return _plan(parsed, application_tree=application_tree,
                 machine_inventory=inventory, environ=environ,
                 inventory_source=inventory_source)


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
