"""Publish a prepared Request file as a Request PR on the control bus.

Narrow on purpose: it takes a local JSON file that is already a well-formed Request,
refuses anything whose shape it does not recognise, and opens one non-draft PR in
chenzhenxi1-sudo/go-control-tasks that adds exactly ``requests/<request_id>.json``.

It holds no Task key and signs nothing. It cannot merge, cannot close, cannot touch
another repository, and cannot invent a field: it publishes bytes it was handed.

This tool runs on the operator workstation, not on the Command Center host, and that
is deliberate: opening a PR needs a credential the CC host does not have and should
not hold, so the host that decides "a probe is due" is not the host that can write to
the bus. The token is read from the workstation's Windows Credential Manager through
the local ``gh`` helper, and is never printed or written to disk.

Usage:
  python publish_request_pr.py <request.json> <branch-name> [title-suffix]
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\Code\Workbuddy\.workbuddy\tmp")
try:
    import gh
except ModuleNotFoundError:
    raise SystemExit(
        "this tool must run on the operator workstation: it reads the GitHub token "
        "from the local credential helper (`gh`), which the Command Center host "
        "deliberately does not have")

import urllib.error
import urllib.request

OWNER, REPO = "chenzhenxi1-sudo", "go-control-tasks"
ENVIRONMENT = "HK-STAGING-01"
COMMON = {"schema_version", "request_id", "action_id", "environment", "requested_at"}
SHAPES = {
    "HK_STAGING_TEST_PR": COMMON | {"pr_number"},
    "HK_STAGING_VERIFY": COMMON,
    # DEPLOY has carried only the five common fields since the plan became derived;
    # a Request that still names a plan is refused by the Bridge, so it is refused here too.
    "HK_STAGING_DEPLOY": COMMON,
    "HK_STAGING_CANARY": COMMON,
    "HK_STAGING_ROLLBACK": COMMON,
    "CONTROL_PLANE_HEALTH": COMMON,
}
TOK = gh.get_token()


def api(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        "https://api.github.com" + path, data=data, method=method,
        headers={"Authorization": "Bearer " + TOK,
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "workbuddy-request-pr",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "ignore")[:600]


def main():
    source, branch = sys.argv[1], sys.argv[2]
    raw = pathlib.Path(source).read_text(encoding="utf-8").strip()
    request = json.loads(raw)
    action = request.get("action_id")
    if action not in SHAPES:
        raise SystemExit("refused: unknown action %r" % action)
    if set(request) != SHAPES[action]:
        raise SystemExit("refused: fields %s do not match the %s shape" % (sorted(request), action))
    if request["environment"] != ENVIRONMENT:
        raise SystemExit("refused: environment %r" % request["environment"])
    request_id = request["request_id"]
    path = "requests/%s.json" % request_id

    status, _ = api("GET", "/repos/%s/%s/git/ref/heads/%s" % (OWNER, REPO, branch))
    if status == 200:
        print(json.dumps({"result": "BRANCH_EXISTS", "branch": branch}, sort_keys=True))
        return 0

    status, base_ref = api("GET", "/repos/%s/%s/git/ref/heads/main" % (OWNER, REPO))
    if status != 200:
        raise SystemExit("cannot read main: HTTP %s %s" % (status, base_ref))
    base_sha = base_ref["object"]["sha"]
    status, base_commit = api("GET", "/repos/%s/%s/git/commits/%s" % (OWNER, REPO, base_sha))
    if status != 200:
        raise SystemExit("cannot read main commit: HTTP %s" % status)
    status, blob = api("POST", "/repos/%s/%s/git/blobs" % (OWNER, REPO),
                       {"content": raw + "\n", "encoding": "utf-8"})
    if status != 201:
        raise SystemExit("cannot create blob: HTTP %s %s" % (status, blob))
    status, tree = api("POST", "/repos/%s/%s/git/trees" % (OWNER, REPO),
                       {"base_tree": base_commit["tree"]["sha"],
                        "tree": [{"path": path, "mode": "100644", "type": "blob",
                                  "sha": blob["sha"]}]})
    if status != 201:
        raise SystemExit("cannot create tree: HTTP %s %s" % (status, tree))
    status, commit = api("POST", "/repos/%s/%s/git/commits" % (OWNER, REPO),
                         {"message": "request: " + request_id, "tree": tree["sha"],
                          "parents": [base_sha]})
    if status != 201:
        raise SystemExit("cannot create commit: HTTP %s %s" % (status, commit))
    status, ref = api("POST", "/repos/%s/%s/git/refs" % (OWNER, REPO),
                      {"ref": "refs/heads/" + branch, "sha": commit["sha"]})
    if status != 201:
        raise SystemExit("cannot create branch: HTTP %s %s" % (status, ref))
    body = "\n".join([
        "A `%s` Request, published to exercise the failure closure." % action,
        "",
        "* the Request is an untrusted proposal and grants no execution",
        "* the Bridge validates it and, if it accepts it, signs a Task",
        "* it is polled continuously and does not need to be merged",
        "",
        "```json", raw, "```"])
    status, pr = api("POST", "/repos/%s/%s/pulls" % (OWNER, REPO),
                     {"title": ("request: " + request_id + ((" " + sys.argv[3]) if len(sys.argv) > 3 else "")),
                      "head": branch, "base": "main", "body": body, "draft": False})
    if status != 201:
        raise SystemExit("cannot open PR: HTTP %s %s" % (status, pr))
    print(json.dumps({"result": "PUBLISHED", "request_id": request_id, "branch": branch,
                      "head_sha": pr["head"]["sha"], "pr": pr["number"], "url": pr["html_url"],
                      "draft": pr["draft"], "state": pr["state"],
                      "changed_files": pr["changed_files"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
