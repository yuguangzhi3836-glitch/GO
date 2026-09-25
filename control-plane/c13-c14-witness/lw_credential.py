"""The GitHub credential that CC/HK witnesses are allowed to hold.

Purpose, scope and custody are declared here as data so that the install script,
the docs, the readback tool and the tests all read the **same** statement of what
this credential is for. A credential whose purpose lives only in a README drifts.

Scope, stated as narrowly as the witness actually needs:

    Repository          yuguangzhi3836-glitch/GO      (one repository, no "all repos")
    Actions             read
    Contents            read
    Metadata            read                          (mandatory on fine-grained PATs)

Everything else is a refusal, listed explicitly in ``FORBIDDEN_PERMISSIONS`` so that
"we did not ask for write" is checkable rather than implied.

Custody: the token lives in a root-owned file inside the existing, already
``0700`` key directory on each host. It is read at call time and never printed,
serialised, logged or committed. ``Credential.summary()`` is the only thing any
evidence file may contain, and it carries a *fingerprint*, not the value.
"""
from __future__ import annotations

import dataclasses
import hashlib
import pathlib

# --- what this credential is for -------------------------------------------------

CREDENTIAL_PURPOSE = "GO C13/C14 Lite acceptance witness: GitHub Actions readback only"
CREDENTIAL_SURFACE = "github-rest-actions-readback"

REPOSITORY = "yuguangzhi3836-glitch/GO"

REQUIRED_PERMISSIONS = {
    "actions": "read",
    "contents": "read",
    "metadata": "read",
}

FORBIDDEN_PERMISSIONS = (
    "actions:write",
    "contents:write",
    "issues:write",
    "pull_requests:write",
    "deployments:write",
    "packages:write",
    "administration:write",
    "secrets:write",
    "workflows:write",
    "members:write",
)

# --- where it lives ---------------------------------------------------------------

CREDENTIAL_PATH = {
    "cc": "/etc/go-command-center/keys/github-witness-reader.token",
    "hk": "/etc/go-hk-agent/keys/github-witness-reader.token",
}

#: The key directory owners as observed on the two hosts. The credential inherits
#: the same custody as every other secret already in that directory.
CREDENTIAL_OWNER = {"cc": "root:root", "hk": "go-hk-agent:go-hk-agent"}
CREDENTIAL_MODE = "0600"

#: Pre-existing, mis-scoped credential. Kept in the model because the round report
#: must explain what it is and why it does not work, not merely replace it.
LEGACY_PATHS = {
    "cc": "/etc/go-command-center/keys/github-requests-reader.token",
}

#: Endpoints the witness is allowed to call. A readback tool that calls anything
#: else is out of scope by construction.
#:
#: ``/repos/{repo}/actions/permissions`` is intentionally absent: it requires
#: administrative scope, and the whole point of this credential is that it holds none.
ALLOWED_ENDPOINTS = (
    "GET /repos/{repo}/actions/runs/{run_id}",
    "GET /repos/{repo}/actions/runs/{run_id}/artifacts",
    "GET /repos/{repo}/actions/artifacts/{artifact_id}",
    "GET /repos/{repo}/actions/artifacts/{artifact_id}/zip",
    "GET /user",
    "GET /rate_limit",
)

SECRET_PREFIXES = ("github_pat_", "ghp_", "gho_", "ghu_", "ghs_", "ghr_")


def class_fingerprint(token: str) -> str:
    """Which kind of GitHub credential this is. Never returns any of the value."""
    for prefix in SECRET_PREFIXES:
        if token.startswith(prefix):
            return prefix
    return "other"


def token_fingerprint(token: str) -> str:
    """A stable audit handle for a token, so "same secret?" is answerable without
    storing the secret. SHA-256 over a high-entropy value is not reversible."""
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]


@dataclasses.dataclass(frozen=True)
class Credential:
    """A loaded credential. The value is private to the object and never rendered."""

    token: str
    source: str
    fake: bool = False

    def __repr__(self) -> str:  # pragma: no cover - the point is the redaction
        return f"Credential(source={self.source!r}, value=<redacted>, length={len(self.token)})"

    __str__ = __repr__

    @property
    def length(self) -> int:
        return len(self.token)

    @property
    def klass(self) -> str:
        return class_fingerprint(self.token)

    def summary(self) -> dict:
        """Everything an evidence file is allowed to say about this credential."""
        return {
            "source": self.source,
            "present": bool(self.token),
            "length": self.length,
            "class": self.klass,
            "fingerprint": token_fingerprint(self.token),
            "value_redacted": True,
            "fake": self.fake,
        }


class CredentialError(RuntimeError):
    """Missing, empty or malformed credential file."""


def load(path: str | pathlib.Path, *, fake: bool = False) -> Credential:
    """Read a credential from a file. Trailing newline and whitespace are stripped.

    Never logs or returns the value anywhere other than inside the object.
    """
    file_path = pathlib.Path(path)
    if not file_path.is_file():
        raise CredentialError("credential_file_missing")
    raw = file_path.read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        raise CredentialError("credential_file_empty")
    if any(character.isspace() for character in raw):
        raise CredentialError("credential_value_contains_whitespace")
    return Credential(token=raw, source=str(file_path), fake=fake)


def from_value(value: str, *, source: str, fake: bool = False) -> Credential:
    """Wrap an already-loaded value (used by tests and by in-run GITHUB_TOKEN)."""
    stripped = (value or "").strip()
    if not stripped:
        raise CredentialError("credential_value_empty")
    return Credential(token=stripped, source=source, fake=fake)


def environment_variable(host: str) -> str:
    """The env var a host's tooling should use, so no path is hard-coded in tests."""
    return "GO_WITNESS_GITHUB_TOKEN"


def install_plan(host: str) -> dict:
    """The exact install operations, as data, so the script and docs cannot drift."""
    if host not in CREDENTIAL_PATH:
        raise CredentialError(f"unknown_host:{host}")
    return {
        "host": host,
        "path": CREDENTIAL_PATH[host],
        "owner": CREDENTIAL_OWNER[host],
        "mode": CREDENTIAL_MODE,
        "purpose": CREDENTIAL_PURPOSE,
        "repository": REPOSITORY,
        "permissions": dict(REQUIRED_PERMISSIONS),
        "must_not_grant": list(FORBIDDEN_PERMISSIONS),
        "directory_permissions_unchanged": True,
        "restart_services": False,
    }


def scope_statement() -> dict:
    """The minimal-scope request, in the shape an Owner action list needs."""
    return {
        "repository": REPOSITORY,
        "repository_access": "only_select_repositories -> " + REPOSITORY,
        "permissions": dict(REQUIRED_PERMISSIONS),
        "must_not_grant": list(FORBIDDEN_PERMISSIONS),
        "credential_type_preference": "fine-grained personal access token (read-only)",
    }
