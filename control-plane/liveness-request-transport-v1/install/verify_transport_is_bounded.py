#!/usr/bin/env python3
"""Prove the liveness transport is bounded, against a real git repository.

Uses a local bare repository as the bus, so the whole thing is hermetic: no
network, no GitHub, no credential. What it exercises is the real plumbing --
``ls-remote``, ``fetch``, ``hash-object``, ``write-tree``, ``commit-tree``,
``push`` and ``push --force-with-lease`` -- because that plumbing is exactly what
the Bridge's acceptance rule constrains:

    diff --name-status merge-base(main, head)..head  ==  exactly one entry,
                                                        status A, requests/<id>.json

Run:  python install/verify_transport_is_bounded.py --work <scratch dir>
"""
import argparse
import datetime as dt
import json
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
COMPONENT = HERE.parent
TOOL = COMPONENT / "command-center" / "go-liveness-request-transport"
TRANSPORT = "boss-request-liveness-transport"
ARCHIVE = "request/liveness-archive"
ACTION = "CONTROL_PLANE_HEALTH"
ENVIRONMENT = "HK-STAGING-01"
R = "refs/remotes/origin/"


def git(*args, cwd=None, check=True):
    result = subprocess.run(["git", *args], cwd=str(cwd) if cwd else None,
                            capture_output=True, text=True)
    if check and result.returncode != 0:
        raise AssertionError("git %s -> %s" % (" ".join(args[:2]), result.stderr.strip()[:300]))
    return result.stdout.strip()


def iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class Bus:
    """A local bare repository plus a read-only clone that inspects it after a sync."""

    def __init__(self, root):
        self.root = pathlib.Path(root)
        self.bare = self.root / "bus.git"
        git("init", "--bare", "--initial-branch=main", str(self.bare))
        # A leftover bare repository would carry refs from an earlier run and make
        # every count below meaningless, so refuse to start unless it is empty.
        stale = git("for-each-ref", "--format=%(refname)", cwd=self.bare, check=False).strip()
        if stale:
            raise AssertionError("the scratch bus is not empty: %s" % stale)
        self.view = self.root / "view"
        git("clone", "--quiet", str(self.bare), str(self.view))
        git("config", "user.name", "bus", cwd=self.view)
        git("config", "user.email", "bus@localhost", cwd=self.view)
        (self.view / "README.md").write_text("the control bus\n", encoding="utf-8")
        (self.view / "tasks").mkdir()
        (self.view / "tasks" / "one.json").write_text("{}\n", encoding="utf-8")
        git("add", "-A", cwd=self.view)
        git("commit", "-q", "-m", "bus", cwd=self.view)
        git("push", "--quiet", "origin", "HEAD:main", cwd=self.view)
        self.sync()

    def sync(self):
        """Bring the view up to the bare repository -- the tool pushed behind its back."""
        git("fetch", "--quiet", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*",
            cwd=self.view)

    def branches(self):
        self.sync()
        return sorted(git("for-each-ref", "--format=%(refname)", "refs/remotes/origin/",
                          cwd=self.view).split())

    def unresolved(self, *args):
        """git printed nothing usable -- checked by exit code, never by stdout.

        ``git rev-parse <unknown ref>`` exits 128 but echoes the argument on
        stdout, so ``stdout or None`` would return the ref name as if it were a
        sha. Everything that may legitimately fail goes through here.
        """
        result = subprocess.run(["git", *args], cwd=str(self.view),
                                capture_output=True, text=True)
        return None if result.returncode != 0 else result.stdout.strip()

    def head_of(self, name):
        self.sync()
        return self.unresolved("rev-parse", R + name)

    def names(self, name):
        self.sync()
        listed = self.unresolved("ls-tree", "-r", "--name-only", R + name)
        return sorted(listed.split()) if listed is not None else []

    def requests(self, name):
        return [n for n in self.names(name) if n.startswith("requests/")]

    def on_the_bus(self):
        return sorted(set(self.requests(TRANSPORT)) | set(self.requests(ARCHIVE)))

    def changed_vs_merge_base(self, name):
        """What the Bridge itself would compute for this submission."""
        self.sync()
        base = git("merge-base", R + "main", R + name, cwd=self.view)
        raw = git("diff", "--name-status", base, R + name, cwd=self.view)
        return [line for line in raw.splitlines() if line.strip()]

    def parent_of(self, name):
        return self.unresolved("rev-parse", R + name + "^")

    def main_head(self):
        self.sync()
        return git("rev-parse", R + "main", cwd=self.view)


def relay(outbox, work, repo_url, now, dry_run=False):
    result = subprocess.run(
        [sys.executable, str(TOOL), "relay", "--outbox", str(outbox), "--work", str(work),
         "--repo-url", repo_url, "--now", iso(now), *(["--dry-run"] if dry_run else [])],
        capture_output=True, text=True)
    assert result.stdout.strip(), (result.returncode, result.stdout, result.stderr)
    return result.returncode, json.loads(result.stdout.strip()), result.stderr


