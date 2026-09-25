"""SECRET_LEAK_SCAN: prove this round wrote no credential anywhere it could be read.

A credential test round is exactly the kind of round that leaks one, so the scan is a
tool with tests rather than a promise in a report. It looks for the shapes that
actually appear in this project:

    GitHub token prefixes      github_pat_ / ghp_ / gho_ / ghu_ / ghs_ / ghr_
    transport headers          Authorization: <scheme> <value>
    query-string credentials   token= / access_token= / sig= (a signed URL is a bearer
                               capability in its own right)
    private keys               -----BEGIN * PRIVATE KEY-----
    cloud access keys          AKIA... / ASIA...

A hit is reported by pattern name, file and line number only. The matched text is
never echoed: a leak scanner that prints the secret is a leak.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import re
import sys

PASS = "SECRET_LEAK_SCAN_PASS"
FAIL = "SECRET_LEAK_SCAN_FAIL"


@dataclasses.dataclass(frozen=True)
class Pattern:
    name: str
    regex: re.Pattern


PATTERNS = (
    Pattern("github_fine_grained_pat", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    Pattern("github_classic_pat", re.compile(r"\bghp_[A-Za-z0-9]{30,}")),
    Pattern("github_oauth_token", re.compile(r"\bgho_[A-Za-z0-9]{30,}")),
    Pattern("github_user_token", re.compile(r"\bghu_[A-Za-z0-9]{30,}")),
    Pattern("github_app_token", re.compile(r"\bghs_[A-Za-z0-9]{30,}")),
    Pattern("github_refresh_token", re.compile(r"\bghr_[A-Za-z0-9]{30,}")),
    # A literal credential in a header. The value must look like a credential: a
    # placeholder such as ``Authorization: Bearer <token>`` or ``Bearer ${TOKEN}``
    # cannot match, because '<', '>', '$' and '{' are not in the value charset.
    Pattern("authorization_header",
            re.compile(r"Authorization\s*:\s*\S+\s+[A-Za-z0-9_\-\.]{20,}")),
    Pattern("bearer_literal", re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{20,}")),
    Pattern("query_access_token", re.compile(r"[?&](access_token|token|sig)=[A-Za-z0-9%_\-\.]{16,}")),
    Pattern("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    Pattern("aws_access_key_id", re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{12,}")),
)

#: Files whose whole point is to describe these patterns, so they are exempt.
#: Deliberately a single file: a broader exemption is how a real secret gets
#: pasted next to a suppression comment and never noticed. Test vectors elsewhere
#: are built by string concatenation so the literal never appears in a source line.
SELF_EXEMPT = {"lw_secret_scan.py"}

SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".zip", ".pdf", ".ico", ".woff", ".woff2"}

#: Findings a human has read and judged benign. Keyed by repository-relative path
#: and the pattern name, with the reason recorded next to it. This is deliberately a
#: table in the scanner's own source rather than a suppression comment: it is
#: reviewable in a diff, it cannot be added by whoever pastes a secret, and every
#: entry is re-checked by a test that the file still exists.
REVIEWED_EXCEPTIONS = {
    ("control-plane/boss-test-pr-live-integration-v1/tests/test_live_integration.py",
     "private_key_block"):
        "test vector for the redaction filter: the literal is asserted to be replaced "
        "with UNCLASSIFIED_REJECT, so its presence in the source is the point",
    ("hk-staging/source/agent/hk_agent/agent053_regression.py",
     "private_key_block"):
        "test vector for the agent's _safe_stream redaction: the PEM header sits inside "
        "a string whose preview is asserted NOT to contain it",
    ("deliverables/CP11_DEPTH48_SOURCE_COMPOSITE_PARENT_20260913/source/hk-staging/"
     "source/agent/hk_agent/agent053_regression.py",
     "private_key_block"):
        "the same archived source snapshot duplicated inside a deliverables bundle; "
        "same benign test vector, not a second occurrence",
}

#: Directories never worth reading: version-control internals hold packed binary data
#: that would be decoded as text for minutes and can only produce false positives.
SKIP_DIRECTORIES = {".git", ".hg", ".svn", "node_modules", "__pycache__"}


def _relative(origin: str) -> str:
    return origin.replace("\\", "/")


def _reviewed_reason(origin: str, pattern_name: str):
    """Match an exception by path suffix.

    Suffix matching keeps the table working whether the scan was invoked with a
    repository-relative path or an absolute one, while still being specific: a
    same-named file under a different directory does not match, because the whole
    relative path has to line up.
    """
    normalized = _relative(origin)
    for (relative_path, exception_pattern), reason in REVIEWED_EXCEPTIONS.items():
        if exception_pattern != pattern_name:
            continue
        if normalized == relative_path or normalized.endswith("/" + relative_path):
            return reason
    return None


def scan_text(text: str, *, origin: str) -> list:
    """Return hits as dicts. The matched substring is deliberately not included.

    A hit matching a reviewed exception is still returned, marked, so that nothing is
    silently dropped: ``scan_paths`` separates them from the gate.
    """
    hits = []
    for pattern in PATTERNS:
        for match in pattern.regex.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            reason = _reviewed_reason(origin, pattern.name)
            hits.append({"pattern": pattern.name, "origin": origin, "line": line,
                         "match_redacted": True,
                         "reviewed_exception": bool(reason),
                         "reviewed_reason": reason})
    return hits


def scan_file(path: pathlib.Path) -> list:
    if path.suffix.lower() in SKIP_SUFFIXES:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return scan_text(text, origin=str(path))


def scan_paths(paths) -> dict:
    hits = []
    scanned = 0
    for raw in paths:
        path = pathlib.Path(raw)
        if path.is_dir():
            files = [p for p in path.rglob("*")
                     if p.is_file() and not (SKIP_DIRECTORIES & set(p.parts))]
        else:
            files = [path]
        for file_path in files:
            if file_path.name in SELF_EXEMPT:
                continue
            scanned += 1
            hits.extend(scan_file(file_path))
    gate = [hit for hit in hits if not hit["reviewed_exception"]]
    reviewed = [hit for hit in hits if hit["reviewed_exception"]]
    return {
        "schema_version": "go.c13c14.secret_scan.v1",
        "status": FAIL if gate else PASS,
        "files_scanned": scanned,
        "patterns": [p.name for p in PATTERNS],
        "hit_count": len(gate),
        "hits": gate,
        "reviewed_exception_count": len(reviewed),
        "reviewed_exceptions": reviewed,
        "secret_values_emitted": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", default=["."])
    parser.add_argument("--json-out")
    args = parser.parse_args(argv)
    report = scan_paths(args.paths)
    if args.json_out:
        pathlib.Path(args.json_out).write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "files_scanned", "hit_count")}))
    for hit in report["hits"]:
        print(f"  {hit['pattern']} @ {hit['origin']}:{hit['line']}")
    return 0 if report["status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
