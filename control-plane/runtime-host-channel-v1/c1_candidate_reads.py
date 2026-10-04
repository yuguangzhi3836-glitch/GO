"""Reading a FROZEN candidate out of GitHub: one definition, two callers.

A candidate is a pull request plus the commit it is reviewed at. Two paths ask about one:

    an Owner's `C14 · REVIEW · ...` issue   - the Owner chose the PR and froze the commit
    a Builder run that just opened a PR     - the Builder created it, and its head IS the
                                              commit this round is about

Both need the same three answers - is the PR aimed at the default branch, what is the
`application/` tree of that exact commit, and which test files did the candidate change -
and both must REFUSE rather than repair. So the reading lives here, once, and neither path
restates it; what differs between them is only how the candidate was named, which is the
caller's business and not this module's.

This module performs no I/O. It is handed a `reader` and calls four GET-only methods:

    read_pull(number)          -> {"number","state","draft","base_ref","head_sha"}
    read_pull_files(number)    -> [{"filename","status"}, ...]
    read_commit_tree(sha)      -> root tree sha
    read_tree(sha)             -> [{"path","type","sha"}, ...]

The Runtime host has two objects that provide them - the consumer's `GitHubIssuesReader`,
which the Formal Review issue path uses, and the shared `GitHubActionsClient`, which the
Builder's own completion path uses - and they are the same four endpoints. Naming the
shape once is what lets a caller choose either without a second copy of the checks.
"""
from __future__ import annotations

import re

from c1_execution_contract import (
    Refused,
    review_test_inventory,
)

# The PR's base branch must be the default branch. A round's verdict is a statement about a
# candidate destined for main, and a PR aimed anywhere else is a different question.
REVIEW_BASE_BRANCH = "main"
# The directory whose tree the C13 machine test runs inside. Exactly that entry, and its
# only legitimate type.
APPLICATION_DIR = "application"
TREE_TYPE = "tree"

_CANONICAL_SHA1 = re.compile(r"^[0-9a-f]{40}$")

# ------------------------------------------------------------------- refusals
REASON_PR_NOT_FOUND = "REVIEW_CANDIDATE_PR_NOT_FOUND"
REASON_PR_BASE_NOT_MAIN = "REVIEW_CANDIDATE_BASE_IS_NOT_MAIN"
REASON_HEAD_MOVED = "REVIEW_CANDIDATE_HEAD_MOVED"
REASON_TREE_UNRESOLVED = "REVIEW_APPLICATION_TREE_UNRESOLVED"


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
    """The PR is not aimed at the default branch, so it is not this round's candidate."""

    def __init__(self, issue_number, base_ref):
        super().__init__(REASON_PR_BASE_NOT_MAIN)
        self.issue_number = issue_number
        self.base_ref = base_ref


def resolve_candidate(reader, parsed) -> dict:
    """Resolve a frozen candidate against the live PR, or refuse.

    Used by the path where a caller FROZE the commit in advance (a Review issue). The PR is
    read once and only to answer two questions: is it aimed at the default branch, and is
    its head still the commit that was frozen. Nothing here follows the PR forward - a head
    that has moved is a refusal, so a review can never be silently re-pointed at work
    nobody asked to review.
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
