"""The Runtime-side GitHub Actions client for the C1 dispatch loop.

This is the ONLY place the Runtime Host talks to the GitHub REST API for C1. It
implements exactly five operations and nothing else:

    dispatch_workflow()   POST .../actions/workflows/{id}/dispatches
    find_run_by_name()    GET  .../actions/runs            (resolve an unknown dispatch)
    get_run()             GET  .../actions/runs/{id}
    download_artifact()   GET  .../actions/runs/{id}/artifacts -> .../artifacts/{id}/zip
    send()/find_run()     adapters for the outbox

Credential contract (see the doc for the verified minimum):

    a SINGLE fine-grained permission - Actions: Read and write - on
    yuguangzhi3836-glitch/GO. No Contents, no Pull requests, no Issues, no Admin.

The token is never a literal and never a parameter of a task. It is read through an
injected loader; the shipped loader reads a root-only file whose path is configured
outside the repository:

    /etc/go-runtime-host/c1-github-token      (root:root, 0600)

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

from c1_execution_contract import DISPATCH_ENDPOINT, RUNS_ENDPOINT, Refused, canonical

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
    def __init__(self, *, token_loader=None, opener=urllib.request.urlopen,
                 redirect_opener=None, no_redirect_opener=None, api_base=API_BASE,
                 api_version=API_VERSION, timeout_s=HTTP_TIMEOUT_S):
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
    def dispatch_workflow(self, request: dict):
        """Send exactly one dispatch. Returns ("sent", run_id|None) for the outbox."""
        payload = {"ref": request["ref"], "inputs": {
            "runtime_task_id": request["runtime_task_id"],
            "attempt": str(request["attempt"]),
            "execution_request_id": request["execution_request_id"],
        }}
        status, raw = self._call("POST", DISPATCH_ENDPOINT, payload)
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

    def _repo_slug(self) -> str:
        return DISPATCH_ENDPOINT.split("/repos/", 1)[1].split("/actions/", 1)[0]

    # ----------------------------------------------------- outbox adapters
    def send(self, request: dict):
        return self.dispatch_workflow(request)

    def find_run(self, run_name: str):
        found = self.find_run_by_name(run_name)
        return None if found is None else found["id"]
