"""Publish one CONTROL_PLANE_HEALTH Request from the producer outbox as a Request PR.

This is the operator wiring the liveness producer's README says is missing: the
producer writes an untrusted Request into its outbox on the Command Center host, and
something has to put it on the Request channel. The Request channel is a PR in
go-control-tasks that adds exactly one ``requests/<request_id>.json`` file, so that is
what this creates.

Deliberately narrow:

* it talks only to chenzhenxi1-sudo/go-control-tasks;
* it accepts only a well-formed CONTROL_PLANE_HEALTH Request with the five common
  fields and nothing else, in the HK-STAGING-01 environment;
* it creates a branch, one blob, one tree, one commit, one ref and one non-draft PR;
* it cannot merge, cannot close, cannot change a file it did not add, and is
  idempotent: an existing branch or PR for the same request_id is reported, not
  recreated.

It holds no Task key and signs nothing. Turning a Request into a signed Task stays
where it already is -- the Bridge.

Usage:
  python liveness_request_wiring.py            # newest published probe in the outbox
  python liveness_request_wiring.py <req_id>   # one specific request id
"""
import json
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, r"D:\Code\Workbuddy\.workbuddy\tmp")
import gh

OWNER, REPO = "chenzhenxi1-sudo", "go-control-tasks"
SSH_HOST = "go-cc"
OUTBOX = "/var/lib/go-command-center/liveness-producer-v1/outbox"
ACTION = "CONTROL_PLANE_HEALTH"
ENVIRONMENT = "HK-STAGING-01"
FIELDS = {"schema_version", "request_id", "action_id", "environment", "requested_at"}
TOK = gh.get_token()


def api(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        "https://api.github.com" + path, data=data, method=method,
        headers={"Authorization": "Bearer " + TOK,
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "workbuddy-liveness-wiring",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "ignore")[:600]


def newest_outbox_request(wanted=None):
    listing = subprocess.run(["ssh", "-o", "BatchMode=yes", SSH_HOST,
                              "ls -1 %s" % OUTBOX], capture_output=True, text=True)
    if listing.returncode != 0:
        raise SystemExit("cannot list the outbox: %s" % listing.stderr.strip()[:200])
    names = sorted(n for n in listing.stdout.split() if n.endswith(".json"))
    if wanted:
        names = [n for n in names if n == wanted + ".json"]
    if not names:
        raise SystemExit("no request in the outbox%s" % (" for " + wanted if wanted else ""))
    name = names[-1]
    body = subprocess.run(["ssh", "-o", "BatchMode=yes", SSH_HOST,
                           "cat %s/%s" % (OUTBOX, name)], capture_output=True, text=True)
    if body.returncode != 0:
        raise SystemExit("cannot read %s: %s" % (name, body.stderr.strip()[:200]))
    raw = body.stdout.strip()
    request = json.loads(raw)
    if set(request) != FIELDS:
        raise SystemExit("refused: fields are %s" % sorted(request))
    if request["action_id"] != ACTION or request["environment"] != ENVIRONMENT:
        raise SystemExit("refused: %s / %s" % (request["action_id"], request["environment"]))
    if request["request_id"] != name[:-5]:
        raise SystemExit("refused: request_id does not match the outbox file name")
    for value in request.values():
        if not isinstance(value, str):
            raise SystemExit("refused: non-string field")
    return request, raw


def main():
    wanted = sys.argv[1] if len(sys.argv) > 1 else None
    request, raw = newest_outbox_request(wanted)
    request_id = request["request_id"]
    branch = "boss-request-" + request_id
    path = "requests/%s.json" % request_id

    status, existing = api("GET", "/repos/%s/%s/git/ref/heads/%s" % (OWNER, REPO, branch))
    if status == 200:
        print(json.dumps({"result": "ALREADY_PUBLISHED", "branch": branch,
                          "sha": existing["object"]["sha"]}, sort_keys=True))
        return 0

    status, base_ref = api("GET", "/repos/%s/%s/git/ref/heads/main" % (OWNER, REPO))
    if status != 200:
        raise SystemExit("cannot read main: HTTP %s %s" % (status, base_ref))
    base_commit_sha = base_ref["object"]["sha"]
    status, base_commit = api("GET", "/repos/%s/%s/git/commits/%s"
                              % (OWNER, REPO, base_commit_sha))
    if status != 200:
        raise SystemExit("cannot read main commit: HTTP %s %s" % (status, base_commit))
    base_tree_sha = base_commit["tree"]["sha"]

    status, blob = api("POST", "/repos/%s/%s/git/blobs" % (OWNER, REPO),
                       {"content": raw + "\n", "encoding": "utf-8"})
    if status != 201:
        raise SystemExit("cannot create blob: HTTP %s %s" % (status, blob))
    status, tree = api("POST", "/repos/%s/%s/git/trees" % (OWNER, REPO),
                       {"base_tree": base_tree_sha,
                        "tree": [{"path": path, "mode": "100644", "type": "blob",
                                  "sha": blob["sha"]}]})
    if status != 201:
        raise SystemExit("cannot create tree: HTTP %s %s" % (status, tree))
    status, commit = api("POST", "/repos/%s/%s/git/commits" % (OWNER, REPO),
                         {"message": "request: " + request_id, "tree": tree["sha"],
                          "parents": [base_commit_sha]})
    if status != 201:
        raise SystemExit("cannot create commit: HTTP %s %s" % (status, commit))
    status, ref = api("POST", "/repos/%s/%s/git/refs" % (OWNER, REPO),
                      {"ref": "refs/heads/" + branch, "sha": commit["sha"]})
    if status != 201:
        raise SystemExit("cannot create branch: HTTP %s %s" % (status, ref))

    body = "\n".join([
        "A read-only `CONTROL_PLANE_HEALTH` probe Request, produced by",
        "`control-plane/agent-liveness-producer-v1` on the Command Center host.",
        "",
        "* the Request is an untrusted proposal; it carries no signature and grants no execution",
        "* turning it into a signed Task is the Boss Request Bridge's job, not this PR's",
        "* the action is read-only, has no parameters, and cannot become VERIFY / TEST_PR / DEPLOY / ROLLBACK",
        "* this PR exists only so the agent can publish fresh signed liveness Evidence;",
        "  it is polled continuously and does not need to be merged",
        "",
        "```json", raw, "```"])
    status, pr = api("POST", "/repos/%s/%s/pulls" % (OWNER, REPO),
                     {"title": "request: " + request_id, "head": branch, "base": "main",
                      "body": body, "draft": False})
    if status != 201:
        raise SystemExit("cannot open PR: HTTP %s %s" % (status, pr))
    print(json.dumps({"result": "PUBLISHED", "request_id": request_id,
                      "branch": branch, "head_sha": pr["head"]["sha"],
                      "pr": pr["number"], "url": pr["html_url"],
                      "draft": pr["draft"], "state": pr["state"],
                      "changed_files": pr["changed_files"],
                      "additions": pr["additions"], "deletions": pr["deletions"]},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
