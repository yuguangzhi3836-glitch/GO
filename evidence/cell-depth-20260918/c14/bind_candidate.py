"""Read-only source/evidence binding for an explicitly frozen local candidate."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

repo = Path(sys.argv[1]).resolve()
expected = sys.argv[2]
output = Path(__file__).resolve().parent


def git(*args):
    return subprocess.check_output(["git", *args], cwd=repo)


head = git("rev-parse", "HEAD").decode().strip()
if head != expected:
    raise SystemExit("Candidate HEAD moved")
entries = []
for item in git("ls-tree", "-r", "-z", "--full-tree", head, "--", "application").split(b"\0"):
    if not item:
        continue
    meta, raw_path = item.split(b"\t", 1)
    mode, kind, blob = meta.decode().split()
    if kind != "blob":
        raise SystemExit("Non-blob application entry")
    entries.append((raw_path.decode(), mode, blob))
entries.sort(key=lambda item: item[0].encode("utf-8"))
manifest, fingerprint, mismatches = [], hashlib.sha256(), []
for path, mode, blob in entries:
    content = git("cat-file", "blob", blob)
    sha = hashlib.sha256(content).hexdigest()
    fingerprint.update(path.encode("utf-8") + b"\0" + sha.encode("ascii") + b"\n")
    target = repo / path
    actual = os.readlink(target).encode() if mode == "120000" else target.read_bytes()
    if content != actual:
        mismatches.append(path)
    manifest.append({"path": path, "mode": mode, "git_blob": blob, "sha256": sha, "bytes": len(content)})

evidence = []
checks = []
evidence_root = repo / "evidence/cell-depth-20260918"
for path in sorted(evidence_root.rglob("*")):
    if path.is_file():
        evidence.append({"path": str(path.relative_to(repo)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size})
for checksum in sorted(evidence_root.rglob("SHA256SUMS.json")):
    failures = []
    values = json.loads(checksum.read_text())
    for name, wanted in values.items():
        target = checksum.parent / name
        actual = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None
        if wanted != actual:
            failures.append({"path": name, "expected": wanted, "actual": actual})
    checks.append({"manifest": str(checksum.relative_to(repo)), "files_checked": len(values), "mismatches": failures})

dirty = git("diff", "--name-only", head, "--", "application").decode().splitlines()
untracked = git("ls-files", "--others", "--exclude-standard", "--", "application").decode().splitlines()
non_generated = [path for path in untracked if "/__pycache__/" not in path and "/.pytest_cache/" not in path and "/var/media_cache/" not in path]
changed = git("diff", "--name-status", "617823b", head, "--", "application").decode().splitlines()
binding = {
    "candidate_sha": head,
    "application_git_tree": git("rev-parse", head + ":application").decode().strip(),
    "application_files": len(entries),
    "application_source_sha256": fingerprint.hexdigest(),
    "fingerprint_algorithm": "SHA256 of UTF-8-byte-sorted tracked application paths, each encoded as path (including application/ prefix) + NUL + file-content SHA256 lowercase hex + LF",
    "working_tree_content_mismatches": mismatches,
    "tracked_application_dirty": dirty,
    "untracked_non_generated_application_files": non_generated,
    "changed_application_files_from_local_base": changed,
    "evidence_checksum_manifests": checks,
    "evidence_files": len(evidence),
}
if git("rev-parse", "HEAD").decode().strip() != head:
    raise SystemExit("Candidate HEAD moved during binding")
for name, value in (("APPLICATION_MANIFEST.json", manifest), ("EVIDENCE_MANIFEST.json", evidence), ("SOURCE_BINDING.json", binding)):
    (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(binding, ensure_ascii=False, indent=2))
if mismatches or dirty or non_generated or any(item["mismatches"] for item in checks):
    raise SystemExit("Source or evidence mismatch")
