"""Fail-closed, source-bound Evidence bundle writer.

The writer owns serialization and publication so workflows do not duplicate
fragile Python heredocs.  A bundle is visible only after every JSON document,
source binding and digest has been recomputed successfully.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any, Mapping, Sequence


SCHEMA = "go.shared-evidence.bundle.v1"
RESERVED = {
    "EVIDENCE_SCHEMA.json",
    "SOURCE_BINDING.json",
    "SOURCE_FINGERPRINT.json",
    "SOURCE_FINGERPRINT_SHA256",
    "SHA256SUMS",
}
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class EvidenceError(RuntimeError):
    """Evidence creation or verification failed closed."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + chr(10)
    ).encode("utf-8")


def strict_json(data: bytes, *, name: str) -> Any:
    try:
        text = data.decode("utf-8")
        value = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"INVALID_JSON:{name}:{exc}") from exc
    if data != canonical_json(value):
        raise EvidenceError(f"NON_CANONICAL_JSON:{name}")
    return value


def _relative(name: str) -> str:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise EvidenceError(f"UNSAFE_EVIDENCE_PATH:{name}")
    return path.as_posix()


def _hex(value: str, pattern: re.Pattern[str], field: str) -> str:
    if not pattern.fullmatch(value):
        raise EvidenceError(f"INVALID_{field.upper()}:{value}")
    return value


