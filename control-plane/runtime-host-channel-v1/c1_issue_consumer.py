"""Builder GitHub Issue consumer: open C01-C12 issues -> Runtime.enqueue(GHAW_BUILDER_V1).

What this is
------------
The last leg of the new path, and only that:

    GitHub open C01-C12 issue -> [ this module ] -> c1_issue_ingress -> Runtime.enqueue()

One consumer for twelve cells, never twelve consumers. The cell is read from the issue
title and carried into the task, but nothing about fetching, planning or de-duplicating is
per-cell - so a consumer per cell would be twelve copies of one loop with a different
constant in it, which is the shape this channel keeps refusing.

`c1_issue_ingress` already owns the parser, the payload schema and the idempotency key.
This module deliberately owns none of those: it fetches open issues, decides which ones
are worth handing to the ingress at all, and reports what happened. There is no second
parser and no second de-duplication system here.

Read-only on GitHub
-------------------
Only two GETs are ever issued - `GET /repos/<repo>/issues` and `GET /repos/<repo>/commits/main`
- with no other verb, no other path, and never a comment, a label, a state change or a write
of any kind. `GitHubIssuesReader` hard-codes GET, and the test suite asserts that no other
method and no comment path exists in this file.

One poll, one source snapshot
-----------------------------
A poll reads the default branch's head ONCE, before it reads the tracker, and admits every
candidate in that poll against that one value. Two reasons, and the second is the one that
matters: a poll must not cost one extra request per issue, and every candidate in a single
tick must be judged against the same snapshot - otherwise the reported plan would describe
no one state of the repository.

If that read does not succeed, the poll reports `SOURCE_HEAD_LOOKUP_FAILED` and does nothing
else: nothing is planned, no Runtime is constructed and nothing is enqueued. There is no
fallback to a remembered main, a local checkout or the issue's own claim, because each of
those would silently admit a task against a source nobody verified.

Stateless by design, on purpose
-------------------------------
The consumer keeps **no local record of what it has already seen**. Idempotency is the
Runtime's own: the ingress derives `idempotency_key` from `(kind, cell, external_task_id)` and
the kernel's UNIQUE constraint turns a repeat into "here is the task id you already
have". A local "seen" store would be a second source of truth that can drift, go stale
or be lost on restart, and it is exactly the kind of duplicate the project's own
proportionality principle says not to add. So re-polling the same issue is not merely
harmless, it is the mechanism.

The cost is one `enqueue` call per open C01 issue per poll, which the kernel answers
without creating anything. That is deliberate and is bounded by
`MAX_CANDIDATES_PER_POLL`.

Disabled by default
-------------------
The enable switch is the ingress's own `C01_RUNTIME_INGRESS_ENABLED` - one switch, not
two. While it is off, this consumer still polls, parses and reports the task it *would*
create, and never touches the Runtime: `ingest()` is not reachable from the shadow path,
and the Runtime is not even constructed. On top of that the systemd unit shipped with
this module is not enabled, so there are two independent reasons nothing happens until
someone decides otherwise.

`--check` neither calls the network nor imports the Runtime kernel: it reports what the
installed configuration is capable of, not what it is doing.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

from c1_execution_contract import REPO, Refused, canonical
from c1_github_actions_client import (
    API_BASE,
    API_VERSION,
    HTTP_TIMEOUT_S,
    TOKEN_FILE_ENV,
    configured_token_loader,
)
from c1_issue_ingress import (
    INGRESS_ENABLED_ENV,
    TITLE_CELL,
    TITLE_SEPARATOR,
    ingress_enabled,
    ingest,
    is_builder_cell,
    plan_ingress,
    require_current_source_anchor,
)

# --------------------------------------------------------------------- topology
CONSUMER_NAME = "go-runtime-host-c01-issue-consumer"
ISSUES_PATH = "/repos/%s/issues" % REPO
# The default branch's head, read once per poll. This is the value every candidate in that
# poll is admitted against, and the one the Builder workflow will re-check for itself.
SOURCE_HEAD_PATH = "/repos/%s/commits/main" % REPO
# The Runtime kernel and its database, as installed on the Runtime Host.
RUNTIME_DIR = "/opt/go/c1-c14-runtime"
RUNTIME_DB = "/var/lib/go-c-runtime/runtime.db"

# One poll reads a bounded number of pages, newest first. `listed` is reported so a
# listing larger than this bound is visible rather than silently dropped.
DEFAULT_PAGES = 3
PER_PAGE = 100
MAX_PAGES = 10
# One poll considers at most this many C01-shaped issues, so a single tick can never
# walk an unbounded number of candidates.
MAX_CANDIDATES_PER_POLL = 10

# The poll interval of the resident loop. Bounded: a typo must not turn into a hot loop.
INTERVAL_ENV = "C01_ISSUE_CONSUMER_INTERVAL_S"
DEFAULT_INTERVAL_S = 60
MIN_INTERVAL_S = 5
MAX_INTERVAL_S = 3600


def poll_interval_s(environ=None) -> int:
    """The configured poll interval, clamped, defaulting to 60 seconds."""
    env = os.environ if environ is None else environ
    raw = env.get(INTERVAL_ENV)
    if raw is None or not str(raw).strip():
        return DEFAULT_INTERVAL_S
    try:
        value = int(str(raw).strip())
    except ValueError:
        return DEFAULT_INTERVAL_S
    return max(MIN_INTERVAL_S, min(MAX_INTERVAL_S, value))


# --------------------------------------------------------------------- filtering
def looks_like_builder_issue(issue) -> bool:
    """Cheap pre-filter: is this worth handing to the ingress parser at all?

    It decides nothing about identity - it only avoids asking the parser about the
    hundreds of pull requests and other cells that share this tracker. Anything that
    passes is still parsed and validated by `c1_issue_ingress`, which remains the only
    authority on what a Builder task is.

    The title's first segment is a cell, and "the cells the Builder serves" is asked of
    the contract rather than restated here, so C13/C14 fall out at the cheapest possible
    point by the same answer that excludes them everywhere else. This is a speed filter,
    not a gate: the parser refuses them again, and the Runtime's claim filter refuses
    them a third time.
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
    # Asked of the ingress rather than reimplemented here: "is this a Builder cell" has
    # one answer, and this module is not where it is decided.
    return bool(TITLE_CELL.match(parts[0])) and is_builder_cell(parts[0])


