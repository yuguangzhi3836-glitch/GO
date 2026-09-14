"""Read-only C14 exact candidate identity check; writes only this review's output."""
from pathlib import Path
import hashlib
import json
from datetime import datetime, timezone
import sys


def git_hash(kind, data):
    return hashlib.sha1(kind.encode() + b" " + str(len(data)).encode() + b"\0" + data).hexdigest()


def tree_hash(node):
    entries = []
    for name, value in node.items():
        if isinstance(value, dict):
            mode, digest, key = "40000", tree_hash(value), name.encode() + b"/"
        else:
            mode, digest = value
            key = name.encode()
        entries.append((key, mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(digest)))
    return git_hash("tree", b"".join(row[1] for row in sorted(entries)))


def main():
    root = Path(__file__).resolve().parents[3]
    manifest = root / (sys.argv[1] if len(sys.argv) > 1 else "evidence/v70-next-depth-20260914/CANDIDATE_SOURCE.json")
    result_path = Path(__file__).with_name("fixed-candidate-verification.json")
    candidate = json.loads(manifest.read_text())
    parent = json.loads((root / "evidence/v70-round2-20260914/CANDIDATE_SOURCE.json").read_text())
    errors, observations, tree = [], [], {}
    source_lines = []
    changes = {"unchanged": [], "modified": [], "added": [], "deleted": []}
    for key, expected in [("source_anchor", "fef9c748adb77d37ba5d4dc4fa4662eb668303a1"),
                          ("parent_candidate_commit", "a274f77e4c1479fb143cdc7ef45d63b9c4f8cc1b")]:
        if candidate.get(key) != expected:
            errors.append(key + " identity mismatch")
    for name, data in sorted(candidate["files"].items()):
        rel = Path(name)
        path = root / rel
        if rel.is_absolute() or ".." in rel.parts or not name.startswith("application/"):
            errors.append("invalid candidate path: " + name)
            continue
        if not path.is_file() or path.is_symlink():
            errors.append("missing/nonregular candidate file: " + name)
            continue
        content = path.read_bytes()
        actual = {"sha": git_hash("blob", content), "sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}
        okay = all(data.get(key) == value for key, value in actual.items())
        if not okay:
            errors.append("blob/sha256/size mismatch: " + name)
        observations.append({"path": name, "expected": data, "actual": actual, "match": okay})
        app_rel = name.removeprefix("application/")
        source_lines.append(app_rel + "\0" + actual["sha256"] + "\n")
        node = tree
        pieces = app_rel.split("/")
        for part in pieces[:-1]:
            node = node.setdefault(part, {})
        node[pieces[-1]] = (data["mode"], actual["sha"])
        original = parent["files"].get(name)
        label = "added" if original is None else ("unchanged" if actual["sha"] == original["sha"] and data["mode"] == original["mode"] else "modified")
        changes[label].append(name)
    changes["deleted"] = sorted(set(parent["files"]) - set(candidate["files"]))
    actual_paths = {str(p.relative_to(root)) for p in (root / "application").rglob("*") if p.is_file() or p.is_symlink()}
    extras = sorted(actual_paths - set(candidate["files"]))
    if extras:
        errors.append("application has undeclared files")
    if any(name.startswith("application/application/") for name in actual_paths):
        errors.append("nested accidental application tree")
    actual_tree = tree_hash(tree)
    actual_source_hash = hashlib.sha256("".join(source_lines).encode()).hexdigest()
    if actual_tree != candidate["application_git_tree"]:
        errors.append("application Git tree mismatch")
    if actual_source_hash != candidate["source_tree_sha256"]:
        errors.append("source tree SHA256 mismatch")
    if candidate.get("source_files") != len(observations):
        errors.append("source file count mismatch")
    result = {"reviewer": "/root/c14_review", "observed_at": datetime.now(timezone.utc).isoformat(),
        "result": "MATCH" if not errors else "MISMATCH", "source_anchor": candidate.get("source_anchor"),
        "parent_candidate_commit": candidate.get("parent_candidate_commit"),
        "candidate_manifest": {"path": str(manifest.relative_to(root)), "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()},
        "application_git_tree": actual_tree, "source_tree_sha256": actual_source_hash,
        "source_files": len(observations), "change_counts": {key: len(value) for key, value in changes.items()},
        "changes": changes, "undeclared_files": extras, "errors": errors, "observations": observations,
        "scope": "Independent byte/blob/tree identity check only; not C14 or C13 acceptance by itself"}
    result_path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("result", "application_git_tree", "source_tree_sha256", "source_files", "change_counts", "errors")}, indent=2))
    return int(bool(errors))


if __name__ == "__main__":
    sys.exit(main())
