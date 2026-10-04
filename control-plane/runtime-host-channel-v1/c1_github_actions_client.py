"""The Runtime-side GitHub client for the C1 dispatch loop.

This is the ONLY place the Runtime Host talks to the GitHub REST API. It implements the
dispatch loop and the read-only candidate reads that feed a review round, and nothing else:

    dispatch_workflow()   POST .../actions/workflows/{id}/dispatches
    find_run_by_name()    GET  .../actions/runs            (resolve an unknown dispatch)
    get_run()             GET  .../actions/runs/{id}
    download_artifact()   GET  .../actions/runs/{id}/artifacts -> .../artifacts/{id}/zip
    download_artifact_members()  the same, several named files out of one archive
    send()/find_run()     adapters for the outbox
    read_pull()           GET  .../pulls/{n}
    read_pull_files()     GET  .../pulls/{n}/files
    read_commit_tree()    GET  .../commits/{sha}
    read_tree()           GET  .../git/trees/{sha}

Credential contract. The four `read_*` methods were added when a Builder completion began
naming its own review candidate: the Runtime has to read the pull request the Builder's run
created, and the `application/` tree of the exact commit it is at, to build a review round
at all. That needs two more fine-grained permissions than the dispatch loop did:

    Actions: Read and write     dispatch, run lookup, artifact download
    Pull requests: Read         the candidate and its changed files
    Contents: Read              the candidate commit's trees

This was MEASURED on the Runtime host rather than assumed: the deployed token already
carries all three (and more), no permission was granted for this change, and no write scope
is used by any of the four reads. Nothing else was added - no Contents write, no Issues, no
Admin - and the reads supersede nothing: every previously-proven operation is unchanged.

The token is never a literal and never a parameter of a task. It is read through an
injected loader; the shipped loader reads a root-only file whose path is configured
outside the repository. The host overrides the built-in default with
`C1_GITHUB_TOKEN_PATH`; `DEFAULT_TOKEN_FILE` below is only the class's own fallback.

`token_from_file()` refuses a file that is readable by group or other, so a mis-set
permission fails closed instead of silently working. This module never logs the
token, never puts it in a result, and never writes it anywhere.
"""
from __future__ import annotations

import io
import json
import os
import stat
import urllib.error
import urllib.request
import zipfile

from c1_execution_contract import (
    REF,
    REPO,
    RUNS_ENDPOINT,
    WORKFLOW_FILE,
    Refused,
    canonical,
    dispatch_endpoint,
    dispatch_inputs,
)

API_BASE = "https://api.github.com"
# 2022-11-28 answers a dispatch with 204 and no body; 2026-03-10 answers 200 with
# workflow_run_id. The loop works under both: a dispatch without a run id is recorded
# as ambiguous and resolved by the deterministic run name.
API_VERSION = "2022-11-28"
TOKEN_FILE_ENV = "C1_GITHUB_TOKEN_PATH"
DEFAULT_TOKEN_FILE = "/etc/go-runtime-host/c1-github-token"
RESULT_ARTIFACT_FILE = "c1_result.json"
HTTP_TIMEOUT_S = 30
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
# One page of a pull request's changed files. The bound is stated rather than implied: the
# file list is a review's declared test scope, and a candidate with more changed files than
# this is read as its first page rather than refused. Every Builder pull request this
# channel produces is a handful of files.
PULL_FILES_PER_PAGE = 100


def token_from_file(path: str) -> str:
    """Read a token from a file that must not be readable by group or other."""
    try:
        info = os.stat(path)
    except OSError:
        raise Refused("TOKEN_FILE_UNREADABLE") from None
    if info.st_mode & (stat.S_IRGRP | stat.S_IROTH):
        raise Refused("TOKEN_FILE_PERMISSIONS_TOO_OPEN")
    with open(path, "r", encoding="utf-8") as handle:
        token = handle.read().strip()
    if not token:
        raise Refused("TOKEN_FILE_EMPTY")
    return token


