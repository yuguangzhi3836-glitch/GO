"""The authoritatively declared C14 rule sources, resolved read-only.

Why this module exists
----------------------
C14 used to review against three rule-set names our own backend hard-coded. They were never the
Owner's rule names: they were our own engineering abstraction, no document in the repository
carried them, and every version was recorded as ``unversioned``. A record that declares them
looks exactly like a record that declares real rules, which is worse than declaring nothing
(CCV1-145C). A review whose rule set is a constant we invented cannot say anything about
compliance at all.

So the rule set is data now, and it lives where the reviewed candidate cannot reach it:

* ``docs/governance/C14_RULE_SOURCES.json`` on the **default branch** lists real repository
  paths. A human maintains paths and nothing else - no derived rule id, no version filler,
  no declared_by, no completeness flag, no signature.
* The bytes are read read-only from **one resolved commit** of the default branch, so the
  manifest and every rule text come from the same moment (``authority_commit``).
* The candidate under review supplies none of it. If the candidate's own change surface
  touches the manifest or any declared rule text the round is BLOCKED
  (``GOVERNANCE_SOURCE_CHANGED``): a candidate does not get to edit the rules that judge it.

Fail-closed, and decided **before any AI call**: a manifest that is missing, unparsable or
empty, a source path that does not exist, or a source that cannot be read each produce a
deterministic BLOCKED record (``decision_origin = DETERMINISTIC_PRECHECK``) with the AI never
called. There is no fallback rule set and no default name anywhere in this module.

What this module deliberately does NOT do: it does not invent a rule id, a rule name or a
version for any source, and it does not hash a hash. ``rule_input_sha256`` answers exactly one
question - "are the rule bytes the AI saw the bytes of this rule input?" - and
``rule_sources`` carries the machine identity of each source (path, git blob, digest).
"""
from __future__ import annotations

import base64
import hashlib
import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lite_ai_reviewer  # noqa: E402
from lite_canonical import digest, digest_bytes  # noqa: E402
from lite_errors import DETERMINISTIC_PRECHECK  # noqa: E402

MANIFEST_PATH = "docs/governance/C14_RULE_SOURCES.json"
MANIFEST_SCHEMA_VERSION = "1"

#: The default branch. Deliberately a constant rather than a dispatch input: the authority
#: must not be choosable by whoever triggers the run.
DEFAULT_AUTHORITY_REF = "main"

#: The machine codes a failed precheck may carry. Each one is a different real condition.
GOVERNANCE_SOURCE_CHANGED = "GOVERNANCE_SOURCE_CHANGED"
MANIFEST_ABSENT = "RULE_MANIFEST_ABSENT"
MANIFEST_INVALID = "RULE_MANIFEST_INVALID"
NO_SOURCES = "RULE_MANIFEST_HAS_NO_SOURCES"
SOURCE_PATH_MISSING = "RULE_SOURCE_PATH_MISSING"
SOURCE_UNREADABLE = "RULE_SOURCE_UNREADABLE"

FAILURE_REASONS = (
    GOVERNANCE_SOURCE_CHANGED,
    MANIFEST_ABSENT,
    MANIFEST_INVALID,
    NO_SOURCES,
    SOURCE_PATH_MISSING,
    SOURCE_UNREADABLE,
)



class FetchFailed(Exception):
    """One read-only contents read did not produce bytes."""

    def __init__(self, path: str, *, status=None, detail: str = ""):
        super().__init__(detail or path)
        self.path = path
        self.status = status
        self.detail = detail or path


def git_blob_sha(raw: bytes) -> str:
    """The SHA git itself would give these bytes (blob header, length, content)."""
    return hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()


