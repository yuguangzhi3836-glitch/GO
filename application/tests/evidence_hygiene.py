"""Credential-safe test evidence. No network, credential validation or revocation.

This targeted Authorization/session guard complements a full secret scanner.
It is deliberately independent of the application and its database configuration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

MARKER = "[REDACTED_TEST_SESSION_TOKEN]"
KEYS = r"(?:authorization|proxy-authorization|cookie|set-cookie|access_token|refresh_token|csrf_token|id_token|client_secret|token|password|api_key|jwt_signing_key)"
QUOTES = (r'\"', r"\'", '"', "'", "&quot;", "&apos;", "&#34;", "&#39;", "&#x22;", "&#x27;")
PATTERNS = []
for quote in QUOTES:
    q = re.escape(quote)
    PATTERNS.append(("credential_field", re.compile(
        rf"(?P<head>(?:{q})?\b{KEYS}(?:{q})?\s*[:=]\s*{q})(?P<value>.*?)(?P<tail>{q})",
        re.I | re.S)))
PATTERNS.extend([
    ("credential_header", re.compile(rf"(?P<head>^[ \t]*{KEYS}\s*:\s*)(?P<value>[^\r\n]+)", re.I | re.M)),
    ("credential_assignment", re.compile(rf"(?P<head>\b{KEYS}\s*=\s*)(?P<value>[A-Za-z0-9_~+./=-]+)", re.I)),
    ("authorization_scheme", re.compile(r"(?P<head>\b(?:Bearer|Basic|Token)\s+)(?P<value>[A-Za-z0-9_~+./=-]+)", re.I)),
    ("jwt", re.compile(r"(?P<value>\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_.-]{8,})")),
])


def redact(text: str) -> tuple[str, int]:
    count = 0
    for _rule, pattern in PATTERNS:
        def replace(match):
            nonlocal count
            value = match.group("value")
            if not value or value in {MARKER, "[REDACTED_CREDENTIAL]", "null", "None"} or re.fullmatch(
                    r"(?:Bearer|Basic|Token)\s+\[REDACTED_[A-Z_]+\]", value, re.I):
                return match.group(0)
            count += 1
            start, end = match.span("value")
            whole = match.group(0)
            return whole[:start-match.start()] + MARKER + whole[end-match.start():]
        text = pattern.sub(replace, text)
    return text, count


def safe_name(path: Path) -> str:
    return redact(str(path))[0]


def files_under(root: Path):
    if root.is_symlink() or not root.exists():
        raise ValueError("UNSAFE_OR_MISSING_INPUT")
    if root.is_file():
        yield root
        return
    for path in sorted(root.rglob("*")):
        if ".git" in path.relative_to(root).parts:
            continue
        if path.is_symlink():
            raise ValueError("SYMLINK_REJECTED")
        if path.is_file():
            yield path
        elif not path.is_dir():
            raise ValueError("NON_REGULAR_FILE_REJECTED")


def transform(path: Path, data: bytes) -> tuple[bytes, int, str]:
    if len(data) > 16 * 1024 * 1024:
        raise ValueError("EVIDENCE_FILE_TOO_LARGE")
    if path.suffix.lower() in {".zip", ".gz", ".tar", ".7z", ".xz"} or data.startswith((b"PK\x03\x04", b"\x1f\x8b")):
        raise ValueError("ARCHIVE_REQUIRES_SEPARATE_SCAN")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        # Browser evidence includes PNG screenshots. Never rewrite image bytes.
        # This is a byte-string credential check, not OCR or visual certification.
        if path.suffix.lower() != ".png" or not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("UNSUPPORTED_BINARY_EVIDENCE")
        if redact(data.decode("latin1"))[1]:
            raise ValueError("CREDENTIAL_IN_BINARY_EVIDENCE")
        return data, 0, "png_bytes_only_no_ocr"
    if "\x00" in text:
        raise ValueError("NUL_IN_TEXT_EVIDENCE")
    clean, count = redact(text)
    return clean.encode("utf-8"), count, "utf8_text"


def scan(roots: list[Path]) -> dict:
    findings = []
    checked = 0
    image_count = 0
    for root in roots:
        for path in files_under(root):
            _clean, count, kind = transform(path, path.read_bytes())
            checked += 1
            image_count += kind.startswith("png")
            if count:
                findings.append({"path": safe_name(path), "redactions_required": count})
    return {"schema": "go.evidence-hygiene.scan.v1", "files_checked": checked,
            "png_byte_checks_without_ocr": image_count, "findings": findings,
            "status": "FAIL" if findings else "PASS", "scope": "authorization_and_session_credentials"}


def prepare(source: Path, destination: Path) -> dict:
    if source.is_symlink() or not source.is_dir():
        raise ValueError("SOURCE_NOT_REGULAR_DIRECTORY")
    source = source.resolve(strict=True)
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("DESTINATION_EXISTS")
    if destination.resolve().is_relative_to(source):
        raise ValueError("DESTINATION_WITHIN_SOURCE")
    destination.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    # No publishable destination exists unless every file passes validation.
    with tempfile.TemporaryDirectory(prefix=".evidence-stage-", dir=destination.parent) as temporary:
        stage = Path(temporary) / "payload"
        stage.mkdir()
        for path in files_under(source):
            relative = path.relative_to(source)
            if relative.as_posix() in {"SHA256.json", "SANITIZATION.json"}:
                continue  # These are recomputed over the sanitized output.
            if redact(relative.as_posix())[1]:
                raise ValueError("CREDENTIAL_IN_FILENAME")
            original = path.read_bytes()
            clean, count, kind = transform(path, original)
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(clean)
            entries.append({"path": relative.as_posix(), "redactions": count,
                            "original_sha256": hashlib.sha256(original).hexdigest(),
                            "sanitized_sha256": hashlib.sha256(clean).hexdigest(), "kind": kind})
        if not entries:
            raise ValueError("EMPTY_EVIDENCE")
        manifest = {"schema": "go.evidence-hygiene.sanitization.v1", "files": entries,
                    "raw_evidence_published": False, "test_verdict_modified": False}
        (stage / "SANITIZATION.json").write_text(json.dumps(manifest, indent=2) + "\n")
        result = scan([stage])
        if result["status"] != "PASS":
            raise ValueError("SANITIZED_EVIDENCE_SCAN_FAILED")
        hashes = {p.relative_to(stage).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in files_under(stage)}
        (stage / "SHA256.json").write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n")
        # Same filesystem atomic rename. The caller uploads ONLY this destination.
        stage.rename(destination)
    return {"status": "PASS", "files": len(entries), "redactions": sum(x["redactions"] for x in entries)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("stream")
    scan_parser = sub.add_parser("scan")
    scan_parser.add_argument("paths", nargs="+", type=Path)
    scan_parser.add_argument("--report", type=Path)
    stage_parser = sub.add_parser("prepare")
    stage_parser.add_argument("source", type=Path)
    stage_parser.add_argument("destination", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "stream":
            # Buffer bounded output so quoted/multiline credentials cannot leak
            # across read boundaries. Oversized output fails before any echo.
            content = sys.stdin.read(16 * 1024 * 1024 + 1)
            if len(content) > 16 * 1024 * 1024:
                raise ValueError("CAPTURED_OUTPUT_TOO_LARGE")
            sys.stdout.write(redact(content)[0])
            return 0
        if args.command == "prepare":
            result = prepare(args.source, args.destination)
        else:
            result = scan(args.paths)
            if args.report:
                args.report.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "PASS" else 1
    except Exception as error:
        # Exception text can contain a credential-bearing path: never echo it.
        print(json.dumps({"status": "ERROR", "error_type": type(error).__name__}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
