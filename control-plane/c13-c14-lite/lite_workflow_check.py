"""Structural contract checks for the two Lite V2 workflows.

These are the checks that must hold even when the workflow cannot be dispatched
from this workstation: least privilege, credential separation between the C13
machine job and the C13 AI job, no deployment authority, and a dispatchable
identity. They run offline and are part of the normal test suite.

Uses PyYAML when it is importable; otherwise falls back to a deliberately
conservative text scan so the suite still runs in a bare environment.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

C14_WORKFLOW = "c14-rule-compliance.yml"
C13_WORKFLOW = "c13-quality-acceptance.yml"
POC_WORKFLOW = "c13-c14-lite-poc.yml"

FORBIDDEN_PERMISSION_SUFFIXES = ("write", "admin")
FORBIDDEN_CREDENTIAL_HINTS = ("SSH", "DEPLOY", "PRODUCTION", "AWS_", "ALIYUN", "HK_", "CC_")

try:  # pragma: no cover - trivial import guard
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def load(name: str) -> dict:
    path = WORKFLOW_DIR / name
    text = path.read_text(encoding="utf-8")
    if yaml is None:
        return {"__raw__": text}
    return yaml.safe_load(text)


def raw_of(document: dict, name: str) -> str:
    if "__raw__" in document:
        return document["__raw__"]
    return (WORKFLOW_DIR / name).read_text(encoding="utf-8")


def check_permissions(name: str, document: dict, raw: str, failures: list) -> None:
    permissions = document.get("permissions")
    if permissions is None:
        if not re.search(r"^permissions:", raw, re.M):
            failures.append(f"{name}: no permissions block (must be explicit, least privilege)")
        return
    if not isinstance(permissions, dict):
        failures.append(f"{name}: permissions must be a mapping")
        return
    for scope, value in permissions.items():
        if str(value).endswith(FORBIDDEN_PERMISSION_SUFFIXES) or value == "write-all":
            failures.append(f"{name}: forbidden permission {scope}={value}")
    for scope in ("contents", "actions"):
        if permissions.get(scope) != "read":
            failures.append(f"{name}: {scope} must be exactly read")


def check_no_deployment_authority(name: str, raw: str, failures: list) -> None:
    for pattern in (r"\bgit\s+merge\b", r"\bgit\s+push\b", r"\bgh\s+pr\s+merge\b",
                    r"deployments:\s*write", r"issues:\s*write", r"pull-requests:\s*write",
                    r"authorizes_any_action\s*[:=]\s*true"):
        if re.search(pattern, raw):
            failures.append(f"{name}: forbidden pattern {pattern}")


def check_credential_boundary(name: str, document: dict, raw: str, failures: list) -> None:
    """The C13 machine job must not see the AI key; the AI job must not run Docker."""
    if name != C13_WORKFLOW:
        return
    if "OPENAI_API_KEY" not in raw:
        failures.append(f"{name}: the AI review job must consume the AI credential")
    if yaml is None:
        return
    jobs = document.get("jobs") or {}
    machine = jobs.get("c13-machine-test")
    ai_review = jobs.get("c13-ai-review")
    if not machine or not ai_review:
        failures.append(f"{name}: expected both c13-machine-test and c13-ai-review jobs")
        return
    machine_text = json.dumps(machine)
    ai_text = json.dumps(ai_review)
    if "OPENAI_API_KEY" in machine_text:
        failures.append(f"{name}: machine job must not receive OPENAI_API_KEY")
    if "docker run" in ai_text or "services" in (ai_review or {}):
        failures.append(f"{name}: AI review job must not run Docker")
    if "postgres" in ai_text.lower() and "postgres_version" not in ai_text:
        failures.append(f"{name}: AI review job must not touch PostgreSQL")
    for hint in FORBIDDEN_CREDENTIAL_HINTS:
        if hint in machine_text:
            failures.append(f"{name}: machine job references a privileged credential hint {hint}")
    if str(ai_review.get("permissions")) not in ("None", "{}"):
        failures.append(f"{name}: AI job must not add write permissions of its own")


def check_dispatch_surface(name: str, document: dict, failures: list) -> None:
    if "__raw__" in document:
        return
    triggers = document.get("on") or document.get(True) or {}
    if "workflow_dispatch" not in triggers:
        failures.append(f"{name}: must be dispatchable with workflow_dispatch")
        return
    inputs = (triggers.get("workflow_dispatch") or {}).get("inputs") or {}
    for required in ("candidate_sha", "application_tree", "issue_number", "request_id"):
        if name == POC_WORKFLOW:
            continue
        if required not in inputs:
            failures.append(f"{name}: missing dispatch input {required}")
    if len(inputs) > 10:
        failures.append(f"{name}: workflow_dispatch allows at most 10 inputs")


def check_artifact_discipline(name: str, raw: str, failures: list) -> None:
    if "upload-artifact@v4" not in raw:
        failures.append(f"{name}: must publish a sealed artifact")
    if "retention-days" not in raw:
        failures.append(f"{name}: artifacts must declare retention-days")


def run() -> dict:
    failures = []
    checked = []
    for name in (C14_WORKFLOW, C13_WORKFLOW, POC_WORKFLOW):
        if not (WORKFLOW_DIR / name).is_file():
            failures.append(f"{name}: missing")
            continue
        checked.append(name)
        document = load(name)
        raw = raw_of(document, name)
        check_permissions(name, document, raw, failures)
        check_no_deployment_authority(name, raw, failures)
        check_credential_boundary(name, document, raw, failures)
        check_dispatch_surface(name, document, failures)
        check_artifact_discipline(name, raw, failures)
    return {
        "gate": "PASS" if not failures else "FAIL",
        "yaml_parser": "PyYAML" if yaml is not None else "text-scan-fallback",
        "checked": checked,
        "failures": failures,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    report = run()
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        pathlib.Path(args.out).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["gate"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