def _fsync_dir(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def source_fingerprint(source_root: Path, source_paths: Sequence[str]) -> tuple[dict[str, str], str]:
    root = source_root.resolve(strict=True)
    if not source_paths:
        raise EvidenceError("EMPTY_SOURCE_BINDING")
    files: dict[str, str] = {}
    for supplied in sorted(set(source_paths)):
        rel = _relative(supplied)
        path = root / rel
        if path.is_symlink() or not path.is_file():
            raise EvidenceError(f"SOURCE_NOT_REGULAR:{rel}")
        resolved = path.resolve(strict=True)
        if root not in resolved.parents:
            raise EvidenceError(f"SOURCE_ESCAPE:{rel}")
        files[rel] = sha256_bytes(path.read_bytes())
    material = b"".join(
        path.encode("utf-8") + bytes([0]) + digest.encode("ascii") + bytes([10])
        for path, digest in sorted(files.items())
    )
    return files, sha256_bytes(material)


def _manifest(files: Mapping[str, bytes]) -> bytes:
    return "".join(
        f"{sha256_bytes(data)}  {name}{chr(10)}" for name, data in sorted(files.items())
    ).encode("utf-8")


def _parse_manifest(data: bytes) -> dict[str, str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvidenceError("INVALID_SHA256SUMS_ENCODING") from exc
    if not text.endswith(chr(10)):
        raise EvidenceError("SHA256SUMS_MISSING_NEWLINE")
    parsed: dict[str, str] = {}
    for line in text.splitlines():
        if len(line) < 67 or line[64:66] != "  ":
            raise EvidenceError(f"INVALID_SHA256SUMS_LINE:{line}")
        digest, name = line[:64], _relative(line[66:])
        _hex(digest, HEX64, "sha256")
        if name in parsed:
            raise EvidenceError(f"DUPLICATE_SHA256SUMS_PATH:{name}")
        parsed[name] = digest
    return parsed


def verify_bundle(
    bundle: Path,
    *,
    expected_candidate: str | None = None,
    expected_application_tree: str | None = None,
    expected_cell: str | None = None,
    expected_task_id: str | None = None,
) -> dict[str, Any]:
    bundle = bundle.resolve(strict=True)
    if not bundle.is_dir():
        raise EvidenceError("BUNDLE_NOT_DIRECTORY")
    actual_paths = {
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if any(path.is_symlink() for path in bundle.rglob("*")):
        raise EvidenceError("BUNDLE_SYMLINK_REJECTED")
    if "SHA256SUMS" not in actual_paths:
        raise EvidenceError("SHA256SUMS_MISSING")
    manifest = _parse_manifest((bundle / "SHA256SUMS").read_bytes())
    expected_paths = actual_paths - {"SHA256SUMS"}
    if set(manifest) != expected_paths:
        raise EvidenceError("SHA256SUMS_FILESET_MISMATCH")
    for name, expected in manifest.items():
        if sha256_bytes((bundle / name).read_bytes()) != expected:
            raise EvidenceError(f"SHA256_MISMATCH:{name}")

    schema = strict_json((bundle / "EVIDENCE_SCHEMA.json").read_bytes(), name="EVIDENCE_SCHEMA.json")
    if schema != {"schema": SCHEMA, "version": 1}:
        raise EvidenceError("EVIDENCE_SCHEMA_MISMATCH")
    binding = strict_json((bundle / "SOURCE_BINDING.json").read_bytes(), name="SOURCE_BINDING.json")
    fingerprint = strict_json(
        (bundle / "SOURCE_FINGERPRINT.json").read_bytes(), name="SOURCE_FINGERPRINT.json"
    )
    if not isinstance(fingerprint, dict) or not fingerprint:
        raise EvidenceError("EMPTY_SOURCE_FINGERPRINT")
    for name, digest in fingerprint.items():
        _relative(name)
        _hex(digest, HEX64, "source_file_sha256")
    material = b"".join(
        name.encode("utf-8") + bytes([0]) + digest.encode("ascii") + bytes([10])
        for name, digest in sorted(fingerprint.items())
    )
    computed_fingerprint = sha256_bytes(material)
    fingerprint_text = (bundle / "SOURCE_FINGERPRINT_SHA256").read_bytes()
    if fingerprint_text != (computed_fingerprint + chr(10)).encode("ascii"):
        raise EvidenceError("SOURCE_FINGERPRINT_DIGEST_MISMATCH")

    required = {
        "schema",
        "cell",
        "task_id",
        "candidate_commit",
        "application_tree",
        "source_files",
        "source_fingerprint_sha256",
    }
    if not isinstance(binding, dict) or not required.issubset(binding):
        raise EvidenceError("SOURCE_BINDING_SCHEMA_MISMATCH")
    if binding["schema"] != SCHEMA:
        raise EvidenceError("SOURCE_BINDING_SCHEMA_MISMATCH")
    _hex(binding["candidate_commit"], HEX40, "candidate_commit")
    _hex(binding["application_tree"], HEX40, "application_tree")
    if binding.get("product_source_fingerprint_sha256") is not None:
        _hex(binding["product_source_fingerprint_sha256"], HEX64, "product_source_fingerprint")
    if binding["source_files"] != len(fingerprint):
        raise EvidenceError("SOURCE_FILE_COUNT_MISMATCH")
    if binding["source_fingerprint_sha256"] != computed_fingerprint:
        raise EvidenceError("SOURCE_BINDING_FINGERPRINT_MISMATCH")
    expected = {
        "candidate_commit": expected_candidate,
        "application_tree": expected_application_tree,
        "cell": expected_cell,
        "task_id": expected_task_id,
    }
    for field, value in expected.items():
        if value is not None and binding.get(field) != value:
            raise EvidenceError(f"SOURCE_BINDING_{field.upper()}_MISMATCH")
    for path in sorted(actual_paths):
        if path.endswith(".json"):
            strict_json((bundle / path).read_bytes(), name=path)
    return {
        "schema": SCHEMA,
        "candidate_commit": binding["candidate_commit"],
        "application_tree": binding["application_tree"],
        "source_fingerprint_sha256": computed_fingerprint,
        "files": len(actual_paths),
        "sha256sums_sha256": sha256_bytes((bundle / "SHA256SUMS").read_bytes()),
    }


def write_bundle(
    target: Path,
    *,
    source_root: Path,
    source_paths: Sequence[str],
    cell: str,
    task_id: str,
    candidate_commit: str,
    application_tree: str,
    payload_files: Mapping[str, bytes] | None = None,
    json_documents: Mapping[str, Any] | None = None,
    product_source_fingerprint_sha256: str | None = None,
) -> dict[str, Any]:
    candidate_commit = _hex(candidate_commit, HEX40, "candidate_commit")
    application_tree = _hex(application_tree, HEX40, "application_tree")
    if not re.fullmatch(r"(?:C(?:0[1-9]|1[0-4])|SHARED)", cell):
        raise EvidenceError(f"INVALID_CELL:{cell}")
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{2,127}", task_id):
        raise EvidenceError(f"INVALID_TASK_ID:{task_id}")
    if product_source_fingerprint_sha256 is not None:
        _hex(product_source_fingerprint_sha256, HEX64, "product_source_fingerprint")
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise EvidenceError("TARGET_ALREADY_EXISTS")

    fingerprint, fingerprint_digest = source_fingerprint(source_root, source_paths)
    files: dict[str, bytes] = {}
    for name, data in (payload_files or {}).items():
        rel = _relative(name)
        if rel in RESERVED:
            raise EvidenceError(f"RESERVED_EVIDENCE_PATH:{rel}")
        if not isinstance(data, bytes):
            raise EvidenceError(f"PAYLOAD_NOT_BYTES:{rel}")
        if rel.endswith(".json"):
            strict_json(data, name=rel)
        files[rel] = data
    for name, value in (json_documents or {}).items():
        rel = _relative(name)
        if rel in RESERVED or rel in files or not rel.endswith(".json"):
            raise EvidenceError(f"INVALID_JSON_EVIDENCE_PATH:{rel}")
        files[rel] = canonical_json(value)
    files["EVIDENCE_SCHEMA.json"] = canonical_json({"schema": SCHEMA, "version": 1})
    files["SOURCE_FINGERPRINT.json"] = canonical_json(fingerprint)
    files["SOURCE_FINGERPRINT_SHA256"] = (fingerprint_digest + chr(10)).encode("ascii")
    binding: dict[str, Any] = {
        "schema": SCHEMA,
        "cell": cell,
        "task_id": task_id,
        "candidate_commit": candidate_commit,
        "application_tree": application_tree,
        "source_files": len(fingerprint),
        "source_fingerprint_sha256": fingerprint_digest,
    }
    if product_source_fingerprint_sha256 is not None:
        binding["product_source_fingerprint_sha256"] = product_source_fingerprint_sha256
    files["SOURCE_BINDING.json"] = canonical_json(binding)
    files["SHA256SUMS"] = _manifest(files)

    stage = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        for name, data in sorted(files.items()):
            _atomic_file(stage / name, data)
        report = verify_bundle(
            stage,
            expected_candidate=candidate_commit,
            expected_application_tree=application_tree,
            expected_cell=cell,
            expected_task_id=task_id,
        )
        _fsync_dir(stage)
        os.rename(stage, target)
        _fsync_dir(target.parent)
        return verify_bundle(
            target,
            expected_candidate=candidate_commit,
            expected_application_tree=application_tree,
            expected_cell=cell,
            expected_task_id=task_id,
        ) | {"pre_publish_sha256sums_sha256": report["sha256sums_sha256"]}
    except BaseException:
        if stage.exists():
            shutil.rmtree(stage)
        raise


def _assignments(values: Sequence[str], *, json_values: bool) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in values:
        if "=" not in value:
            raise EvidenceError(f"INVALID_ASSIGNMENT:{value}")
        name, supplied = value.split("=", 1)
        path = Path(supplied)
        result[name] = json.loads(path.read_text()) if json_values else path.read_bytes()
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--target", type=Path, required=True)
    create.add_argument("--source-root", type=Path, required=True)
    create.add_argument("--source-path", action="append", default=[], required=True)
    create.add_argument("--cell", required=True)
    create.add_argument("--task-id", required=True)
    create.add_argument("--candidate", required=True)
    create.add_argument("--application-tree", required=True)
    create.add_argument("--product-source-fingerprint")
    create.add_argument("--file", action="append", default=[])
    create.add_argument("--json", action="append", default=[])
    verify = sub.add_parser("verify")
    verify.add_argument("--bundle", type=Path, required=True)
    verify.add_argument("--candidate")
    verify.add_argument("--application-tree")
    verify.add_argument("--cell")
    verify.add_argument("--task-id")
    args = parser.parse_args(argv)
    if args.command == "create":
        report = write_bundle(
            args.target,
            source_root=args.source_root,
            source_paths=args.source_path,
            cell=args.cell,
            task_id=args.task_id,
            candidate_commit=args.candidate,
            application_tree=args.application_tree,
            payload_files=_assignments(args.file, json_values=False),
            json_documents=_assignments(args.json, json_values=True),
            product_source_fingerprint_sha256=args.product_source_fingerprint,
        )
    else:
        report = verify_bundle(
            args.bundle,
            expected_candidate=args.candidate,
            expected_application_tree=args.application_tree,
            expected_cell=args.cell,
            expected_task_id=args.task_id,
        )
    print(canonical_json(report).decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