def sha256_of(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def identity(source: dict) -> dict:
    """The machine identity of one rule source.

    There is no ``rule_id`` and no ``rule_name`` here. A rule that does not name itself gets
    no name from us, so identity is three facts - path, git blob, digest - and none of them
    is a string we made up.
    """
    return {
        "repository_path": source["repository_path"],
        "git_blob_sha": source["git_blob_sha"],
        "sha256": source["sha256"],
    }


def rule_input_digest(record: dict) -> str:
    """One digest over the resolved rule input.

    It binds which commit the rules came from and the bytes of each source (via its
    ``sha256``), and deliberately not the rule text a second time: the text is already
    bound by its digest. This is not a hash wrapped around another hash.
    """
    return digest({
        "status": record["status"],
        "authority_commit": record.get("authority_commit"),
        "reason": record.get("reason"),
        "sources": [identity(source) for source in record.get("sources", [])],
    })


def _usable_path(value) -> bool:
    """A repository-relative path, and nothing that tries to walk out of the repository."""
    if not isinstance(value, str) or not value.strip():
        return False
    path = value.strip()
    if path.startswith("/") or "\\" in path or ":" in path:
        return False
    return ".." not in path.split("/")


def resolve(*, ref: str = DEFAULT_AUTHORITY_REF, resolve_commit, read_file, changed_paths=()) -> dict:
    """Resolve the declared rule sources, or say deterministically why we cannot.

    ``resolve_commit(ref) -> str``        the commit the default branch points at
    ``read_file(commit, path) -> bytes``  one read-only contents read

    Both are injected, so the whole rule can be exercised offline; the HTTP versions are in
    :func:`github_reader`. Every failure returns a record - this function never raises for a
    governance condition, because the caller has to be able to *record* the refusal.
    """
    changed = {str(path).strip() for path in changed_paths if str(path).strip()}

    def blocked(reason: str, detail: str = "", *, authority_commit=None, sources=None) -> dict:
        record = {
            "status": "BLOCKED",
            "reason": reason,
            "detail": detail,
            "authority_ref": ref,
            "authority_commit": authority_commit,
            "manifest_path": MANIFEST_PATH,
            "sources": list(sources or []),
        }
        record["rule_input_sha256"] = rule_input_digest(record)
        record["blocking_issues"] = [f"{reason}: {detail}" if detail else reason]
        return record

    # A candidate may not edit the rules that judge it. This needs no read at all, so it is
    # checked first - it is the most specific signal we can have.
    if MANIFEST_PATH in changed:
        return blocked(GOVERNANCE_SOURCE_CHANGED, MANIFEST_PATH)

    try:
        authority_commit = resolve_commit(ref)
    except Exception as error:  # noqa: BLE001 - an unresolvable ref is a closed door
        return blocked(MANIFEST_ABSENT, f"cannot resolve {ref}: {type(error).__name__}")
    if not isinstance(authority_commit, str) or len(authority_commit) != 40:
        return blocked(MANIFEST_ABSENT, f"cannot resolve {ref}: no commit sha")

    try:
        manifest_raw = read_file(authority_commit, MANIFEST_PATH)
    except FetchFailed as error:
        return blocked(MANIFEST_ABSENT, error.detail, authority_commit=authority_commit)

    try:
        manifest = json.loads(manifest_raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        return blocked(MANIFEST_INVALID, f"not JSON: {type(error).__name__}", authority_commit=authority_commit)
    if not isinstance(manifest, dict):
        return blocked(MANIFEST_INVALID, "not an object", authority_commit=authority_commit)
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        return blocked(MANIFEST_INVALID, "schema_version", authority_commit=authority_commit)

    declared = manifest.get("sources")
    if not isinstance(declared, list):
        return blocked(MANIFEST_INVALID, "sources is not a list", authority_commit=authority_commit)
    if not declared:
        return blocked(NO_SOURCES, "sources is empty", authority_commit=authority_commit)
    if not all(_usable_path(path) for path in declared):
        return blocked(MANIFEST_INVALID, "sources contains an unusable path", authority_commit=authority_commit)

    paths = [path.strip() for path in declared]
    if len(set(paths)) != len(paths):
        return blocked(MANIFEST_INVALID, "sources repeats a path", authority_commit=authority_commit)

    touched = sorted(changed & set(paths))
    if touched:
        return blocked(GOVERNANCE_SOURCE_CHANGED, ", ".join(touched), authority_commit=authority_commit)

    sources = []
    for path in paths:
        try:
            raw = read_file(authority_commit, path)
        except FetchFailed as error:
            reason = SOURCE_PATH_MISSING if error.status == 404 else SOURCE_UNREADABLE
            return blocked(reason, error.detail, authority_commit=authority_commit)
        except Exception as error:  # noqa: BLE001 - anything unreadable is closed
            return blocked(SOURCE_UNREADABLE, f"{type(error).__name__} for {path}",
                           authority_commit=authority_commit)
        if not raw:
            return blocked(SOURCE_UNREADABLE, f"{path} is empty", authority_commit=authority_commit)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            # Replace-on-error would let the text and its digest disagree, which is the one
            # thing this whole mechanism exists to prevent.
            return blocked(SOURCE_UNREADABLE, f"{path} is not UTF-8", authority_commit=authority_commit)
        sources.append({
            "repository_path": path,
            "git_blob_sha": git_blob_sha(raw),
            "sha256": sha256_of(raw),
            "rule_text": text,
        })

    record = {
        "status": "OK",
        "reason": None,
        "detail": "",
        "authority_ref": ref,
        "authority_commit": authority_commit,
        "manifest_path": MANIFEST_PATH,
        "manifest_blob_sha": git_blob_sha(manifest_raw),
        "manifest_sha256": sha256_of(manifest_raw),
        "sources": sources,
        "blocking_issues": [],
    }
    record["rule_input_sha256"] = rule_input_digest(record)
    return record


def github_reader(repository: str, token: str, *, timeout: int = 60):
    """``(resolve_commit, read_file)`` over the GitHub contents API - read-only.

    Two GETs and nothing else: no new service, no new credential, no new permission scope.
    The blob digest is recomputed from the returned bytes rather than taken from the API's
    own ``sha`` field, for the same reason as CCV1-145B D-2: a value that is reported must
    not be the only evidence for itself.
    """
    if not repository:
        raise ValueError("repository is required")
    if not token:
        raise ValueError("token is required")

    def _get(path: str, url: str) -> bytes:
        request = urllib.request.Request(url, headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "go-c13-c14-lite-rule-input",
        })
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            raise FetchFailed(path, status=error.code, detail=f"HTTP {error.code} for {path}") from error
        except Exception as error:  # noqa: BLE001 - any transport failure is closed
            raise FetchFailed(path, detail=f"{type(error).__name__} for {path}") from error

    def resolve_commit(ref: str) -> str:
        url = f"https://api.github.com/repos/{repository}/commits/{urllib.parse.quote(ref)}"
        payload = json.loads(_get(ref, url).decode("utf-8"))
        sha = payload.get("sha") if isinstance(payload, dict) else None
        if not isinstance(sha, str) or len(sha) != 40:
            raise FetchFailed(ref, detail=f"no commit sha for {ref}")
        return sha

    def read_file(commit: str, path: str) -> bytes:
        quoted = "/".join(urllib.parse.quote(part) for part in path.split("/") if part)
        url = (f"https://api.github.com/repos/{repository}/contents/{quoted}"
               f"?ref={urllib.parse.quote(commit)}")
        payload = json.loads(_get(path, url).decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("encoding") != "base64":
            raise FetchFailed(path, detail=f"not a base64 file object: {path}")
        content = payload.get("content")
        if not isinstance(content, str):
            raise FetchFailed(path, detail=f"no inline content: {path}")
        raw = base64.b64decode(content)
        if payload.get("sha") != git_blob_sha(raw):
            raise FetchFailed(path, detail=f"blob sha does not match the returned bytes: {path}")
        return raw

    return resolve_commit, read_file


def blocked_review_outcome(role: str, facts: dict, rule_input: dict) -> dict:
    """The only outcome a failed rule-input precheck may produce.

    A recorded BLOCKED with the AI **never called**, and the record says so: no provider, no
    model, no fabricated execution id, no opinion digest. A reader can tell it apart from an
    AI verdict without knowing anything about this code.
    """
    reason = rule_input.get("reason") or NO_SOURCES
    detail = rule_input.get("detail") or ""
    issues = list(rule_input.get("blocking_issues") or [])
    if not issues:
        issues = [f"{reason}: {detail}" if detail else reason]
    return {
        "role": role,
        "verdict": "BLOCKED",
        "opinion": None,
        "opinion_sha256": None,
        # The named reason travels with the refusal, so the sealed record can say what was
        # wrong instead of merely "blocked".
        "blocking_issues": issues,
        "prompt_sha256": digest_bytes(lite_ai_reviewer.build_prompt(role, facts).encode("utf-8")),
        "input_sha256": digest(facts),
        "ai_provider": None,
        "ai_model": None,
        "ai_execution_id": None,
        "failure_class": None,
        "decision_origin": DETERMINISTIC_PRECHECK,
        "ai_called": False,
        "detail": detail,
    }
