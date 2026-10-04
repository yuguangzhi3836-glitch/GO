"""C01 GitHub Issue consumer: open C01 issues -> Runtime.enqueue(GHAW_BUILDER_V1).

What this is
------------
The last leg of the new path, and only that:

    GitHub open C01 issue -> [ this module ] -> c1_issue_ingress -> Runtime.enqueue()

`c1_issue_ingress` already owns the parser, the payload schema and the idempotency key.
This module deliberately owns none of those: it fetches open issues, decides which ones
are worth handing to the ingress at all, and reports what happened. There is no second
parser and no second de-duplication system here.

Read-only on GitHub
-------------------
Only `GET /repos/<repo>/issues` is ever issued, with no other verb and no other path:
never a comment, never a label, never a state change, never a write of any kind.
`GitHubIssuesReader` hard-codes GET, and the test suite asserts that no other method
and no comment path exists in this file.

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
    plan_ingress,
)

# --------------------------------------------------------------------- topology
CONSUMER_NAME = "go-runtime-host-c01-issue-consumer"
ISSUES_PATH = "/repos/%s/issues" % REPO
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
def looks_like_c01(issue) -> bool:
    """Cheap pre-filter: is this worth handing to the ingress parser at all?

    It decides nothing about identity - it only avoids asking the parser about the
    hundreds of pull requests and other cells that share this tracker. Anything that
    passes is still parsed and validated by `c1_issue_ingress`, which remains the only
    authority on what a C01 task is.
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
    return bool(TITLE_CELL.match(parts[0])) and parts[0].upper() == "C01"


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

    def _get(self, path: str, query: str) -> list:
        """One authenticated GET. The token goes in a header, never in the URL."""
        token = self._token_loader()
        url = "%s%s?%s" % (self._api_base, path, query)
        request = urllib.request.Request(
            url, method="GET",
            headers={"Authorization": "Bearer " + token,
                     "Accept": "application/vnd.github+json",
                     "User-Agent": CONSUMER_NAME,
                     "X-GitHub-Api-Version": API_VERSION})
        with self._opener(request, timeout=self._timeout_s) as response:
            payload = response.read()
        document = json.loads(payload.decode("utf-8"))
        if not isinstance(document, list):
            raise Refused("ISSUES_LISTING_NOT_A_LIST")
        return document

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
    candidates = [issue for issue in issues if looks_like_c01(issue)]
    planned, refused, enqueued = [], [], []
    runtime_error = None

    for issue in candidates[:MAX_CANDIDATES_PER_POLL]:
        try:
            plan = plan_ingress(issue, environ=env)
        except Refused as refusal:
            # malformed / closed / not-C01-after-all: fail closed, and say which.
            refused.append({"issue_number": issue.get("number"),
                            "reason": refusal.reason})
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
        result = ingest(issue, runtime=runtime, environ=env)
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
            "listed": listing["listed"], "pages_fetched": listing["pages_fetched"],
            "candidates": len(candidates), "considered": len(planned),
            "planned": planned, "refused": refused, "enqueued": enqueued,
            "runtime_error": runtime_error}


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
