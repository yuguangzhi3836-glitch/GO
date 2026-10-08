"""Reading a FROZEN candidate out of GitHub: one definition, two callers.

A candidate is a pull request plus the commit it is reviewed at. Two paths ask about one:

    an Owner's `C14 · REVIEW · ...` issue   - the Owner chose the PR and froze the commit
    a Builder run that just opened a PR     - the Builder created it, and its head IS the
                                              commit this round is about

Both need the same three answers - what is the candidate's real base, what is the
`application/` tree of that exact commit, and which test files did the candidate change -
and both must REFUSE rather than repair. So the reading lives here, once, and neither path
restates it; what differs between them is only how the candidate was named, which is the
caller's business and not this module's.

The Formal Review path (`resolve_candidate`) reads the BASE from the live pull request
itself: a review is a review of `base -> head`, so which base that is is a fact of the
candidate and not a privilege a non-`main` candidate has to be granted in writing. An
issue MAY still state the base explicitly; those two lines are then an ASSERTION about the
live PR, not an override, and a mismatch is refused. The Builder path
(`c1_builder_candidate.resolve_builder_candidate`) keeps its own stricter rule - a Builder
product candidate must still be aimed at `main` - and is deliberately unaffected here.

This module performs no I/O. It is handed a `reader` and calls five GET-only methods:

    read_pull(number)             -> {"number","state","draft","base_ref","base_sha",
                                      "head_sha"}
    read_compare(base, head)      -> {"status","merge_base_commit":{"sha"}}
    read_pull_files(number)       -> [{"filename","status"}, ...]
    read_commit_tree(sha)         -> root tree sha
    read_tree(sha)                -> [{"path","type","sha"}, ...]

The Runtime host has two objects that provide them - the consumer's `GitHubIssuesReader`,
which the Formal Review issue path uses, and the shared `GitHubActionsClient`, which the
Builder's own completion path uses - and they are the same endpoints. Naming the shape once
is what lets a caller choose either without a second copy of the checks.
"""
from __future__ import annotations

import re

from c1_execution_contract import (
    Refused,
    review_test_inventory,
    validate_frozen_review_base,
)

# The branch a BUILDER product candidate must be aimed at. A Builder task is dispatched with
# `ref = main` and produces a product candidate destined for the default branch, so a PR
# aimed anywhere else is a different question. The formal REVIEW path below no longer uses
# this value as an admission rule - it freezes the candidate's real base whatever it is -
# and the constant stays because the Builder path still needs it.
REVIEW_BASE_BRANCH = "main"
# The directory whose tree the C13 machine test runs inside. Exactly that entry, and its
# only legitimate type.
APPLICATION_DIR = "application"
TREE_TYPE = "tree"

_CANONICAL_SHA1 = re.compile(r"^[0-9a-f]{40}$")

# ------------------------------------------------------------------- refusals
REASON_PR_NOT_FOUND = "REVIEW_CANDIDATE_PR_NOT_FOUND"
# Not a review refusal any more: the formal review froze whatever base the PR really has.
# It is still the Builder path's own refusal, which is why the name survives.
REASON_PR_BASE_NOT_MAIN = "REVIEW_CANDIDATE_BASE_IS_NOT_MAIN"
REASON_HEAD_MOVED = "REVIEW_CANDIDATE_HEAD_MOVED"
REASON_TREE_UNRESOLVED = "REVIEW_APPLICATION_TREE_UNRESOLVED"
# The issue stated a base and the live PR disagrees with it. An assertion that fails is a
# refusal, never a repair and never a preference for one of the two values.
REASON_BASE_NOT_THE_LIVE_BASE = "REVIEW_CANDIDATE_BASE_MOVED"
REASON_BASE_NOT_ANCESTOR = "REVIEW_FROZEN_BASE_NOT_ANCESTOR"


class CandidateHeadMoved(Refused):
    """The PR's head is no longer the commit this round froze.

    Carries the two commit ids the refusal is made of, so the Evidence line shows which
    commit the round asked for and which one the PR is at now. They are public commit ids,
    not credentials. Nothing is repaired and nothing is inferred: the answer to a moved
    candidate is a NEW round, so that the round a review belongs to is never silently
    redefined.
    """

    def __init__(self, issue_number, candidate_sha, head_sha):
        super().__init__(REASON_HEAD_MOVED)
        self.issue_number = issue_number
        self.candidate_sha = candidate_sha
        self.head_sha = head_sha


class CandidatePrBaseIsNotMain(Refused):
    """The PR is not aimed at the default branch, so it is not a BUILDER candidate.

    Raised by the Builder completion path only. The formal Review path froze the PR's real
    base instead, precisely because a review's candidate is often not aimed at `main`.
    """

    def __init__(self, issue_number, base_ref):
        super().__init__(REASON_PR_BASE_NOT_MAIN)
        self.issue_number = issue_number
        self.base_ref = base_ref


