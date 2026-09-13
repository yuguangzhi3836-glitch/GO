from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
import hashlib
import json
import shutil


@dataclass(frozen=True)
class DeltaFile:
    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class DeltaManifest:
    schema_version: str
    candidate_id: str
    directive_id: str
    builder_cell: str
    immutable_parent_sha256: str
    changed_files: tuple[DeltaFile, ...]
    deleted_paths: tuple[str, ...]
    candidate_manifest_ref: str
    evidence_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            **{k: v for k, v in asdict(self).items() if k != "changed_files"},
            "changed_files": [asdict(x) for x in self.changed_files],
        }


class ThinWorkspaceError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_relative(path: str) -> str:
    p = Path(path)
    if p.is_absolute() or ".." in p.parts:
        raise ThinWorkspaceError(f"UNSAFE_DELTA_PATH:{path}")
    return p.as_posix()


def build_delta_manifest(
    *,
    root: Path,
    candidate_id: str,
    directive_id: str,
    builder_cell: str,
    immutable_parent_sha256: str,
    changed_paths: Iterable[str],
    deleted_paths: Iterable[str] = (),
    candidate_manifest_ref: str,
    evidence_refs: Iterable[str] = (),
) -> DeltaManifest:
    if len(immutable_parent_sha256) != 64 or any(c not in "0123456789abcdef" for c in immutable_parent_sha256.lower()):
        raise ThinWorkspaceError("IMMUTABLE_PARENT_SHA256_REQUIRED")
    files = []
    for raw in sorted(set(changed_paths)):
        rel = _safe_relative(raw)
        full = root / rel
        if not full.is_file():
            raise ThinWorkspaceError(f"DELTA_FILE_MISSING:{rel}")
        files.append(DeltaFile(rel, sha256_file(full), full.stat().st_size))
    deleted = tuple(sorted({_safe_relative(x) for x in deleted_paths}))
    if set(x.path for x in files) & set(deleted):
        raise ThinWorkspaceError("DELTA_PATH_CHANGED_AND_DELETED")
    return DeltaManifest(
        schema_version="GO_PARALLEL_WORKBENCH_DELTA_MANIFEST_1.0",
        candidate_id=candidate_id,
        directive_id=directive_id,
        builder_cell=builder_cell,
        immutable_parent_sha256=immutable_parent_sha256.lower(),
        changed_files=tuple(files),
        deleted_paths=deleted,
        candidate_manifest_ref=_safe_relative(candidate_manifest_ref),
        evidence_refs=tuple(evidence_refs),
    )


def write_thin_workspace(*, root: Path, output_dir: Path, manifest: DeltaManifest) -> Path:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    (output_dir / "delta").mkdir(parents=True)
    for item in manifest.changed_files:
        src = root / item.path
        dst = output_dir / "delta" / item.path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if sha256_file(dst) != item.sha256:
            raise ThinWorkspaceError(f"DELTA_COPY_HASH_MISMATCH:{item.path}")
    manifest_path = output_dir / "DELTA_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest_path


def verify_thin_workspace(output_dir: Path) -> tuple[bool, str]:
    manifest_path = output_dir / "DELTA_MANIFEST.json"
    if not manifest_path.is_file():
        return False, "DELTA_MANIFEST_MISSING"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "GO_PARALLEL_WORKBENCH_DELTA_MANIFEST_1.0":
        return False, "DELTA_SCHEMA_INVALID"
    parent_sha = str(data.get("immutable_parent_sha256", ""))
    if len(parent_sha) != 64:
        return False, "PARENT_SHA_INVALID"
    for item in data.get("changed_files", []):
        rel = _safe_relative(item["path"])
        file_path = output_dir / "delta" / rel
        if not file_path.is_file():
            return False, f"DELTA_FILE_MISSING:{rel}"
        if sha256_file(file_path) != item["sha256"]:
            return False, f"DELTA_FILE_HASH_MISMATCH:{rel}"
    return True, "THIN_WORKSPACE_VERIFIED"
