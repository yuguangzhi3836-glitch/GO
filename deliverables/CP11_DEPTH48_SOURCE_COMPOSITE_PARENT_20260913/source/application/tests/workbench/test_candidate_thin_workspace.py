from pathlib import Path
import json
import pytest

from go_hotel.workbench.thin_workspace import (
    ThinWorkspaceError,
    build_delta_manifest,
    write_thin_workspace,
    verify_thin_workspace,
)

PARENT = "a" * 64


def test_thin_workspace_copies_only_changed_files(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src/a.py").write_text("x=1\n")
    (root / "unchanged.bin").write_bytes(b"x" * 1024 * 1024)
    m = build_delta_manifest(
        root=root,
        candidate_id="CAND-1",
        directive_id="D-1",
        builder_cell="C11",
        immutable_parent_sha256=PARENT,
        changed_paths=("src/a.py",),
        candidate_manifest_ref="governance/candidate.json",
    )
    out = tmp_path / "thin"
    write_thin_workspace(root=root, output_dir=out, manifest=m)
    assert (out / "delta/src/a.py").is_file()
    assert not (out / "delta/unchanged.bin").exists()
    assert verify_thin_workspace(out) == (True, "THIN_WORKSPACE_VERIFIED")


def test_parent_sha_is_mandatory_and_immutable_shape(tmp_path: Path):
    root = tmp_path / "root"; root.mkdir(); (root / "a").write_text("x")
    with pytest.raises(ThinWorkspaceError, match="IMMUTABLE_PARENT_SHA256_REQUIRED"):
        build_delta_manifest(root=root,candidate_id="c",directive_id="d",builder_cell="C01",immutable_parent_sha256="bad",changed_paths=("a",),candidate_manifest_ref="m.json")


def test_unsafe_delta_path_fails_closed(tmp_path: Path):
    root = tmp_path / "root"; root.mkdir()
    with pytest.raises(ThinWorkspaceError, match="UNSAFE_DELTA_PATH"):
        build_delta_manifest(root=root,candidate_id="c",directive_id="d",builder_cell="C01",immutable_parent_sha256=PARENT,changed_paths=("../escape",),candidate_manifest_ref="m.json")


def test_manifest_records_hash_and_delete_set(tmp_path: Path):
    root = tmp_path / "root"; root.mkdir(); (root / "a").write_text("hello")
    m = build_delta_manifest(root=root,candidate_id="c",directive_id="d",builder_cell="C01",immutable_parent_sha256=PARENT,changed_paths=("a",),deleted_paths=("old.txt",),candidate_manifest_ref="m.json")
    out = tmp_path / "thin"; write_thin_workspace(root=root, output_dir=out, manifest=m)
    data=json.loads((out/"DELTA_MANIFEST.json").read_text())
    assert data["immutable_parent_sha256"] == PARENT
    assert data["deleted_paths"] == ["old.txt"]
    assert len(data["changed_files"][0]["sha256"]) == 64
