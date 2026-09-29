"""Artifact byte retrieval: the two-step fetch that GitHub actually requires.

Why this module exists
----------------------
``GET /repos/{owner}/{repo}/actions/artifacts/{id}/zip`` answers **302** and points
at a pre-signed Azure Blob Storage URL. That signed URL carries its own
authorisation in the query string, and the storage endpoint **rejects any request
that also carries an ``Authorization`` header**:

    <Error><Code>InvalidAuthenticationInfo</Code>
    <Message>Server failed to authenticate the request.</Message></Error>

Python's ``urllib`` follows the redirect and forwards ``Authorization`` to the new
host, so the naive ``urlopen(zip_url)`` in this resource's first version failed with
401 *even for a credential that can read Actions perfectly well*. PR #248 and
CCV1-144 both recorded that 401 as "the storage endpoint refuses our credential",
which was a misdiagnosis: the credential was fine, the header was the problem.

Hence this module:

1. asks the API for the redirect **without following it**;
2. fetches the signed URL with **no** ``Authorization`` header at all;
3. only ever records the redirect host *category*, never the signed URL, because the
   query string is itself a bearer capability.

The token is read by the caller and is never returned, printed or serialised.
"""
from __future__ import annotations

import hashlib
import urllib.error
import urllib.parse
import urllib.request

API_ROOT = "https://api.github.com"
USER_AGENT = "go-c13c14-artifact-fetch"

# Byte-retrieval outcome classes. A failure is always classified, never a PASS.
BYTES_OK = "ARTIFACT_BYTES_AVAILABLE"
BYTES_UNAVAILABLE = "ARTIFACT_BYTES_UNAVAILABLE"
STORAGE_REJECTED_CREDENTIAL = "ARTIFACT_BYTES_STORAGE_REJECTED_CREDENTIAL"
BYTES_NOT_A_ZIP = "ARTIFACT_BYTES_NOT_A_ZIP"
BYTES_DIGEST_MISMATCH = "ARTIFACT_BYTES_DIGEST_MISMATCH"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse to follow redirects: step 1 needs the ``Location`` itself."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def local_digest(raw: bytes) -> str:
    """GitHub reports artifact digests as ``sha256:<hex>`` over the zip blob."""
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def host_category(url: str) -> str:
    """Classify a URL's host without exposing the URL's (signed) query string."""
    try:
        host = urllib.parse.urlsplit(url).netloc.split("@")[-1].split(":")[0].lower()
    except ValueError:
        return "unparseable"
    if not host:
        return "none"
    if host == "api.github.com" or host.endswith(".github.com"):
        return "github-owned"
    if host.endswith(".blob.core.windows.net") or host.endswith(".windows.net"):
        return "storage-endpoint"
    return "other"


def _api_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": USER_AGENT,
    }


def request_signed_location(*, repository: str, artifact_id: int, token: str,
                            api_root: str = API_ROOT, timeout: int = 60,
                            opener=None) -> dict:
    """Step 1: learn where the bytes live, without following the redirect.

    Returns ``{"status", "location", "host_category", "raw"}``. ``location`` is the
    signed URL when the API redirects, and ``None`` when it answers 200 with the
    bytes inline (``raw`` then holds them). The caller must treat ``location`` as a
    secret; this function never logs it.
    """
    request = urllib.request.Request(
        f"{api_root}/repos/{repository}/actions/artifacts/{artifact_id}/zip",
        headers=_api_headers(token),
    )
    opener = opener or urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:
            # Some deployments answer 200 directly. Then there is nothing to strip.
            return {"status": response.status, "location": None, "raw": response.read(),
                    "host_category": "github-owned"}
    except urllib.error.HTTPError as error:
        location = error.headers.get("Location") if error.headers else None
        if error.code in (301, 302, 303, 307, 308) and location:
            return {"status": error.code, "location": location, "raw": None,
                    "host_category": host_category(location)}
        raise


def download_signed(*, location: str, timeout: int = 120, opener=None) -> dict:
    """Step 2: fetch the pre-signed URL with **no** Authorization header.

    Sending ``Authorization`` here is what produced the misdiagnosed 401, so the
    header set is deliberately minimal and asserted by a test.
    """
    request = urllib.request.Request(location, headers={"User-Agent": USER_AGENT})
    opener = opener or urllib.request.build_opener()
    try:
        with opener.open(request, timeout=timeout) as response:
            return {"status": response.status, "raw": response.read()}
    except urllib.error.HTTPError as error:
        return {"status": error.code, "raw": None,
                "error_class": STORAGE_REJECTED_CREDENTIAL if error.code in (401, 403)
                else BYTES_UNAVAILABLE}


def fetch_artifact_bytes(*, repository: str, artifact_id: int, token: str,
                         expected_digest: str | None = None,
                         api_root: str = API_ROOT, timeout: int = 60,
                         download_timeout: int = 120, opener=None) -> dict:
    """Fetch and verify one artifact's bytes. Never raises for a classified failure.

    Returns a record with the four separate states the task requires
    (``available`` / ``hashed`` / ``verified``) so that a byte-level failure can
    never be summarised as a vague single boolean.
    """
    record = {
        "available": False,
        "hashed": False,
        "verified": False,
        "bytes": None,
        "sha256": None,
        "zip_bytes": None,
        "expected_digest": expected_digest,
        "failure_class": None,
        "http_status": None,
        "redirect_host_category": None,
    }
    try:
        step1 = request_signed_location(repository=repository, artifact_id=artifact_id,
                                        token=token, api_root=api_root, timeout=timeout,
                                        opener=opener)
    except urllib.error.HTTPError as error:
        record.update(failure_class=BYTES_UNAVAILABLE, http_status=error.code)
        return record
    except (urllib.error.URLError, OSError) as error:
        record.update(failure_class=BYTES_UNAVAILABLE,
                      detail=type(error).__name__)
        return record

    record["redirect_host_category"] = step1.get("host_category")
    if step1.get("location") is None:
        raw = step1.get("raw")
        if raw is None:
            record.update(failure_class=BYTES_UNAVAILABLE, detail="no_signed_url_returned")
            return record
        step2 = {"status": step1.get("status"), "raw": raw}
    else:
        step2 = download_signed(location=step1["location"], timeout=download_timeout)
    record["http_status"] = step2.get("status")
    raw = step2.get("raw")
    if raw is None:
        record["failure_class"] = step2.get("error_class", BYTES_UNAVAILABLE)
        return record

    record["available"] = True
    record["zip_bytes"] = len(raw)
    if not raw.startswith(b"PK"):
        record["failure_class"] = BYTES_NOT_A_ZIP
        return record

    digest = local_digest(raw)
    record["hashed"] = True
    record["sha256"] = digest
    record["bytes"] = raw
    if expected_digest is not None and digest != expected_digest:
        record["failure_class"] = BYTES_DIGEST_MISMATCH
        return record
    record["verified"] = True
    return record