# ------------------------------------------------------------------ read-only client
class GitHubIssuesReader:
    """The only GitHub access this consumer has: list open issues, GET, nothing else.

    `opener` is injected so tests exercise the real request-building code path with a
    recorded transport instead of a live socket.
    """

    def __init__(self, *, token_loader=None, opener=None, api_base=API_BASE,
                 per_page=PER_PAGE, timeout_s=HTTP_TIMEOUT_S):
        self._token_loader = token_loader or configured_token_loader()
        self._opener = opener or urllib.request.urlopen
        self._api_base = api_base
        self._per_page = per_page
        self._timeout_s = timeout_s

    def _get_json(self, path: str, query: str = ""):
        """One authenticated GET. The token goes in a header, never in the URL."""
        token = self._token_loader()
        url = "%s%s%s" % (self._api_base, path, ("?" + query) if query else "")
        request = urllib.request.Request(
            url, method="GET",
            headers={"Authorization": "Bearer " + token,
                     "Accept": "application/vnd.github+json",
                     "User-Agent": CONSUMER_NAME,
                     "X-GitHub-Api-Version": API_VERSION})
        with self._opener(request, timeout=self._timeout_s) as response:
            payload = response.read()
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise Refused("GITHUB_RESPONSE_NOT_JSON") from None

    def _get(self, path: str, query: str) -> list:
        document = self._get_json(path, query)
        if not isinstance(document, list):
            raise Refused("ISSUES_LISTING_NOT_A_LIST")
        return document

    def read_current_source(self) -> str:
        """The default branch's head SHA, or a refusal. GET, and only GET.

        This is the second read-only path this consumer has, and it exists so that
        admission can be about the CURRENT tree rather than about whatever an issue
        happens to claim. It is deliberately read ONCE per poll by the caller, not once
        per issue: one poll judges every candidate against one snapshot.

        Everything the platform can hand back that is not a canonical 40-hex commit id -
        another object shape, a missing `sha`, a differently-cased or truncated value -
        is a refusal. Nothing here falls back to a remembered value.
        """
        document = self._get_json(SOURCE_HEAD_PATH)
        if not isinstance(document, dict):
            raise Refused("SOURCE_HEAD_NOT_AN_OBJECT")
        return require_current_source_anchor(document.get("sha"))

    def list_open_issues(self, *, pages: int = DEFAULT_PAGES) -> dict:
        """Read open issues, newest first, bounded to `pages` pages."""
        if type(pages) is not int or pages < 1 or pages > MAX_PAGES:
            raise Refused("PAGES_OUT_OF_RANGE")
        issues = []
        fetched = 0
        for page in range(1, pages + 1):
            query = "state=open&per_page=%d&page=%d&sort=created&direction=desc" % (
                self._per_page, page)
            batch = self._get(ISSUES_PATH, query)
            fetched += 1
            issues.extend(batch)
            if len(batch) < self._per_page:
                break
        return {"issues": issues, "pages_fetched": fetched, "listed": len(issues)}