def put(outbox, request_id, moment, **over):
    request = {"schema_version": "1", "request_id": request_id, "action_id": ACTION,
               "environment": ENVIRONMENT, "requested_at": iso(moment)}
    request.update(over)
    (outbox / (request_id + ".json")).write_text(
        json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", required=True)
    args = parser.parse_args()

    work = pathlib.Path(args.work).resolve()
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    bus = Bus(work)
    outbox = work / "outbox"
    outbox.mkdir()
    relay_work = work / "relay"
    failures = []

    def check(name, condition, detail=None):
        print(("PASS  " if condition else "FAIL  ") + name
              + ("" if condition else "  %s" % (detail,)))
        if not condition:
            failures.append(name)

    base = dt.datetime(2026, 9, 15, 12, 0, 0, tzinfo=dt.timezone.utc)
    p1 = "requests/liveness-control-plane-health-1001.json"
    p2 = "requests/liveness-control-plane-health-1002.json"
    p3 = "requests/liveness-control-plane-health-1003.json"

    # 1. the first probe creates the transport, as ONE added file, removing nothing
    put(outbox, "liveness-control-plane-health-1001", base)
    code, report, _ = relay(outbox, relay_work, str(bus.bare), base)
    check("first_probe_published", code == 0 and report["result"] == "PUBLISHED", report)
    check("the_bridge_would_see_exactly_one_added_file",
          bus.changed_vs_merge_base(TRANSPORT) == ["A\t" + p1], bus.changed_vs_merge_base(TRANSPORT))
    check("transport_parent_is_main", bus.parent_of(TRANSPORT) == bus.main_head())
    check("nothing_was_archived_on_the_first_probe", report["archived_now"] == [], report)
    check("the_archive_does_not_exist_yet", bus.head_of(ARCHIVE) is None)

    # 2. re-running one bucket is a no-op: the timer ticks far more often than the
    #    producer publishes
    before = bus.head_of(TRANSPORT)
    code, report, _ = relay(outbox, relay_work, str(bus.bare), base + dt.timedelta(seconds=300))
    check("a_second_tick_of_the_same_bucket_publishes_nothing",
          report["result"] == "ALREADY_PUBLISHED", report)
    check("and_moves_no_ref", bus.head_of(TRANSPORT) == before)
    check("and_creates_no_archive", bus.head_of(ARCHIVE) is None)

    # 3. the next bucket rotates the transport and archives the superseded file
    later = base + dt.timedelta(seconds=1800)
    put(outbox, "liveness-control-plane-health-1002", later)
    code, report, _ = relay(outbox, relay_work, str(bus.bare), later + dt.timedelta(seconds=60))
    check("second_probe_published", code == 0 and report["result"] == "PUBLISHED", report)
    check("the_superseded_file_was_archived", report["archived_now"] == [p1], report)
    check("the_second_submission_is_still_one_added_file",
          bus.changed_vs_merge_base(TRANSPORT) == ["A\t" + p2],
          bus.changed_vs_merge_base(TRANSPORT))
    check("the_transport_holds_the_current_probe_only", bus.requests(TRANSPORT) == [p2],
          bus.requests(TRANSPORT))
    check("the_archive_holds_the_superseded_probe", bus.requests(ARCHIVE) == [p1],
          bus.requests(ARCHIVE))
    check("no_request_file_was_lost_from_the_bus", bus.on_the_bus() == sorted([p1, p2]),
          bus.on_the_bus())
    check("the_branch_count_did_not_move", bus.branches() == sorted(
        [R + "main", R + TRANSPORT, R + ARCHIVE]), bus.branches())

    # 4. a third bucket keeps both properties: one file in, one file out
    third = later + dt.timedelta(seconds=1800)
    put(outbox, "liveness-control-plane-health-1003", third)
    code, report, _ = relay(outbox, relay_work, str(bus.bare), third + dt.timedelta(seconds=60))
    check("third_probe_published", code == 0 and report["result"] == "PUBLISHED", report)
    check("the_third_submission_is_still_one_added_file",
          bus.changed_vs_merge_base(TRANSPORT) == ["A\t" + p3],
          bus.changed_vs_merge_base(TRANSPORT))
    check("the_archive_grew_by_exactly_one", bus.requests(ARCHIVE) == sorted([p1, p2]),
          bus.requests(ARCHIVE))
    check("the_archive_never_lost_a_probe", bus.on_the_bus() == sorted([p1, p2, p3]),
          bus.on_the_bus())
    check("three_buckets_left_three_branches",
          bus.branches() == sorted([R + "main", R + TRANSPORT, R + ARCHIVE]), bus.branches())
    check("three_buckets_left_the_transport_at_one_file", len(bus.requests(TRANSPORT)) == 1)

    # 5. a stale probe is skipped rather than turned into a refusal fact
    put(outbox, "liveness-control-plane-health-1004", third)
    before = bus.head_of(TRANSPORT)
    code, report, _ = relay(outbox, relay_work, str(bus.bare), third + dt.timedelta(seconds=2000))
    check("a_stale_probe_is_skipped", report["result"] == "SKIPPED_STALE", report)
    check("and_moves_no_ref", bus.head_of(TRANSPORT) == before)

    # 6. a dry run decides without pushing
    fresh = third + dt.timedelta(seconds=2400)
    put(outbox, "liveness-control-plane-health-1005", fresh)
    before = bus.head_of(TRANSPORT)
    code, report, _ = relay(outbox, relay_work, str(bus.bare), fresh, dry_run=True)
    check("a_dry_run_reports_a_decision",
          report["result"] == "PUBLISHED" and report["dry_run"], report)
    check("a_dry_run_pushes_nothing", bus.head_of(TRANSPORT) == before)

    # 7. the manual wiring this replaces is gone: it cannot open a PR because it has
    #    no way to speak to an API at all
    source = TOOL.read_text(encoding="utf-8")
    for forbidden in ("urllib", "http.client", "requests.", "socket", "import gh"):
        check("no_%s_in_the_tool" % forbidden.replace(".", "_").replace(" ", "_"),
              forbidden not in source)

    print("\ntransport boundedness: %s" % ("PASS" if not failures else "FAIL %s" % failures))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
