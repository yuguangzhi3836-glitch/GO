"""Command line entry point used by the two Lite V2 workflows.

Everything a workflow does to a candidate (freeze it, review it, seal it, verify
it, bind it to the existing ledger) goes through this file, so the logic lives in
reviewable Python instead of inside YAML.

Subcommands
-----------
``spec``          build one frozen candidate spec + contract from the dispatch env
``review``        run one fresh AI review execution (or the labelled local stub)
``seal``          seal a bundle from the contract, the review outcome and machine evidence
``verify``        verify a whole C13+C14 round and write the decision
``bind-ledger``   DRY RUN binding of two execution records onto the existing ledger

No subcommand contacts a server, a database or a deployment path.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lite_ai_reviewer  # noqa: E402
import lite_bundle  # noqa: E402
import lite_candidate  # noqa: E402
import lite_canonical  # noqa: E402
import lite_chain  # noqa: E402
import lite_errors  # noqa: E402
import lite_execution_record  # noqa: E402
import lite_ledger_binding  # noqa: E402

ENV_KEYS = {
    "candidate_sha": "LITE_CANDIDATE_SHA",
    "application_tree": "LITE_APPLICATION_TREE",
    "cell_pair": "LITE_CELL_PAIR",
    "request_id": "LITE_REQUEST_ID",
    "c14_task_id": "LITE_C14_TASK_ID",
    "c13_task_id": "LITE_C13_TASK_ID",
    "ledger_round_id": "LITE_LEDGER_ROUND_ID",
    "nonce": "LITE_NONCE",
    "workflow_identity": "LITE_WORKFLOW_IDENTITY",
    "workflow_sha": "LITE_WORKFLOW_SHA",
    "scope_sha256": "LITE_SCOPE_SHA256",
    "issued_at": "LITE_ISSUED_AT",
    "expires_at": "LITE_EXPIRES_AT",
    "run_id": "LITE_RUN_ID",
    "run_attempt": "LITE_RUN_ATTEMPT",
    "repository": "GITHUB_REPOSITORY",
}


def _read(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def _write(path, value):
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    pathlib.Path(path).write_text(text, encoding="utf-8")
    return path


def _env_spec(role: str) -> dict:
    missing = [name for name, var in ENV_KEYS.items() if var != "GITHUB_REPOSITORY" and not os.environ.get(var)]
    if missing:
        raise SystemExit(f"missing dispatch env: {sorted(missing)}")
    return {
        "role": role,
        "cell_id": "C14" if role == "c14" else "C13",
        "candidate_sha": os.environ["LITE_CANDIDATE_SHA"],
        "application_tree": os.environ["LITE_APPLICATION_TREE"],
        "cell_pair": os.environ["LITE_CELL_PAIR"],
        "issue_number": int(os.environ["LITE_ISSUE_NUMBER"]) if os.environ.get("LITE_ISSUE_NUMBER") else None,
        "request_id": os.environ["LITE_REQUEST_ID"],
        "c14_task_id": os.environ["LITE_C14_TASK_ID"],
        "c13_task_id": os.environ["LITE_C13_TASK_ID"],
        "ledger_round_id": os.environ["LITE_LEDGER_ROUND_ID"],
        "nonce": os.environ["LITE_NONCE"],
        "workflow_identity": os.environ["LITE_WORKFLOW_IDENTITY"],
        "workflow_sha": os.environ["LITE_WORKFLOW_SHA"],
        "scope_sha256": os.environ["LITE_SCOPE_SHA256"],
        "issued_at": os.environ["LITE_ISSUED_AT"],
        "expires_at": os.environ["LITE_EXPIRES_AT"],
        "run_id": int(os.environ["LITE_RUN_ID"]),
        "run_attempt": int(os.environ["LITE_RUN_ATTEMPT"]),
        "repository": os.environ.get("GITHUB_REPOSITORY") or "yuguangzhi3836-glitch/GO",
        # Optional, and deliberately not part of the "missing dispatch env" check:
        # an empty value must fall back to the default, not fail the step. A push
        # triggered run has no inputs at all, which is exactly how this was found.
        "principal_id": os.environ.get("LITE_PRINCIPAL_ID") or "github-actions",
        "ai_model": os.environ.get("LITE_AI_MODEL") or lite_ai_reviewer.DEFAULT_MODEL,
        # Optional machine-test facts. Without a separate frozen inventory the
        # manifest itself is the inventory, which keeps the two digests linked.
        "test_inventory_sha256": os.environ.get("LITE_TEST_INVENTORY_SHA256", ""),
        "runner": os.environ.get("LITE_RUNNER", "ubuntu-24.04"),
        "runner_os": os.environ.get("LITE_RUNNER_OS", "Linux"),
        "postgres_version": os.environ.get("LITE_POSTGRES_VERSION", "18.4"),
        "docker_used": os.environ.get("LITE_DOCKER_USED", "true").lower() == "true",
        # Supplied by the scheduler adapter once it is wired; until then the
        # independence check is honest about not knowing the implementation run.
        "implementation_execution_id": os.environ.get("LITE_IMPLEMENTATION_EXECUTION_ID", "unknown-implementation-execution"),
    }


def _facts(role: str, spec: dict, *, task_id: str) -> dict:
    facts = {
        "repository": spec["repository"],
        "candidate_sha": spec["candidate_sha"],
        "application_tree": spec["application_tree"],
        "cell_id": spec["cell_id"],
        "task_id": task_id,
        "issue_number": spec["issue_number"],
        "ledger_reference": {
            "round_id": spec["ledger_round_id"],
            "cell_id": spec["cell_id"],
            "task_id": task_id,
        },
    }
    if role == "c14":
        facts["rule_review_scope_sha256"] = spec["scope_sha256"]
        facts["applicable_rules"] = spec.get("applicable_rules", ["GO_CONSTITUTION", "PERMISSION_BOUNDARY", "AI_BEHAVIOUR_RULES"])
        facts["applicable_rule_versions"] = spec.get(
            "applicable_rule_versions",
            {name: spec.get("rule_version", "unversioned") for name in facts["applicable_rules"]},
        )
        facts["changed_paths"] = spec.get("changed_paths", [])
    else:
        facts["quality_test_scope_sha256"] = spec["scope_sha256"]
        facts["machine_evidence"] = spec.get("machine_evidence", {})
        facts["acceptance_criteria"] = spec.get("acceptance_criteria", [])
    return facts


def _task_id(role: str, spec: dict) -> str:
    return spec["c14_task_id"] if role == "c14" else spec["c13_task_id"]


def cmd_spec(args) -> int:
    spec = _env_spec(args.role)
    facts = _facts(args.role, spec, task_id=_task_id(args.role, spec))
    prompt = lite_ai_reviewer.build_prompt(args.role, facts)
    contract = lite_candidate.build(
        repository=spec["repository"],
        candidate_commit_sha=spec["candidate_sha"],
        application_tree=spec["application_tree"],
        cell_id=spec["cell_id"],
        task_id=_task_id(args.role, spec),
        request_id=spec["request_id"],
        nonce=spec["nonce"],
        issued_at=spec["issued_at"],
        expires_at=spec["expires_at"],
        workflow_identity=spec["workflow_identity"],
        workflow_sha=spec["workflow_sha"],
        review_scope_sha256=spec["scope_sha256"],
        prompt_sha256=lite_canonical.digest_bytes(prompt.encode("utf-8")),
        issue_number=spec["issue_number"],
        ledger_reference={"round_id": spec["ledger_round_id"], "cell_id": spec["cell_id"], "task_id": _task_id(args.role, spec)},
    )
    _write(args.spec, spec)
    _write(args.facts, facts)
    _write(args.contract, contract)
    print(json.dumps({"spec": args.spec, "facts": args.facts, "contract": args.contract, "cell_id": spec["cell_id"]}))
    return 0


def cmd_review(args) -> int:
    spec = _read(args.spec)
    facts = _read(args.facts)
    role = spec["role"]
    try:
        outcome = lite_ai_reviewer.run(
            role,
            facts,
            model=spec.get("ai_model", lite_ai_reviewer.DEFAULT_MODEL),
            api_key=os.environ.get("OPENAI_API_KEY"),
            stub=args.stub,
        )
    except lite_ai_reviewer.ReviewUnavailable as error:
        outcome = lite_ai_reviewer.blocked_outcome(role, facts, error.failure_class, error.detail)
        outcome["http_status"] = error.http_status
        _write(args.out, outcome)
        print(json.dumps({"verdict": outcome["verdict"], "failure_class": outcome["failure_class"]}))
        # A provider/quota failure is BLOCKED, not a crash and not a FAIL.
        return 0 if args.allow_blocked else 1
    _write(args.out, outcome)
    print(json.dumps({"verdict": outcome["verdict"], "ai_provider": outcome["ai_provider"]}))
    return 0


def _machine_job(spec: dict, artifacts: dict) -> dict:
    return {
        "runner": spec.get("runner", "ubuntu-24.04"),
        "runner_os": spec.get("runner_os", "Linux"),
        "postgres_version": spec.get("postgres_version", "18.4"),
        "docker_used": bool(spec.get("docker_used", True)),
        "test_inventory_sha256": spec.get("test_inventory_sha256") or lite_canonical.digest_bytes(artifacts["manifest"]),
        "junit_sha256": lite_canonical.digest_bytes(artifacts["junit"]),
        "stdout_sha256": lite_canonical.digest_bytes(artifacts["stdout"]),
        "manifest_sha256": lite_canonical.digest_bytes(artifacts["manifest"]),
    }


def cmd_seal(args) -> int:
    spec = _read(args.spec)
    contract = _read(args.contract)
    outcome = _read(args.outcome)
    role = spec["role"]
    cell_id = spec["cell_id"]
    fields = {
        "schema_version": lite_bundle.SCHEMA_VERSION_C14 if role == "c14" else lite_bundle.SCHEMA_VERSION_C13,
        "cell_id": cell_id,
        "task_id": contract["task_id"],
        "issue_number": contract["issue_number"],
        "ledger_reference": contract["ledger_reference"],
        "candidate_sha": contract["candidate_commit_sha"],
        "application_tree": contract["application_tree"],
        "nonce": contract["nonce"],
        "github_run_id": spec["run_id"],
        "github_run_attempt": spec["run_attempt"],
        "workflow_ref": f"{spec['repository']}/{spec['workflow_sha']}",
        "workflow_sha": spec["workflow_sha"],
        "ai_provider": outcome["ai_provider"],
        "ai_model": outcome["ai_model"] or "unavailable",
        "ai_execution_id": outcome["ai_execution_id"] or f"blocked-{spec['run_id']}-{spec['run_attempt']}",
        "principal_id": spec["principal_id"],
        "review_execution_id": outcome["ai_execution_id"] or f"blocked-{spec['run_id']}-{spec['run_attempt']}",
        "prompt_sha256": outcome["prompt_sha256"],
        "input_sha256": outcome["input_sha256"],
        "opinion_sha256": outcome["opinion_sha256"] or lite_canonical.digest({"blocked": outcome["failure_class"]}),
        "verdict": outcome["verdict"],
        "failure_class": outcome["failure_class"],
        "issued_at": spec["issued_at"],
        "authorizes_any_action": False,
    }
    if role == "c14":
        opinion = outcome.get("opinion") or {}
        fields.update({
            "rule_review_scope_sha256": contract["review_scope_sha256"],
            "applicable_rules": opinion.get("applicable_rules") or spec.get("applicable_rules", ["GO_CONSTITUTION"]),
            "applicable_rule_versions": spec.get("applicable_rule_versions", {}),
            "not_applicable": (opinion or {}).get("not_applicable"),
            "findings": (opinion or {}).get("findings", []),
            "blocking_issues": (opinion or {}).get("blocking_issues", []),
            "remediation_status": (opinion or {}).get("remediation_status", "OPEN"),
        })
        if not fields["applicable_rule_versions"]:
            fields["applicable_rule_versions"] = {name: spec.get("rule_version", "unversioned") for name in fields["applicable_rules"]}
    else:
        artifacts = {
            "junit": pathlib.Path(args.junit).read_bytes(),
            "stdout": pathlib.Path(args.stdout).read_bytes(),
            "manifest": pathlib.Path(args.manifest).read_bytes(),
        }
        machine = _machine_job(spec, artifacts)
        prerequisite = _read(args.prereq)
        fields.update({
            "quality_test_scope_sha256": contract["review_scope_sha256"],
            "c14_prerequisite": {
                "c14_root": prerequisite[lite_bundle.C14_ROOT_FIELD],
                "c14_verdict": prerequisite["verdict"],
                "c14_candidate_sha": prerequisite["candidate_sha"],
                "c14_rule_scope_sha256": prerequisite["rule_review_scope_sha256"],
                "c14_remediation_closed": prerequisite["remediation_status"] in ("CLOSED", "NOT_REQUIRED"),
            },
            "machine_job": machine,
            "junit_sha256": machine["junit_sha256"],
            "stdout_sha256": machine["stdout_sha256"],
            "manifest_sha256": machine["manifest_sha256"],
            "quality_findings": (outcome.get("opinion") or {}).get("quality_findings", []),
            "remaining_risks": (outcome.get("opinion") or {}).get("remaining_risks", []),
        })
    lite_bundle.seal(fields)
    _write(args.out, fields)
    root_field = lite_bundle.C14_ROOT_FIELD if role == "c14" else lite_bundle.C13_ROOT_FIELD
    print(json.dumps({"bundle": args.out, root_field: fields[root_field], "verdict": fields["verdict"]}))
    return 0


def cmd_scope(args) -> int:
    """Freeze the review scope: the digest C13/C14 must both bind to."""
    changed = []
    if args.changed_paths:
        changed = sorted(line.strip() for line in pathlib.Path(args.changed_paths).read_text(encoding="utf-8").splitlines() if line.strip())
    rules = sorted(name for value in (args.rule or []) for name in value.split(",") if name.strip())
    payload = {
        "role": args.role,
        "rules": rules,
        "rule_version": args.rule_version,
        "changed_paths": changed,
        "test_inventory": sorted(line.strip() for line in pathlib.Path(args.inventory).read_text(encoding="utf-8").splitlines() if line.strip()) if args.inventory else [],
        "acceptance_criteria": args.criterion or [],
    }
    digest = lite_canonical.digest(payload)
    _write(args.out, {"scope": payload, "scope_sha256": digest})
    print(json.dumps({"scope_sha256": digest, "rules": rules, "changed_paths": len(changed)}))
    return 0


def cmd_verify(args) -> int:
    spec = _read(args.spec)
    dispatch = {
        "candidate_sha": spec["candidate_sha"],
        "application_tree": spec["application_tree"],
        "cell_pair": spec["cell_pair"],
        "issue_number": spec["issue_number"],
        "request_id": spec["request_id"],
        "c14_task_id": spec["c14_task_id"],
        "c13_task_id": spec["c13_task_id"],
        "c14_ledger_reference": {"round_id": spec["ledger_round_id"], "cell_id": "C14", "task_id": spec["c14_task_id"]},
        "c13_ledger_reference": {"round_id": spec["ledger_round_id"], "cell_id": "C13", "task_id": spec["c13_task_id"]},
    }
    artifacts = {}
    for name, path in (("c14_opinion", args.c14_opinion), ("c13_opinion", args.c13_opinion),
                       ("junit", args.junit), ("stdout", args.stdout), ("manifest", args.manifest)):
        if path:
            artifacts[name] = pathlib.Path(path).read_bytes()
    decision = lite_chain.verify_round(
        c14_bundle=_read(args.c14_bundle),
        c13_bundle=_read(args.c13_bundle),
        c14_contract=_read(args.c14_contract),
        c13_contract=_read(args.c13_contract),
        dispatch=dispatch,
        implementation_execution_id=spec["implementation_execution_id"],
        artifacts=artifacts,
        now=None,
    )
    payload = decision.as_dict()
    _write(args.out, payload)
    print(json.dumps({"decision": payload["decision"], "reasons": decision.reasons, "eligibility": payload["eligibility"]}))
    if decision.ok or args.allow_incomplete:
        return 0
    return 1


def cmd_bind_ledger(args) -> int:
    spec = _read(args.spec)
    ledger = _read(args.ledger)
    c14_bundle = _read(args.c14_bundle)
    c13_bundle = _read(args.c13_bundle)
    evidence_root = pathlib.Path(args.evidence_root)
    c14_record = lite_execution_record.build(
        c14_bundle,
        artifact={"name": args.c14_artifact_name, "id": args.c14_artifact_id, "digest": args.c14_artifact_digest},
        evidence_path=args.c14_bundle,
    )
    c13_record = lite_execution_record.build(
        c13_bundle,
        artifact={"name": args.c13_artifact_name, "id": args.c13_artifact_id, "digest": args.c13_artifact_digest},
        evidence_path=args.c13_bundle,
    )
    machine_files = [pathlib.Path(p) for p in (args.junit, args.stdout, args.manifest)]
    bound = lite_ledger_binding.bind(
        ledger,
        evidence_root=evidence_root,
        candidate_sha=spec["candidate_sha"],
        c14_record=c14_record,
        c13_record=c13_record,
        c14_evidence=[(args.c14_bundle, pathlib.Path(args.c14_bundle).read_bytes())],
        c13_evidence=[(args.c13_bundle, pathlib.Path(args.c13_bundle).read_bytes())],
        machine_evidence=[(_relpath(p, evidence_root), p.read_bytes()) for p in machine_files],
        completed_at=args.completed_at,
        mark_tasks_done=not args.keep_assigned,
    )
    report = lite_ledger_binding.validate_with_repository_validator(bound, evidence_root)
    _write(args.out_bound, bound)
    _write(args.out_report, report)
    print(json.dumps({"ledger_gate": report["gate"], "errors": report["errors"]}))
    return 0 if report["gate"] == "PASS_SCOPED" else 1


def _relpath(path, root):
    try:
        return pathlib.Path(path).resolve().relative_to(pathlib.Path(root).resolve()).as_posix()
    except ValueError as error:
        raise lite_errors.Reject("evidence_outside_root", str(path)) from error


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    spec = sub.add_parser("spec")
    spec.add_argument("--role", required=True, choices=("c13", "c14"))
    spec.add_argument("--spec", required=True)
    spec.add_argument("--facts", required=True)
    spec.add_argument("--contract", required=True)
    spec.set_defaults(func=cmd_spec)

    scope = sub.add_parser("scope")
    scope.add_argument("--role", required=True, choices=("c13", "c14"))
    scope.add_argument("--rule", action="append", help="repeatable; comma separated rule names")
    scope.add_argument("--rule-version", default="unversioned")
    scope.add_argument("--changed-paths", help="file with one repository path per line")
    scope.add_argument("--inventory", help="file with one test-inventory entry per line")
    scope.add_argument("--criterion", action="append", help="repeatable acceptance criterion")
    scope.add_argument("--out", required=True)
    scope.set_defaults(func=cmd_scope)

    review = sub.add_parser("review")
    review.add_argument("--spec", required=True)
    review.add_argument("--facts", required=True)
    review.add_argument("--out", required=True)
    review.add_argument("--stub", action="store_true")
    review.add_argument("--allow-blocked", action="store_true")
    review.set_defaults(func=cmd_review)

    seal = sub.add_parser("seal")
    seal.add_argument("--spec", required=True)
    seal.add_argument("--contract", required=True)
    seal.add_argument("--outcome", required=True)
    seal.add_argument("--out", required=True)
    seal.add_argument("--prereq")
    seal.add_argument("--junit")
    seal.add_argument("--stdout")
    seal.add_argument("--manifest")
    seal.set_defaults(func=cmd_seal)

    verify = sub.add_parser("verify")
    verify.add_argument("--spec", required=True)
    verify.add_argument("--c14-bundle", required=True)
    verify.add_argument("--c13-bundle", required=True)
    verify.add_argument("--c14-contract", required=True)
    verify.add_argument("--c13-contract", required=True)
    verify.add_argument("--c14-opinion")
    verify.add_argument("--c13-opinion")
    verify.add_argument("--junit")
    verify.add_argument("--stdout")
    verify.add_argument("--manifest")
    verify.add_argument("--out", required=True)
    verify.add_argument("--allow-incomplete", action="store_true",
                        help="write the decision and exit 0 even when it is not ACCEPT (the decision file still carries the truth)")
    verify.set_defaults(func=cmd_verify)

    bind = sub.add_parser("bind-ledger")
    bind.add_argument("--spec", required=True)
    bind.add_argument("--ledger", required=True)
    bind.add_argument("--evidence-root", required=True)
    bind.add_argument("--c14-bundle", required=True)
    bind.add_argument("--c13-bundle", required=True)
    bind.add_argument("--junit", required=True)
    bind.add_argument("--stdout", required=True)
    bind.add_argument("--manifest", required=True)
    bind.add_argument("--completed-at", required=True)
    bind.add_argument("--c14-artifact-name", required=True)
    bind.add_argument("--c14-artifact-id", type=int, required=True)
    bind.add_argument("--c14-artifact-digest", required=True)
    bind.add_argument("--c13-artifact-name", required=True)
    bind.add_argument("--c13-artifact-id", type=int, required=True)
    bind.add_argument("--c13-artifact-digest", required=True)
    bind.add_argument("--out-bound", required=True)
    bind.add_argument("--out-report", required=True)
    bind.add_argument("--keep-assigned", action="store_true")
    bind.set_defaults(func=cmd_bind_ledger)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (lite_errors.Reject, lite_errors.Block) as error:
        print(json.dumps({"refused": error.reason, "detail": getattr(error, "detail", "")}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
