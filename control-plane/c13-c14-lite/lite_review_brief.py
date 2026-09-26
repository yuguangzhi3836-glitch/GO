"""The review brief: the task the candidate was answering, resolved read-only.

Why this module exists
----------------------
By the time of the first real Review E2E both cells could see WHAT changed - the frozen
change surface, the candidate's own first-parent diff, the authoritative rule text and the
machine evidence - but neither could see WHAT WAS ASKED FOR. A reviewer that only knows the
answer can only grade against its own idea of best practice, which is how an acceptable
candidate gets sent back for findings the original task never asked about.

So the brief is the candidate's associated Pull Request, frozen as **GitHub's own raw
facts** - number, title, body, base/head refs, head sha, merge commit sha, state, merged_at
and the PR URL. No model summarises it, nothing is invented, and the URL is navigation only:
it is not an authority and nothing is verified through it.

Matching is deterministic and refuses to guess. A candidate SHA must equal a pull request's
``head.sha`` or its ``merge_commit_sha``, and **exactly one** pull request must match:

* zero matches  -> ``REVIEW_BRIEF_PR_NOT_FOUND`` (there is no task to grade)
* two or more   -> ``REVIEW_BRIEF_PR_AMBIGUOUS`` (grading the wrong task is worse than refusing)

Never: guess by title, by recency, by branch name, or by taking the first result.

What this module deliberately does NOT do: no spec version, no authority root, no witness, no
signature and no second hash registry. The brief is one more field of the facts, so the
existing facts digest (``input_sha256``) binds it - a hash wrapped in another hash would be
one more thing to keep in step and would answer no question the facts digest does not.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from lite_canonical import is_git_sha

SCHEMA_VERSION = "go.c13c14.lite.review_brief.v1"

#: How the candidate SHA was found on the pull request. Recorded because it is a fact about
#: the lookup, not an interpretation of it.
MATCHED_BY_HEAD = "head_sha"
MATCHED_BY_MERGE = "merge_commit_sha"

#: The machine codes a refused lookup may carry. Each one is a different real condition.
PR_NOT_FOUND = "REVIEW_BRIEF_PR_NOT_FOUND"
PR_AMBIGUOUS = "REVIEW_BRIEF_PR_AMBIGUOUS"
PR_UNREADABLE = "REVIEW_BRIEF_UNREADABLE"
PR_INVALID = "REVIEW_BRIEF_INVALID"

FAILURE_REASONS = (PR_NOT_FOUND, PR_AMBIGUOUS, PR_UNREADABLE, PR_INVALID)

#: The fields frozen from the pull request, in the order they are reported. Deliberately a
#: fixed list: a brief whose shape drifts with the API's own additions is not a frozen brief.
BRIEF_FIELDS = (
    "number",
    "title",
    "body",
    "base_ref",
    "head_ref",
    "head_sha",
    "merge_commit_sha",
    "state",
    "merged_at",
    "html_url",
)

#: One page is requested; a full page means uniqueness could not be established, which is a
#: refusal rather than a guess. There is no paging loop because the answer this endpoint gives
#: for a head or a merge commit is one PR, and a repository with 100+ PRs on a single commit
#: would need its own decision - not a silent truncation.
PAGE_SIZE = 100


class BriefFetchFailed(Exception):
    """One read-only commit -> pull requests read did not produce a payload."""

    def __init__(self, path: str, *, status=None, detail: str = ""):
        super().__init__(detail or path)
        self.path = path
        self.status = status
        self.detail = detail or path


def _text(value) -> str:
    """A string field as GitHub reported it, with a non-string replaced by empty."""
    return value if isinstance(value, str) else ""


def brief_from_pull(pull: dict, matched_by: str) -> dict:
    """Freeze one pull request into the brief the reviewers receive.

    Only GitHub's own fields, copied. ``matched_by`` says which of the candidate's two
    possible identities was found (a PR head SHA, or the merge commit SHA of a merged PR).
    """
    inside = {
        "number": pull.get("number") if isinstance(pull.get("number"), int) else None,
        "title": _text(pull.get("title")),
        "body": _text(pull.get("body")),
        "base_ref": _text((pull.get("base") or {}).get("ref")),
        "head_ref": _text((pull.get("head") or {}).get("ref")),
        "head_sha": _text((pull.get("head") or {}).get("sha")),
        "merge_commit_sha": _text(pull.get("merge_commit_sha")),
        "state": _text(pull.get("state")),
        "merged_at": pull.get("merged_at") if isinstance(pull.get("merged_at"), str) else None,
        "html_url": _text(pull.get("html_url")),
    }
    return {**{field: inside[field] for field in BRIEF_FIELDS}, "matched_by": matched_by}


def match(pulls, candidate_sha: str):
    """``(matched_by, pull)`` for the one pull request this candidate SHA belongs to.

    Returns ``None`` for "not found". Raises :class:`BriefFetchFailed` with
    ``REVIEW_BRIEF_PR_AMBIGUOUS`` when more than one pull request matches, because two
    candidate pull requests are two different tasks and only one of them can be graded.
    """
    matches, seen = [], set()
    for pull in pulls:
        if not isinstance(pull, dict):
            continue
        number = pull.get("number")
        head_sha = (pull.get("head") or {}).get("sha")
        merge_sha = pull.get("merge_commit_sha")
        if head_sha == candidate_sha:
            matched_by = MATCHED_BY_HEAD
        elif merge_sha == candidate_sha:
            matched_by = MATCHED_BY_MERGE
        else:
            continue
        # The same pull request can only be one task, so identity is de-duplicated by number.
        # Distinct numbers are left alone: that is a real ambiguity, not a duplicate.
        key = number if isinstance(number, int) else id(pull)
        if key in seen:
            continue
        seen.add(key)
        matches.append((matched_by, pull))

    if not matches:
        return None
    if len(matches) > 1:
        raise BriefFetchFailed(
            "commit/%s/pulls" % candidate_sha,
            detail="REVIEW_BRIEF_PR_AMBIGUOUS: %d pull requests match (%s)"
                   % (len(matches), ", ".join(str(pull.get("number")) for _, pull in matches)),
        )
    return matches[0]


def resolve(candidate_sha: str, list_pulls) -> dict:
    """Resolve the brief record, or say deterministically why we cannot.

    ``list_pulls(candidate_sha) -> list`` is injected, so the whole rule is exercisable
    offline; the HTTP version is :func:`github_pull_reader`. Every failure returns a record -
    this function never raises for a lookup condition, because the caller has to be able to
    *record* the refusal and stop the round before any AI call.
    """
    record = {
        "schema_version": SCHEMA_VERSION,
        "status": "BLOCKED",
        "reason": None,
        "detail": "",
        "candidate_sha": candidate_sha,
        "matched_by": None,
        "pull_request": None,
        "blocking_issues": [],
    }

    def blocked(reason: str, detail: str = "") -> dict:
        record["reason"] = reason
        record["detail"] = detail
        record["blocking_issues"] = [f"{reason}: {detail}" if detail else reason]
        return record

    if not is_git_sha(candidate_sha):
        return blocked(PR_INVALID, "the candidate is not a 40-hex commit sha")

    try:
        pulls = list_pulls(candidate_sha)
    except BriefFetchFailed as error:
        reason = PR_AMBIGUOUS if PR_AMBIGUOUS in error.detail else PR_UNREADABLE
        return blocked(reason, error.detail)
    except Exception as error:  # noqa: BLE001 - any transport failure is a closed door
        return blocked(PR_UNREADABLE, f"{type(error).__name__}")

    if not isinstance(pulls, list):
        return blocked(PR_INVALID, "the commit -> pull requests response is not a list")
    if len(pulls) >= PAGE_SIZE:
        return blocked(
            PR_AMBIGUOUS,
            "a full page of %d associated pull requests was returned, so uniqueness cannot "
            "be established" % PAGE_SIZE,
        )

    try:
        found = match(pulls, candidate_sha)
    except BriefFetchFailed as error:
        return blocked(PR_AMBIGUOUS, error.detail.split(": ", 1)[-1])

    if found is None:
        return blocked(
            PR_NOT_FOUND,
            "no pull request has this commit as its head sha or as its merge commit sha",
        )

    matched_by, pull = found
    brief = brief_from_pull(pull, matched_by)
    if not isinstance(brief["number"], int) or not brief["head_sha"]:
        return blocked(PR_INVALID, "the matched pull request has no number or head sha")
    record["status"] = "OK"
    record["reason"] = None
    record["detail"] = ""
    record["matched_by"] = matched_by
    record["pull_request"] = brief
    record["blocking_issues"] = []
    return record


def github_pull_reader(repository: str, token: str, *, timeout: int = 60):
    """``list_pulls`` over the GitHub commit -> pull requests API - read-only.

    One GET and nothing else: no new service, no new credential, no new permission scope.
    The endpoint is GitHub's own association of a commit with pull requests; nothing here
    infers the association from a title, a branch name or a timestamp.
    """
    if not repository:
        raise ValueError("repository is required")
    if not token:
        raise ValueError("token is required")

    def list_pulls(candidate_sha: str):
        path = "commits/%s/pulls" % candidate_sha
        url = ("https://api.github.com/repos/%s/%s?per_page=%d"
               % (repository, path, PAGE_SIZE))
        request = urllib.request.Request(url, headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "go-c13c14-lite-review-brief",
        })
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise BriefFetchFailed(path, status=error.code,
                                   detail="HTTP %d for %s" % (error.code, path)) from error
        except Exception as error:  # noqa: BLE001 - any transport failure is closed
            raise BriefFetchFailed(path, detail="%s for %s" % (type(error).__name__, path)) from error

    return list_pulls