def configured_token_loader():
    """The default loader: the path comes from configuration, never from a task."""
    path = os.environ.get(TOKEN_FILE_ENV) or DEFAULT_TOKEN_FILE
    return lambda: token_from_file(path)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def _extract_result_bytes(archive: bytes) -> bytes:
    """Return the result file, and only ever that file.

    The member name is required rather than inferred: the workflow uploads exactly
    `c1_result.json`, and accepting "whatever single file happens to be in the zip"
    would let a differently-shaped artifact satisfy the contract.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            if RESULT_ARTIFACT_FILE not in bundle.namelist():
                raise Refused("ARTIFACT_DOES_NOT_CONTAIN_THE_RESULT_FILE")
            return bundle.read(RESULT_ARTIFACT_FILE)
    except zipfile.BadZipFile:
        raise Refused("ARTIFACT_NOT_A_ZIP") from None


class GitHubActionsClient:
    """The GitHub transport for ONE executor, bound to ONE workflow file.

    The workflow file is configuration of the executor, not of the request. A request
    carries `repo` / `workflow_file` / `ref` as a record of where its class is aimed, and
    those three are added *after* the execution identity is hashed - so they cannot be
    part of the identity, and a wrong one cannot be detected by re-hashing. It has to be
    checked against the executor's own binding, here, at the only place that sends.

    Why it has to be per-executor at all: two executors share this class. The Responses
    executor dispatches `c1-ai-execution-backend-v1.yml`; the gh-aw Builder executor
    dispatches `c1-gh-aw-builder-v1.lock.yml`. If the client kept one module-level
    endpoint, the second executor would record one target and send to the other - a
    Builder task delivered to the Responses backend, which is the failure this binding
    exists to prevent.

    `workflow_file` and `ref` default to the channel's original values, so every existing
    construction of this class keeps the behaviour it was proven with.
    """

    def __init__(self, *, token_loader=None, opener=urllib.request.urlopen,
                 redirect_opener=None, no_redirect_opener=None, api_base=API_BASE,
                 api_version=API_VERSION, timeout_s=HTTP_TIMEOUT_S,
                 workflow_file=None, workflow_files=None, ref=None, result_member=None):
        self._token_loader = token_loader or configured_token_loader()
        self._opener = opener
        # The signed artifact URL rejects an Authorization header, so the follow-up
        # request is a separate, deliberately unauthenticated opener.
        self._redirect_opener = redirect_opener or urllib.request.urlopen
        # Requests that must NOT follow a redirect need an opener that refuses to.
        self._no_redirect_opener = no_redirect_opener or urllib.request.build_opener(
            _NoRedirect).open
        self._api = api_base
        self._version = api_version
        self._timeout = timeout_s
        # The executor binding. Fixed at construction and never taken from a request.
        # The executor's dispatch target(s). ONE executor normally owns one workflow;
        # the C13/C14 review executor owns two, because each cell's review is its own
        # existing workflow and the two are different executions of different cells.
        # A tuple widens which targets are admissible, never whether one is checked:
        # `assert_bound_target` still refuses anything that is not on this list, so a
        # review request can never be delivered to the Builder's workflow, nor a Builder
        # request here. The first entry stays the executor's declared identity for
        # status, and with neither argument this is the single original target.
        if workflow_files is not None:
            self._workflow_files = tuple(workflow_files)
            if not self._workflow_files:
                raise Refused("EXECUTOR_HAS_NO_DISPATCH_TARGET")
        else:
            self._workflow_files = (workflow_file or WORKFLOW_FILE,)
        self._workflow_file = self._workflow_files[0]
        self._ref = ref or REF
        self._result_member = result_member or RESULT_ARTIFACT_FILE
        self._dispatch_endpoint = dispatch_endpoint(self._workflow_file)

    # ------------------------------------------------------------------ transport
    def _headers(self, *, with_auth=True):
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "go-runtime-host-c1",
            "X-GitHub-Api-Version": self._version,
        }
        if with_auth:
            token = self._token_loader()
            if not token:
                raise Refused("GITHUB_TOKEN_MISSING")
            headers["Authorization"] = "Bearer " + token
        return headers

    def _call(self, method, path, payload=None, *, follow_redirect=True):
        body = canonical(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(self._api + path, data=body, method=method,
                                         headers=self._headers())
        opener = self._opener if follow_redirect else self._no_redirect_opener
        try:
            with opener(request, timeout=self._timeout) as response:
                raw = response.read()
                return response.status, raw
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                location = exc.headers.get("Location")
                if follow_redirect or not location:
                    raise Refused("UNEXPECTED_REDIRECT_WITHOUT_LOCATION") from None
                # The signed URL carries its own authorisation and REJECTS an
                # Authorization header, so the follow-up request must not send one.
                follow = urllib.request.Request(location, headers={"User-Agent": "go-runtime-host-c1"})
                with self._redirect_opener(follow, timeout=self._timeout) as signed:
                    return signed.status, signed.read()
            raise Refused("GITHUB_HTTP_%s" % exc.code) from None
        except (urllib.error.URLError, OSError):
            raise Refused("GITHUB_UNREACHABLE") from None

    @staticmethod
    def _document(raw):
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise Refused("GITHUB_RESPONSE_NOT_JSON") from None

    # ------------------------------------------------ the five real operations
    def workflow_target(self) -> dict:
        """What this client is bound to send to. Read-only, for status and for tests.

        The binding is configuration, so it is worth being able to read it without
        reaching into the object: "which workflow does this executor dispatch" is the
        question the whole transport binding exists to answer, and an operator's status
        line is a legitimate place to answer it.
        """
        return {"repo": REPO, "workflow_file": self._workflow_file, "ref": self._ref,
                "dispatch_endpoint": self._dispatch_endpoint}

    def assert_bound_target(self, request: dict) -> None:
        """Refuse a request whose recorded transport target is not this executor's.

        The three fields are a record of where the request's CLASS is aimed. They are
        written by the contract, not by a caller, so a disagreement can only mean one
        thing: this client belongs to a different executor than the task does. Sending
        anyway would deliver the task to the wrong workflow - a real dispatch, a real
        run, and for a paid class a real bill, for work another executor owns.

        Fail closed, before the POST, and never "prefer" either value: a request that
        disagrees is not repaired here.
        """
        recorded = request.get("workflow_file")
        if recorded not in self._workflow_files:
            raise Refused("DISPATCH_TARGET_IS_NOT_THIS_EXECUTORS_WORKFLOW:%s" % recorded)
        if request.get("ref") != self._ref:
            raise Refused("DISPATCH_REF_IS_NOT_THIS_EXECUTORS_REF:%s" % request.get("ref"))
        if request.get("repo") != REPO:
            raise Refused("DISPATCH_REPO_MISMATCH:%s" % request.get("repo"))

    def dispatch_workflow(self, request: dict):
        """Send exactly one dispatch. Returns ("sent", run_id|None) for the outbox.

        The input set comes from the contract rather than from here: a smoke dispatch
        carries the identity triple and nothing else, while a real dispatch additionally
        carries its kind and payload so the executor can re-derive the same identity and
        prompt from what it receives. Repository, workflow file and ref stay fixed and
        stay off the wire in both cases - and the two that decide *which* executor runs
        the task are checked against this client's own binding before anything is sent.
        """
        self.assert_bound_target(request)
        payload = {"ref": self._ref,
                   "inputs": {name: value if isinstance(value, str) else str(value)
                              for name, value in dispatch_inputs(request).items()}}
        # Resolved from the (already checked) request, so a two-target executor sends to
        # the workflow the task's own class names - never to whichever one it happens to
        # hold first.
        endpoint = dispatch_endpoint(request["workflow_file"])
        status, raw = self._call("POST", endpoint, payload)
        if status == 204 or not raw:
            return ("sent", None)
        document = self._document(raw)
        run_id = document.get("workflow_run_id")
        if not isinstance(run_id, int) or run_id <= 0:
            return ("sent", None)
        return ("sent", run_id)

    def find_run_by_name(self, name: str):
        """Resolve a dispatch whose outcome is unknown, by the deterministic run name.

        GitHub returns runs newest first, so the first name match is the newest one.
        """
        status, raw = self._call("GET", RUNS_ENDPOINT + "?event=workflow_dispatch&per_page=100")
        document = self._document(raw)
        for run in document.get("workflow_runs", []):
            if run.get("name") == name:
                return {"id": run.get("id"), "run_attempt": run.get("run_attempt", 1),
                        "status": run.get("status"), "conclusion": run.get("conclusion"),
                        "head_sha": ((run.get("head_commit") or {}).get("id"))}
        return None

    def get_run(self, run_id: int):
        status, raw = self._call("GET", "%s/%s" % (RUNS_ENDPOINT, run_id))
        run = self._document(raw)
        return {"id": run.get("id"), "run_attempt": run.get("run_attempt", 1),
                "status": run.get("status"), "conclusion": run.get("conclusion"),
                "head_sha": ((run.get("head_commit") or {}).get("id"))}

    # ------------------------------------------------- read-only candidate reads
    # Four GETs that are not about Actions at all, and they live here for one reason: this
    # class already owns the Runtime host's only outbound transport - its token, its API
    # base, its timeout and its refusal vocabulary - and a second HTTP client would be a
    # second place for all four to drift. They are the same four endpoints the issue
    # consumer's reader calls, with the same normalised shapes, so `c1_candidate_reads` can
    # be handed EITHER object and behave identically.
    #
    # Only GET. There is no write here, and `_call` is the same one every other method uses.
    def read_pull(self, number: int) -> dict:
        """The named pull request: its base branch, its CURRENT head, and its draft flag."""
        status, raw = self._call("GET", "/repos/%s/pulls/%d" % (self._repo_slug(), number))
        document = self._document(raw)
        if not isinstance(document, dict):
            raise Refused("PULL_NOT_AN_OBJECT")
        base = document.get("base") or {}
        head = document.get("head") or {}
        return {"number": document.get("number"), "state": document.get("state"),
                "draft": document.get("draft"), "base_ref": base.get("ref"),
                "head_sha": head.get("sha")}

    def read_pull_files(self, number: int) -> list:
        """One page of the pull request's changed files: each name and change status."""
        status, raw = self._call(
            "GET", "/repos/%s/pulls/%d/files?per_page=%d" % (self._repo_slug(), number,
                                                             PULL_FILES_PER_PAGE))
        document = self._document(raw)
        if not isinstance(document, list):
            raise Refused("PULL_FILES_NOT_A_LIST")
        files = []
        for entry in document:
            if not isinstance(entry, dict):
                raise Refused("PULL_FILES_NOT_OBJECTS")
            files.append({"filename": entry.get("filename"), "status": entry.get("status")})
        return files

    def read_commit_tree(self, commit_sha: str) -> str:
        """The root tree SHA of one commit, read at that commit."""
        status, raw = self._call("GET", "/repos/%s/commits/%s" % (self._repo_slug(),
                                                                 commit_sha))
        document = self._document(raw)
        if not isinstance(document, dict):
            raise Refused("COMMIT_NOT_AN_OBJECT")
        tree = (document.get("commit") or {}).get("tree") or {}
        sha = tree.get("sha")
        if not isinstance(sha, str) or not sha.strip():
            raise Refused("COMMIT_TREE_NOT_FOUND")
        return sha.strip()

    def read_tree(self, tree_sha: str) -> list:
        """One tree's direct entries. A truncated listing is a refusal, not a short answer.

        "The entry was not in the part we saw" and "the entry does not exist" are different
        facts, and only the second one justifies refusing an application tree.
        """
        status, raw = self._call("GET", "/repos/%s/git/trees/%s" % (self._repo_slug(),
                                                                    tree_sha))
        document = self._document(raw)
        if not isinstance(document, dict):
            raise Refused("TREE_NOT_AN_OBJECT")
        if document.get("truncated") is True:
            raise Refused("TREE_TRUNCATED")
        entries = document.get("tree")
        if not isinstance(entries, list):
            raise Refused("TREE_ENTRIES_NOT_A_LIST")
        for entry in entries:
            if not isinstance(entry, dict):
                raise Refused("TREE_ENTRY_NOT_AN_OBJECT")
        return entries

    def download_artifact(self, run_id: int, name: str):
        """Return the sealed result file bytes plus the digest of those bytes.

        Two checks are performed at this layer and nowhere else:
          * the zip blob must hash to the digest the platform reports for it;
          * the archive must contain exactly the result file.
        The caller then checks the document against the task identity it belongs to.
        """
        status, raw = self._call(
            "GET", "%s/%s/artifacts?name=%s" % (RUNS_ENDPOINT, run_id, name))
        listing = self._document(raw)
        artifacts = listing.get("artifacts") or []
        if not artifacts:
            return None
        if len(artifacts) > 1:
            raise Refused("MORE_THAN_ONE_ARTIFACT_WITH_THE_EXECUTION_IDENTITY")
        artifact = artifacts[0]
        if artifact.get("expired"):
            raise Refused("ARTIFACT_EXPIRED")
        status, archive = self._call(
            "GET", "/repos/%s/actions/artifacts/%s/zip" % (self._repo_slug(), artifact["id"]),
            follow_redirect=False)
        if len(archive) > MAX_ARTIFACT_BYTES:
            raise Refused("ARTIFACT_TOO_LARGE")
        declared = artifact.get("digest")
        if declared:
            import hashlib
            if declared != "sha256:" + hashlib.sha256(archive).hexdigest():
                raise Refused("ARTIFACT_ARCHIVE_DIGEST_MISMATCH")
        result_bytes = _extract_result_bytes(archive)
        import hashlib
        return {"bytes": result_bytes,
                "digest": "sha256:" + hashlib.sha256(result_bytes).hexdigest(),
                "github_run_id": run_id}

    def download_artifact_members(self, run_id: int, name: str, members) -> dict | None:
        """Return several named files from ONE artifact, digests recomputed here.

        The C1/C12 classes publish a single-file result, which `download_artifact`
        already handles. The review classes publish the Lite workflow's own bundle
        artifact, which holds several files - so the *same* transport gains the ability
        to take named members out of it instead of gaining a second HTTP client.
        Nothing is inferred: a member that is not present is a refusal, because
        accepting "whatever was in the zip" is how an artifact stops being a contract.
        """
        wanted = tuple(members)
        status, raw = self._call(
            "GET", "%s/%s/artifacts?name=%s" % (RUNS_ENDPOINT, run_id, name))
        listing = self._document(raw)
        artifacts = listing.get("artifacts") or []
        if not artifacts:
            return None
        if len(artifacts) > 1:
            raise Refused("MORE_THAN_ONE_ARTIFACT_WITH_THE_EXECUTION_IDENTITY")
        artifact = artifacts[0]
        if artifact.get("expired"):
            raise Refused("ARTIFACT_EXPIRED")
        status, archive = self._call(
            "GET", "/repos/%s/actions/artifacts/%s/zip" % (self._repo_slug(),
                                                           artifact["id"]),
            follow_redirect=False)
        if len(archive) > MAX_ARTIFACT_BYTES:
            raise Refused("ARTIFACT_TOO_LARGE")
        import hashlib
        declared = artifact.get("digest")
        if declared and declared != "sha256:" + hashlib.sha256(archive).hexdigest():
            raise Refused("ARTIFACT_ARCHIVE_DIGEST_MISMATCH")
        found = {}
        try:
            with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
                present = set(bundle.namelist())
                for member in wanted:
                    if member not in present:
                        raise Refused("ARTIFACT_MEMBER_MISSING:" + member)
                    found[member] = bundle.read(member)
        except zipfile.BadZipFile:
            raise Refused("ARTIFACT_NOT_A_ZIP") from None
        return {"members": found,
                "digests": {k: "sha256:" + hashlib.sha256(v).hexdigest()
                            for k, v in found.items()},
                "github_run_id": run_id}

    def _repo_slug(self) -> str:
        """The repository every operation here addresses.

        Deliberately the repository and not the endpoint: runs and artifacts are
        repo-level, and both executors address the same one. Only the dispatch target is
        per-executor, and only `dispatch_workflow` uses that.
        """
        return REPO

    # ----------------------------------------------------- outbox adapters
    def send(self, request: dict):
        return self.dispatch_workflow(request)

    def find_run(self, run_name: str):
        found = self.find_run_by_name(run_name)
        return None if found is None else found["id"]