# ------------------------------------------------------------------------- polling
def poll_once(*, reader, runtime=None, runtime_factory=None, environ=None,
              pages=DEFAULT_PAGES) -> dict:
    """One poll. Never writes to GitHub; only enqueues when the ingress is enabled."""
    env = os.environ if environ is None else environ
    enabled = ingress_enabled(env)

    # ONE source snapshot, taken before the tracker is read at all and then reused for
    # every candidate in this poll. Two independent reasons, both load-bearing:
    #   * traffic - one extra GET per issue would turn a poll into N+1 requests;
    #   * determinism - every candidate in one tick must be judged against the same
    #     value, or two issues in the same poll could be admitted against two different
    #     mains and the reported plan would describe no single snapshot.
    # Nothing is planned, and no Runtime is reached, unless this read succeeds.
    try:
        current_source_anchor = reader.read_current_source()
    except Refused as refusal:
        return {"verb": "c01-issue-consumer-poll", "status": "SOURCE_HEAD_LOOKUP_FAILED",
                "reason": refusal.reason, "enabled": enabled}
    except urllib.error.HTTPError as error:
        return {"verb": "c01-issue-consumer-poll", "status": "SOURCE_HEAD_LOOKUP_FAILED",
                "reason": "HTTP_%d" % error.code, "enabled": enabled}
    except Exception as error:                          # noqa: BLE001 - reported, not raised
        return {"verb": "c01-issue-consumer-poll", "status": "SOURCE_HEAD_LOOKUP_FAILED",
                "reason": type(error).__name__, "enabled": enabled}

    try:
        listing = reader.list_open_issues(pages=pages)
    except Refused as refusal:
        return {"verb": "c01-issue-consumer-poll", "status": "LISTING_REFUSED",
                "reason": refusal.reason, "enabled": enabled}
    except urllib.error.HTTPError as error:
        # Never the response body and never the URL's headers: only what is needed to
        # tell "not authorised" from "not found" from "the service is unhappy".
        return {"verb": "c01-issue-consumer-poll", "status": "LISTING_FAILED",
                "reason": "HTTP_%d" % error.code, "enabled": enabled}
    except Exception as error:                          # noqa: BLE001 - reported, not raised
        return {"verb": "c01-issue-consumer-poll", "status": "LISTING_FAILED",
                "reason": type(error).__name__, "enabled": enabled}

    issues = listing["issues"]
    candidates = [issue for issue in issues if looks_like_builder_issue(issue)]
    planned, refused, enqueued = [], [], []
    runtime_error = None

    for issue in candidates[:MAX_CANDIDATES_PER_POLL]:
        try:
            plan = plan_ingress(issue, current_source_anchor=current_source_anchor,
                                environ=env)
        except Refused as refusal:
            # malformed / closed / not-C01-after-all / written against another source:
            # fail closed, and say which. The freshness refusal carries the two commit ids
            # it was made of, so the line shows why rather than only that.
            refused.append(_refusal_entry(issue, refusal))
            continue

        call = plan["would_enqueue"]
        entry = {"issue_number": plan["issue_number"],
                 "external_task_id": plan["external_task_id"],
                 "idempotency_key": call["idempotency_key"],
                 "payload_sha256": plan["payload_sha256"]}
        planned.append(entry)
        if not enabled:
            continue

        if runtime is None and runtime_factory is not None:
            runtime = runtime_factory()
        if runtime is None:
            # Disabled-by-configuration cannot reach here; a missing Runtime while
            # enabled is reported once and stops the enqueue leg rather than
            # pretending to have done something.
            runtime_error = "RUNTIME_UNAVAILABLE"
            continue
        result = ingest(issue, current_source_anchor=current_source_anchor,
                        runtime=runtime, environ=env)
        enqueued.append(dict(entry, runtime_task_id=result["runtime_task_id"]))

    # The status says what the poll actually did, most informative first: a missing
    # Runtime outranks the switch, the switch outranks an empty listing, and an empty
    # listing is a normal outcome rather than a failure.
    if runtime_error:
        status = "RUNTIME_UNAVAILABLE"
    elif not enabled:
        status = "DISABLED"
    elif not candidates:
        status = "NO_CANDIDATE"
    else:
        status = "PASS"
    return {"verb": "c01-issue-consumer-poll", "status": status, "enabled": enabled,
            "current_source_anchor": current_source_anchor,
            "listed": listing["listed"], "pages_fetched": listing["pages_fetched"],
            "candidates": len(candidates), "considered": len(planned),
            "planned": planned, "refused": refused, "enqueued": enqueued,
            "runtime_error": runtime_error}


