"""Per-cell C2-C14 ingress using the existing parser, queue and idempotency key.

Only explicitly configured task authors are eligible. Reserved cell containers and
comments are not tasks: publish an issue with the existing three-part title and
Task/source_anchor body. No new task schema, queue or result authority is introduced.
"""
import time

from c1_execution_contract import Refused, canonical
from c1_issue_consumer import (GitHubIssuesReader, check, default_runtime_factory,
                              poll_once, MAX_PAGES, PER_PAGE)
from c1_issue_ingress import INGRESS_ENABLED_ENV
from cell_channel import arguments, cell_config


class AuthorizedReader:
    def __init__(self, reader, authors):
        self.reader, self.authors = reader, authors

    def list_open_issues(self, **kwargs):
        listing = self.reader.list_open_issues(**kwargs)
        # An issue author's identity alone is not enough: its last editor could be
        # someone else. GitHub write access is still required for edits; the task
        # author allowlist is a bounded ingress check, not a deployment authority.
        return dict(listing, issues=[i for i in listing["issues"]
                    if isinstance(i, dict) and
                    (i.get("user") or {}).get("login") in self.authors])


def poll_cell(config, *, reader, runtime=None, runtime_factory=None):
    if not config["authors"]:
        return {"status": "BLOCKED_NO_TASK_AUTHORS", "cell": config["cell"], "enqueued": []}
    result = poll_once(reader=AuthorizedReader(reader, config["authors"]),
                       runtime=runtime, runtime_factory=runtime_factory,
                       environ={INGRESS_ENABLED_ENV: str(config["enabled"])},
                       owner_c=config["cell"], pages=MAX_PAGES,
                       max_candidates=MAX_PAGES * PER_PAGE)
    result["cell"] = config["cell"]
    # Do not silently starve tasks behind the listing bound. Installation acceptance
    # must resolve this state rather than treating a partial scan as full coverage.
    if result.get("listed", 0) >= MAX_PAGES * PER_PAGE:
        result["status"] = "PARTIAL_LISTING_LIMIT"
    return result


def main(argv=None):
    args = arguments(argv)
    try:
        config = cell_config(args.cell)
    except Refused as exc:
        print(canonical({"status": "REFUSED", "reason": exc.reason}))
        return 1
    if args.check:
        report = check({INGRESS_ENABLED_ENV: str(config["enabled"])})
        report.update(cell=config["cell"], enable_switch="C%02d_RUNTIME_INGRESS_ENABLED" % int(config["cell"][1:]),
                      task_authors_configured=bool(config["authors"]))
        if not config["authors"]:
            report["status"] = "BLOCKED_NO_TASK_AUTHORS"
        print(canonical(report))
        return 0 if report["status"] == "READY" else 1
    while True:
        try:
            result = poll_cell(config, reader=GitHubIssuesReader(), runtime_factory=default_runtime_factory)
        except Exception as exc:
            result = {"status": "BLOCKED", "cell": config["cell"], "reason": type(exc).__name__}
        print(canonical(result), flush=True)
        if args.once:
            return 0 if result["status"] in ("PASS", "NO_CANDIDATE", "DISABLED") else 1
        time.sleep(180)


if __name__ == "__main__":
    raise SystemExit(main())
