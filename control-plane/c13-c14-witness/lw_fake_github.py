"""A local stand-in for the two GitHub endpoints involved in an artifact download.

It exists to make one specific behaviour testable offline, because that behaviour is
the whole point of CCV1-144A:

    the API endpoint answers 302 and points at a storage URL whose authorisation is
    in the query string; presenting an ``Authorization`` header to that storage URL
    makes it refuse the request.

``storage_rejects_authorization`` reproduces that refusal with the same status code
and error shape a real Azure Blob Storage endpoint returns, so the test can assert
that the *naive* one-step download fails and the two-step download succeeds. Without
that counter-test, the fixed code path is indistinguishable from a code path that was
never broken.

This is a test double only. It is never imported by production modules.
"""
from __future__ import annotations

import hashlib
import io
import json
import threading
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RUN_ID_DEFAULT = 36110672586
STORAGE_AUTH_ERROR = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    "<Error><Code>InvalidAuthenticationInfo</Code>"
    "<Message>Server failed to authenticate the request.</Message></Error>"
)


def make_zip(members: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


class FakeGitHub:
    """One server, two surfaces: ``/api/...`` and ``/storage/...``."""

    def __init__(
        self,
        *,
        token: str = "fake-github-token-for-tests-not-a-credential-shape",
        zip_bytes: bytes | None = None,
        artifact_name: str = "c13c14-lite-c14-" + "f" * 40,
        artifact_id: int = 10853505252,
        run_id: int = RUN_ID_DEFAULT,
        run_status: str = "completed",
        run_conclusion: str = "success",
        run_head_sha: str = "c" * 40,
        run_path: str = ".github/workflows/c14-rule-compliance.yml",
        artifact_expired: bool = False,
        artifact_run_id: int | None = None,
        artifact_digest: str | None = None,
        run_lookup_http: int = 200,
        artifact_list_http: int = 200,
        api_answers_directly: bool = False,
        storage_rejects_authorization: bool = True,
        signed_ok: bool = True,
    ) -> None:
        self.token = token
        self.zip_bytes = zip_bytes if zip_bytes is not None else make_zip({"bundle.json": b"{}"})
        self.artifact_name = artifact_name
        self.artifact_id = artifact_id
        self.run_id = run_id
        self.run_status = run_status
        self.run_conclusion = run_conclusion
        self.run_head_sha = run_head_sha
        self.run_path = run_path
        self.artifact_expired = artifact_expired
        self.artifact_run_id = artifact_run_id if artifact_run_id is not None else run_id
        self.artifact_digest = artifact_digest or (
            "sha256:" + hashlib.sha256(self.zip_bytes).hexdigest())
        self.run_lookup_http = run_lookup_http
        self.artifact_list_http = artifact_list_http
        self.api_answers_directly = api_answers_directly
        self.storage_rejects_authorization = storage_rejects_authorization
        self.signed_ok = signed_ok
        self.requests: list = []
        self._server = None
        self._thread = None

    # --- lifecycle ----------------------------------------------------------

    def start(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):  # silence
                return

            def _record(self):
                outer.requests.append({
                    "path": urllib.parse.urlsplit(self.path).path,
                    "query_keys": sorted(urllib.parse.parse_qs(
                        urllib.parse.urlsplit(self.path).query).keys()),
                    "has_authorization": "Authorization" in self.headers,
                    "user_agent": self.headers.get("User-Agent"),
                })

            def do_GET(self):  # noqa: N802
                self._record()
                split = urllib.parse.urlsplit(self.path)
                path = split.path
                if path.startswith("/api/repos/") and path.endswith("/zip"):
                    return self._api_zip()
                if path.startswith("/api/repos/") and path.endswith("/artifacts"):
                    return self._json(outer.artifact_list_http, outer.artifact_listing())
                if path.startswith("/api/repos/") and "/actions/runs/" in path:
                    return self._json(outer.run_lookup_http, outer.run_payload())
                if path.startswith("/api/repos/") and path.count("/") == 4:
                    # bare repository read: /api/repos/{owner}/{repo}
                    return self._json(outer.run_lookup_http, outer.repository_payload())
                if path == "/api/user":
                    return self._json(200, {"login": "chenzhenxi1-sudo"})
                if path == "/storage/blob":
                    return self._storage()
                self._json(404, {"message": "Not Found"})

            def _api_zip(self):
                if self.headers.get("Authorization") != f"Bearer {outer.token}":
                    return self._json(404, {"message": "Not Found"})
                if outer.api_answers_directly:
                    return self._send(200, outer.zip_bytes, "application/zip")
                target = "/storage/blob?sig=" + ("good" if outer.signed_ok else "bad")
                self.send_response(302)
                self.send_header("Location", f"http://{self.headers['Host']}{target}")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def _storage(self):
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                if outer.storage_rejects_authorization and "Authorization" in self.headers:
                    return self._send(401, STORAGE_AUTH_ERROR.encode("utf-8"),
                                      "application/xml")
                if query.get("sig") != ["good"]:
                    return self._send(403, b"<Error><Code>AuthenticationFailed/></Error>",
                                      "application/xml")
                return self._send(200, outer.zip_bytes, "application/zip")

            def _json(self, status, payload):
                self._send(status, json.dumps(payload).encode("utf-8"),
                           "application/json")

            def _send(self, status, body, content_type):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        base = f"http://127.0.0.1:{self._server.server_address[1]}"
        return {"api_root": base + "/api", "base": base}

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def __enter__(self):
        self.urls = self.start()
        return self

    def __exit__(self, *_exc):
        self.stop()
        return False

    # --- payloads -----------------------------------------------------------

    def repository_payload(self):
        return {
            "full_name": "yuguangzhi3836-glitch/GO",
            "private": True,
            "default_branch": "main",
        }

    def run_payload(self):        return {
            "id": self.run_id,
            "status": self.run_status,
            "conclusion": self.run_conclusion,
            "run_attempt": 1,
            "head_sha": self.run_head_sha,
            "head_branch": "cc/synthetic",
            "path": self.run_path,
            "repository": {"full_name": "yuguangzhi3836-glitch/GO"},
        }

    def artifact_listing(self):
        return {
            "total_count": 1,
            "artifacts": [{
                "id": self.artifact_id,
                "name": self.artifact_name,
                "digest": self.artifact_digest,
                "size_in_bytes": len(self.zip_bytes),
                "expired": self.artifact_expired,
                "workflow_run": {"id": self.artifact_run_id},
            }],
        }