def _refusal_entry(issue, refusal) -> dict:
    """One refused candidate, with whatever the refusal was made of.

    The base entry is what every refusal has always reported. A source-freshness refusal
    additionally reports the issue's own anchor and the snapshot it was compared with, so
    the operator reading a shadow poll can see a stale historical issue for what it is
    without having to go and look the issue up.
    """
    entry = {"issue_number": issue.get("number"), "reason": refusal.reason}
    for name in ("parsed_source_anchor", "current_source_anchor"):
        value = getattr(refusal, name, None)
        if value is not None:
            entry[name] = value
    return entry


def default_runtime_factory():
    """Build the Runtime from the installed kernel. Only ever called when enabled.

    The kernel is imported here rather than at module import time so that a disabled
    consumer - and `--check` - never touch the installed Runtime at all.
    """
    import importlib
    if RUNTIME_DIR not in sys.path:
        sys.path.insert(0, RUNTIME_DIR)
    return importlib.import_module("runtime").Runtime(RUNTIME_DB)


# ------------------------------------------------------------------------ status
def check(environ=None, *, token_loader=None) -> dict:
    """Report capability, offline: no network call, no Runtime import, no enqueue."""
    env = os.environ if environ is None else environ
    enabled = ingress_enabled(env)
    credential, reason = "present", None
    try:
        loader = token_loader or configured_token_loader()
        loader()
    except Refused as refusal:
        credential, reason = "absent", refusal.reason
    except Exception as error:                          # noqa: BLE001 - reported as a state
        credential, reason = "absent", type(error).__name__
    # Fail closed: a consumer without a usable credential can only fail every poll, so
    # it reports itself as blocked rather than as ready. `--check` exits non-zero for
    # that state, which is what makes the unit's ExecStartPre meaningful.
    status = "READY" if credential == "present" else "BLOCKED_NO_CREDENTIAL"
    return {"verb": "c01-issue-consumer-check", "status": status,
            "enabled": enabled, "enable_switch": INGRESS_ENABLED_ENV,
            "credential": credential, "credential_reason": reason,
            "token_path_env": TOKEN_FILE_ENV,
            "repo": REPO, "issues_endpoint": ISSUES_PATH,
            "source_head_endpoint": SOURCE_HEAD_PATH,
            "source_freshness": "issue source_anchor must equal the current main",
            "github_access": "GET only", "interval_s": poll_interval_s(env),
            "pages": DEFAULT_PAGES, "max_candidates_per_poll": MAX_CANDIDATES_PER_POLL,
            "runtime_dir": RUNTIME_DIR, "runtime_db": RUNTIME_DB,
            "runtime_imported": "runtime" in sys.modules,
            "meaning": "Capability report only; no GitHub call and no Runtime access."}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    mode = argv[0] if argv else ""
    if mode == "--check":
        report = check()
        print(canonical(report))
        return 0 if report["status"] == "READY" else 1
    if mode == "--once":
        try:
            result = poll_once(reader=GitHubIssuesReader(),
                               runtime_factory=default_runtime_factory)
        except Refused as refusal:
            result = {"verb": "c01-issue-consumer-poll", "status": "REFUSED",
                      "reason": refusal.reason}
        print(canonical(result))
        return 0
    if mode == "":
        interval = poll_interval_s()
        while True:
            try:
                result = poll_once(reader=GitHubIssuesReader(),
                                   runtime_factory=default_runtime_factory)
            except Refused as refusal:
                result = {"verb": "c01-issue-consumer-poll", "status": "REFUSED",
                          "reason": refusal.reason}
            print(canonical(result), flush=True)
            time.sleep(interval)
    print("usage: c1_issue_consumer.py [--check|--once]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