def resolve_candidate(reader, parsed) -> dict:
    """Resolve a frozen candidate against the live PR, or refuse.

    Used by the path where a caller FROZE the commit in advance (a Review issue). The PR is
    read once, and it answers three questions in this order:

      1. is the PR still at the commit this round froze?   (head drift -> refusal)
      2. what IS its base, and does the issue agree?       (assertion -> refusal)
      3. is that base an ancestor of the frozen commit?    (unrelated base -> refusal)

    The base is taken FROM THE PULL REQUEST. A review is a review of `base -> head`, so
    the base is a fact about the candidate; `main` is a common value of that fact, not a
    precondition for being reviewable. When the issue also states the base, its two lines
    are an assertion about the live PR rather than an override, and a mismatch is refused
    instead of being resolved in favour of either side.

    Nothing here follows the PR forward - a head that has moved is a refusal, so a review
    can never be silently re-pointed at work nobody asked to review.
    """
    try:
        pull = reader.read_pull(parsed["candidate_pr_number"])
    except Refused as refusal:
        # A missing PR is the common case and gets its own name rather than the transport's:
        # `#500` was reviewed by nobody because it does not exist.
        if refusal.reason in ("GITHUB_HTTP_404", "PULL_NOT_AN_OBJECT"):
            raise Refused(REASON_PR_NOT_FOUND) from None
        raise
    head_sha = pull.get("head_sha")
    if not isinstance(head_sha, str) or head_sha.lower() != parsed["candidate_sha"]:
        raise CandidateHeadMoved(parsed["issue_number"], parsed["candidate_sha"],
                                 head_sha if isinstance(head_sha, str) else None)
    declared = parsed.get("frozen_base")
    if declared is not None:
        # The issue wrote a base, so that is what it must BE. Not a fallback, not a
        # repair: a mismatch means the round would grade a different range than the one
        # the issue named, and which of the two is "right" is not this module's to pick.
        if (pull.get("base_ref") != declared["ref"]
                or pull.get("base_sha") != declared["sha"]
                or pull.get("number") != declared["pr_number"]):
            raise Refused(REASON_BASE_NOT_THE_LIVE_BASE)
        frozen = declared
    else:
        # No explicit base: freeze the PR's OWN base. A non-`main` base is ordinary here -
        # requiring the Owner to retype it was the defect this replaces.
        frozen = validate_frozen_review_base({
            "ref": pull.get("base_ref"),
            "sha": pull.get("base_sha"),
            "pr_number": pull.get("number"),
        })
    comparison = reader.read_compare(frozen["sha"], parsed["candidate_sha"])
    if (not isinstance(comparison, dict)
            or comparison.get("status") != "ahead"
            or (comparison.get("merge_base_commit") or {}).get("sha") != frozen["sha"]):
        raise Refused(REASON_BASE_NOT_ANCESTOR)
    # The identity the issue produced is the identity that travels: the ingress reads it
    # from here, and from there it enters the C14 payload digest, the wire envelope and
    # the C13 half unchanged.
    parsed["frozen_base"] = frozen
    return pull


def resolve_application_tree(reader, candidate_sha: str) -> str:
    """The `application/` git tree of the FROZEN candidate commit, or a refusal.

    Two reads, both at the frozen commit: its root tree, then the entry named
    `application` inside it. There is no fallback to main's tree, a local checkout or a
    cached value, because all three would make the C13 machine test run against something
    other than the commit the round is about - and a review of the wrong tree that reports
    a verdict is worse than a review that refuses to start.
    """
    try:
        root_tree = reader.read_commit_tree(candidate_sha)
        entries = reader.read_tree(root_tree)
    except Refused:
        raise Refused(REASON_TREE_UNRESOLVED) from None
    for entry in entries:
        if entry.get("path") == APPLICATION_DIR and entry.get("type") == TREE_TYPE:
            sha = entry.get("sha")
            if isinstance(sha, str) and _CANONICAL_SHA1.match(sha.strip().lower()):
                return sha.strip().lower()
    raise Refused(REASON_TREE_UNRESOLVED)


def candidate_test_inventory(reader, pr_number: int):
    """The candidate's own test files, as the C13 machine-test inventory.

    The read is here; WHICH paths count is the contract's `review_test_inventory`, so the
    sandboxing rule on those paths has one definition rather than one per caller.
    """
    try:
        files = reader.read_pull_files(pr_number)
    except Refused:
        return None
    return review_test_inventory(files)
