"""Verify predecessor retention and explicit job outcomes; seal exact-head evidence."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main():
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    binding = json.loads((ROOT / "ci/supplier-controls/CANDIDATE.json").read_text())
    base = binding["base_candidate_sha"]
    head = git("rev-parse", "HEAD")
    assert head == os.environ["CANDIDATE_SHA"], "candidate mismatch"
    subprocess.run(["git", "merge-base", "--is-ancestor", base, head], cwd=ROOT, check=True)
    assert git("rev-parse", base + ":application") == binding["base_application_tree"]
    changed = git("diff", "--name-only", base, head).splitlines()
    assert set(changed) <= set(binding["allowed_changed_files"]), "unscoped change"
    assert "application/src/go_hotel/connectors/supplier_runtime_controls.py" in changed
    fingerprint = {}
    for path in git("ls-files", "application").splitlines():
        target = ROOT / path
        assert not target.is_symlink(), path
        fingerprint[path[len("application/"):]] = hashlib.sha256(target.read_bytes()).hexdigest()
    fingerprint_sha = hashlib.sha256(
        "".join(f"{path}\0{digest}\n" for path, digest in sorted(fingerprint.items())).encode()
    ).hexdigest()
    (out / "SOURCE_FINGERPRINT.json").write_text(json.dumps(fingerprint, sort_keys=True, indent=2) + "\n")
    tests = {}
    for name in ("sqlite", "postgres"):
        xml = out / (name + ".xml")
        count = 0
        failures = 0
        if xml.exists():
            cases = ET.parse(xml).findall(".//testcase")
            count = len(cases)
            failures = sum(bool(list(case)) and any(
                item.tag in {"failure", "error", "skipped"} for item in case
            ) for case in cases)
        outcome = os.environ.get(name.upper() + "_OUTCOME")
        tests[name] = {"cases": count, "failed_or_skipped": failures, "step_outcome": outcome,
                       "status": "PASS" if outcome == "success" and count > 0 and not failures else "FAIL"}
    runtime = out / "runtime.log"
    final_marker = "R8.2_RC14_2_EXTERNAL_SANDBOX_EXECUTOR_GATE: PASS"
    runtime_ok = (os.environ.get("RUNTIME_OUTCOME") == "success" and runtime.exists()
                  and runtime.read_text().strip().splitlines()[-1] == final_marker)
    result = {
        "schema": "go.supplier-controls.evidence.v1", "candidate_sha": head,
        "base_candidate_sha": base, "application_tree": git("rev-parse", "HEAD:application"),
        "source_fingerprint_sha256": fingerprint_sha, "source_files": len(fingerprint),
        "changed_files": changed, "unchanged_predecessor_bytes": "PASS",
        "tests": tests, "runtime_gate": "PASS" if runtime_ok else "FAIL",
        "status": "PASS" if runtime_ok and all(t["status"] == "PASS" for t in tests.values()) else "FAIL",
        "scope": binding["scope"], "external_supplier": "HOLD", "hk_staging": "HOLD",
        "final_release": "HOLD", "production": "HOLD", "merge": "NOT_RUN", "deployment": "NOT_RUN",
        "inherited_cell_tests": "NOT_RERUN",
    }
    (out / "EVIDENCE.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    checksums = []
    for path in sorted(out.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            checksums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(out)}\n")
    (out / "SHA256SUMS").write_text("".join(checksums))
    print(json.dumps(result, sort_keys=True))
    print("EVIDENCE_SHA256=" + hashlib.sha256((out / "EVIDENCE.json").read_bytes()).hexdigest())
    if result["status"] != "PASS":
        raise SystemExit("supplier controls gate failed")


if __name__ == "__main__":
    main()

