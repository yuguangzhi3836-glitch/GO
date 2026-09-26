"""Synthetic fixtures for the C13/C14 Lite V2 tests.

Everything here is *synthetic*: the candidate SHAs, the issue number, the run ids
and the AI opinions are derived from literal seeds. No fixture reads a live host,
a real Task, a real Evidence record or a historical PR number, and no fixture
candidate is presented as a real product candidate.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import datetime, timedelta, timezone

import lite_ai_reviewer
import lite_bundle
import lite_candidate
import lite_canonical
import lite_errors
import lite_review_brief
import lite_rule_input

#: A fixed instant, for tests that need one. It is **not** the default for the
#: builders below: a frozen default silently turns every fixture into a time bomb —
#: contracts carry ``expires_at``, so once wall-clock passes ``NOW + 55min`` every
#: test that builds a fixture starts failing with ``candidate_request_expired``.
#: That is exactly what happened to this suite on 2026-09-25, which is why the
#: builders now resolve their ``now`` at call time.
NOW = datetime(2026, 9, 25, 8, 0, 0, tzinfo=timezone.utc)


def fresh_now() -> datetime:
    """Call-time UTC, second precision. Fixtures never rot while the suite runs."""
    return datetime.now(timezone.utc).replace(microsecond=0)


ROUND_ID = "SYNTHETIC-LITE-V2-ROUND"
ISSUE_NUMBER = 4242
REPOSITORY = "yuguangzhi3836-glitch/GO"

C14_TASK = "C14-synthetic-rule-review-1"
C13_TASK = "C13-synthetic-quality-acceptance-1"
REQUEST_ID = "request-lite-round-0001"
C14_WORKFLOW = ".github/workflows/c14-rule-compliance.yml"
C13_WORKFLOW = ".github/workflows/c13-quality-acceptance.yml"


def seed_sha(seed: str, length: int = 40) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:length]


CANDIDATE_SHA = seed_sha("synthetic-candidate-commit")
OTHER_CANDIDATE_SHA = seed_sha("synthetic-other-candidate-commit")
APPLICATION_TREE = seed_sha("synthetic-application-tree")
C14_WORKFLOW_SHA = seed_sha("synthetic-c14-workflow")
C13_WORKFLOW_SHA = seed_sha("synthetic-c13-workflow")

RULE_SCOPE = seed_sha("synthetic-rule-review-scope", 64)
QUALITY_SCOPE = seed_sha("synthetic-quality-test-scope", 64)

#: The synthetic authoritative rule source. The path is a real repository path so the
#: shape matches production, but the bytes are synthetic and nothing here is presented as
#: an authority: this is the *shape* of a resolved rule input and nothing more.
RULE_SOURCE_PATH = "docs/governance/CHANGE_CONTROL_POLICY.md"
RULE_SOURCE_TEXT = "Synthetic governance rule text for the fixture round.\n"
AUTHORITY_COMMIT = seed_sha("synthetic-authority-commit")

#: The synthetic review brief: the task the fixture candidate was answering. Values are derived
#: from seeds and this is presented as the *shape* of a resolved brief, never as a real task and
#: never as a real pull request.
REVIEW_BRIEF_PR_NUMBER = 1717
REVIEW_BRIEF_TITLE = "Synthetic candidate task for the fixture round"
REVIEW_BRIEF_BODY = "Synthetic task body: this candidate answers the fixture brief.\n"


def pull_request(candidate_sha=CANDIDATE_SHA, *, number=REVIEW_BRIEF_PR_NUMBER, as_merge=False) -> dict:
    """One GitHub-shaped pull request, for exercising the brief resolver offline.

    ``as_merge=True`` models the other legal candidate shape: the frozen candidate is the
    *merge commit* of an already merged pull request, so its head SHA is a different commit.
    """
    return {
        "number": number,
        "title": REVIEW_BRIEF_TITLE,
        "body": REVIEW_BRIEF_BODY,
        "state": "closed",
        "merged_at": "2026-09-25T08:00:00Z",
        "merge_commit_sha": candidate_sha if as_merge else seed_sha(f"synthetic-merge-{number}"),
        "html_url": f"https://github.com/{REPOSITORY}/pull/{number}",
        "base": {"ref": "main"},
        "head": {
            "ref": f"synthetic/head-{number}",
            "sha": seed_sha(f"synthetic-head-{number}") if as_merge else candidate_sha,
        },
    }


def review_brief_record(candidate_sha=CANDIDATE_SHA, *, as_merge=False) -> dict:
    """A brief record produced by the production resolver, so the fixture is consistent.

    Hand-writing the record would let a fixture disagree with the real matching rule.
    """
    return lite_review_brief.resolve(
        candidate_sha, lambda sha: [pull_request(sha, as_merge=as_merge)])


def write_review_brief(path, candidate_sha=CANDIDATE_SHA, *, as_merge=False):
    """Write a resolved brief to disk, for the ``spec`` CLI to consume."""
    target = pathlib.Path(path)
    target.write_text(
        json.dumps(review_brief_record(candidate_sha, as_merge=as_merge), indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return target


def rule_input_record(*, status="OK", reason=None, detail="") -> dict:
    """One resolved rule input in the production shape, for fixtures and tests.

    The digest is computed the same way the resolver computes it, so a fixture record is
    internally consistent rather than a hand-written approximation of one.
    """
    reason = reason or lite_rule_input.SOURCE_PATH_MISSING
    record = {
        "status": status,
        "reason": None if status == "OK" else reason,
        "detail": detail,
        "authority_ref": lite_rule_input.DEFAULT_AUTHORITY_REF,
        "authority_commit": AUTHORITY_COMMIT,
        "manifest_path": lite_rule_input.MANIFEST_PATH,
        "sources": [],
        "blocking_issues": [],
    }
    if status == "OK":
        raw = RULE_SOURCE_TEXT.encode("utf-8")
        record["manifest_blob_sha"] = seed_sha("synthetic-manifest")
        record["manifest_sha256"] = seed_sha("synthetic-manifest", 64)
        record["sources"] = [{
            "repository_path": RULE_SOURCE_PATH,
            "git_blob_sha": lite_rule_input.git_blob_sha(raw),
            "sha256": lite_rule_input.sha256_of(raw),
            "rule_text": RULE_SOURCE_TEXT,
        }]
    else:
        record["blocking_issues"] = [f"{reason}: {detail}" if detail else reason]
    record["rule_input_sha256"] = lite_rule_input.rule_input_digest(record)
    return record


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_instant(text: str) -> datetime:
    """Read back an ``...Z`` timestamp. Used by the expiry tests so they assert
    "one second past whatever this contract says" instead of past a constant."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def just_after_expiry(contract: dict) -> datetime:
    """One second past the contract's own ``expires_at``."""
    return parse_instant(contract["expires_at"]) + timedelta(seconds=1)


def contract(role: str, *, candidate_sha=CANDIDATE_SHA, application_tree=APPLICATION_TREE,
             cell_id=None, task_id=None, nonce=None, issue_number=ISSUE_NUMBER,
             ledger_reference="auto", issued_at=None, expires_at=None, now=None) -> dict:
    now = now or fresh_now()
    cell_id = cell_id or ("C14" if role == "c14" else "C13")
    task_id = task_id or (C14_TASK if role == "c14" else C13_TASK)
    nonce = nonce or ("c14-nonce-000000000001" if role == "c14" else "c13-nonce-000000000001")
    if ledger_reference == "auto":
        ledger_reference = {"round_id": ROUND_ID, "cell_id": cell_id, "task_id": task_id}
    facts = role_facts(role, candidate_sha=candidate_sha, application_tree=application_tree, cell_id=cell_id, task_id=task_id)
    prompt = lite_ai_reviewer.build_prompt(role, facts)
    return lite_candidate.build(
        repository=REPOSITORY,
        candidate_commit_sha=candidate_sha,
        application_tree=application_tree,
        cell_id=cell_id,
        task_id=task_id,
        request_id=REQUEST_ID,
        nonce=nonce,
        issued_at=_iso(issued_at or (now - timedelta(minutes=5))),
        expires_at=_iso(expires_at or (now + timedelta(minutes=55))),
        workflow_identity=C14_WORKFLOW if role == "c14" else C13_WORKFLOW,
        workflow_sha=C14_WORKFLOW_SHA if role == "c14" else C13_WORKFLOW_SHA,
        review_scope_sha256=RULE_SCOPE if role == "c14" else QUALITY_SCOPE,
        prompt_sha256=lite_canonical.digest_bytes(prompt.encode("utf-8")),
        issue_number=issue_number,
        ledger_reference=ledger_reference,
    )


def role_facts(role: str, *, candidate_sha=CANDIDATE_SHA, application_tree=APPLICATION_TREE,
               cell_id=None, task_id=None) -> dict:
    base = {
        "repository": REPOSITORY,
        "candidate_sha": candidate_sha,
        "application_tree": application_tree,
        "cell_id": cell_id or ("C14" if role == "c14" else "C13"),
        "task_id": task_id or (C14_TASK if role == "c14" else C13_TASK),
        "issue_number": ISSUE_NUMBER,
        "ledger_reference": {
            "round_id": ROUND_ID,
            "cell_id": cell_id or ("C14" if role == "c14" else "C13"),
            "task_id": task_id or (C14_TASK if role == "c14" else C13_TASK),
        },
        # Both cells grade the same paper: the task the candidate was answering, frozen from its
        # own pull request. Present for c13 and c14 alike, because "acceptable for the task" is
        # not a question either cell can answer without it.
        "review_brief": review_brief_record(candidate_sha)["pull_request"],
    }
    if role == "c14":
        rule_input = rule_input_record()
        base["rule_review_scope_sha256"] = RULE_SCOPE
        base["rule_sources"] = [
            {**lite_rule_input.identity(source), "rule_text": source["rule_text"]}
            for source in rule_input["sources"]
        ]
        base["rule_input_sha256"] = rule_input["rule_input_sha256"]
        base["authority_commit"] = rule_input["authority_commit"]
        base["changed_paths"] = ["control-plane/c13-c14-lite/lite_chain.py"]
    else:
        base["quality_test_scope_sha256"] = QUALITY_SCOPE
        base["machine_evidence"] = {
            "junit_sha256": "synthetic",
            "stdout_sha256": "synthetic",
            "manifest_sha256": "synthetic",
        }
        base["acceptance_criteria"] = ["negative suite rejects every tampered record"]
    return base


def opinion(role: str, *, verdict="PASS_SCOPED", candidate_sha=CANDIDATE_SHA,
            findings=None, blocking_issues=None, remediation_status="NOT_REQUIRED",
            not_applicable=None, remaining_risks=None) -> dict:
    if role == "c14":
        return {
            "verdict": verdict,
            "candidate_sha": candidate_sha,
            "findings": list(findings or []),
            "blocking_issues": list(blocking_issues or []),
            "remediation_status": remediation_status,
            "not_applicable": not_applicable,
            "summary": "synthetic rule review",
        }
    return {
        "verdict": verdict,
        "candidate_sha": candidate_sha,
        "quality_findings": list(findings or []),
        "remaining_risks": list(remaining_risks or []),
        "summary": "synthetic quality acceptance",
    }


def build_bundle(role: str, *, candidate_sha=CANDIDATE_SHA, application_tree=APPLICATION_TREE,
                 dispatch_contract=None, opinion_obj=None, run_id=None, run_attempt=1,
                 execution_id=None, nonce=None, failure_class=None, verdict=None,
                 prereq=None, issued_at=None, now=None) -> tuple:
    """Return ``(bundle, artifacts)`` for one role."""
    now = now or fresh_now()
    contract_obj = dispatch_contract if dispatch_contract is not None else contract(
        role, candidate_sha=candidate_sha, application_tree=application_tree, now=now)
    opinion_obj = opinion_obj if opinion_obj is not None else opinion(role, candidate_sha=candidate_sha)
    facts = role_facts(role, candidate_sha=candidate_sha, application_tree=application_tree,
                       cell_id=contract_obj["cell_id"], task_id=contract_obj["task_id"])
    prompt = lite_ai_reviewer.build_prompt(role, facts)

    artifacts = {}
    effective_verdict = verdict or opinion_obj["verdict"]
    # A provider/quota failure means no opinion was ever produced, so the record must not
    # carry identities belonging to a review that never completed. The fixture builds that
    # shape rather than a plausible-looking one, because a plausible-looking one is exactly
    # what validation refuses.
    provider_failure = bool(failure_class) and effective_verdict == lite_errors.BLOCKED
    if role == "c14":
        fields = {
            "schema_version": lite_bundle.SCHEMA_VERSION_C14,
            "cell_id": "C14",
            "task_id": contract_obj["task_id"],
            "issue_number": contract_obj["issue_number"],
            "ledger_reference": contract_obj["ledger_reference"],
            "candidate_sha": candidate_sha,
            "application_tree": application_tree,
            "nonce": nonce or contract_obj["nonce"],
            "rule_review_scope_sha256": contract_obj["review_scope_sha256"],
            "authority_commit": facts["authority_commit"],
            "rule_input_sha256": facts["rule_input_sha256"],
            "rule_sources": [lite_rule_input.identity(source) for source in facts["rule_sources"]],
            "not_applicable": opinion_obj["not_applicable"],
            "github_run_id": run_id or 900001,
            "github_run_attempt": run_attempt,
            "workflow_ref": f"{REPOSITORY}/{contract_obj['workflow_sha']}",
            "workflow_sha": contract_obj["workflow_sha"],
            "ai_provider": lite_ai_reviewer.STUB_PROVIDER,
            "ai_model": None if provider_failure else "deterministic-stub",
            "ai_execution_id": None if provider_failure else (execution_id or "stub-c14-ai-execution-0001"),
            "principal_id": "synthetic-principal",
            "review_execution_id": None if provider_failure else (execution_id or "stub-c14-ai-execution-0001"),
            "prompt_sha256": contract_obj["prompt_sha256"],
            "input_sha256": lite_canonical.digest(facts),
            "opinion_sha256": None if provider_failure else lite_canonical.digest(opinion_obj),
            "findings": opinion_obj["findings"],
            "blocking_issues": opinion_obj["blocking_issues"],
            "remediation_status": opinion_obj["remediation_status"],
            "verdict": effective_verdict,
            "failure_class": failure_class,
            "decision_origin": lite_errors.AI_REVIEW,
            "ai_called": True,
            "issued_at": _iso(issued_at or (now + timedelta(minutes=1))),
            "authorizes_any_action": False,
        }
        if not provider_failure:
            # No opinion was produced, so there is no opinion artefact to bind. The verifier
            # skips an artefact that was not supplied; it never demands one for a record whose
            # whole point is that no opinion exists.
            artifacts["c14_opinion"] = lite_canonical.canonical(opinion_obj)
    else:
        if prereq is None:
            raise ValueError("c13 bundle requires prereq")
        machine = machine_evidence()
        fields = {
            "schema_version": lite_bundle.SCHEMA_VERSION_C13,
            "cell_id": "C13",
            "task_id": contract_obj["task_id"],
            "issue_number": contract_obj["issue_number"],
            "ledger_reference": contract_obj["ledger_reference"],
            "candidate_sha": candidate_sha,
            "application_tree": application_tree,
            "nonce": nonce or contract_obj["nonce"],
            "quality_test_scope_sha256": contract_obj["review_scope_sha256"],
            "c14_prerequisite": prereq,
            "machine_job": {
                "runner": "ubuntu-24.04",
                "runner_os": "Linux",
                "postgres_version": "18.4",
                "docker_used": True,
                "test_inventory_sha256": machine["test_inventory_sha256"],
                "junit_sha256": machine["junit_sha256"],
                "stdout_sha256": machine["stdout_sha256"],
                "manifest_sha256": machine["manifest_sha256"],
            },
            "github_run_id": run_id or 900002,
            "github_run_attempt": run_attempt,
            "workflow_ref": f"{REPOSITORY}/{contract_obj['workflow_sha']}",
            "workflow_sha": contract_obj["workflow_sha"],
            "ai_provider": lite_ai_reviewer.STUB_PROVIDER,
            "ai_model": "deterministic-stub",
            "ai_execution_id": execution_id or "stub-c13-ai-execution-0001",
            "principal_id": "synthetic-principal",
            "review_execution_id": execution_id or "stub-c13-ai-execution-0001",
            "prompt_sha256": contract_obj["prompt_sha256"],
            "input_sha256": lite_canonical.digest(facts),
            "opinion_sha256": lite_canonical.digest(opinion_obj),
            "junit_sha256": machine["junit_sha256"],
            "stdout_sha256": machine["stdout_sha256"],
            "manifest_sha256": machine["manifest_sha256"],
            "quality_findings": opinion_obj["quality_findings"],
            "remaining_risks": opinion_obj["remaining_risks"],
            "verdict": verdict or opinion_obj["verdict"],
            "failure_class": failure_class,
            "issued_at": _iso(issued_at or (now + timedelta(minutes=2))),
            "authorizes_any_action": False,
        }
        artifacts["c13_opinion"] = lite_canonical.canonical(opinion_obj)
        artifacts.update(machine["files"])
    return lite_bundle.seal(fields), artifacts


def machine_evidence() -> dict:
    files = {
        "junit": b"<testsuite name='synthetic' tests='3' failures='0'/>\n",
        "stdout": b"synthetic machine test stdout\n",
        "manifest": b'{"tests":3,"failures":0,"synthetic":true}\n',
    }
    return {
        "files": files,
        "junit_sha256": hashlib.sha256(files["junit"]).hexdigest(),
        "stdout_sha256": hashlib.sha256(files["stdout"]).hexdigest(),
        "manifest_sha256": hashlib.sha256(files["manifest"]).hexdigest(),
        "test_inventory_sha256": seed_sha("synthetic-test-inventory", 64),
    }


def make_round(*, candidate_sha=CANDIDATE_SHA, application_tree=APPLICATION_TREE,
               c14_verdict="PASS_SCOPED", c14_remediation="NOT_REQUIRED",
               c14_not_applicable=None, c14_findings=None, c14_blocking=None,
               c14_failure_class=None, c13_verdict="PASS_SCOPED", c13_failure_class=None,
               implementation_execution_id="impl-ai-execution-0001",
               c14_execution_id="stub-c14-ai-execution-0001",
               c13_execution_id="stub-c13-ai-execution-0001",
               c14_run_id=900001, c13_run_id=900002,
               c14_nonce="c14-nonce-000000000001", c13_nonce="c13-nonce-000000000001",
               with_c14=True, now=None) -> dict:
    """Assemble a complete, internally consistent synthetic round."""
    now = now or fresh_now()
    c14_contract = contract("c14", candidate_sha=candidate_sha, application_tree=application_tree, nonce=c14_nonce, now=now)
    c14_opinion = opinion(
        "c14", verdict=c14_verdict, candidate_sha=candidate_sha, findings=c14_findings,
        blocking_issues=c14_blocking, remediation_status=c14_remediation,
        not_applicable=c14_not_applicable,
    )
    c14_bundle, c14_artifacts = build_bundle(
        "c14", candidate_sha=candidate_sha, application_tree=application_tree,
        dispatch_contract=c14_contract, opinion_obj=c14_opinion, run_id=c14_run_id,
        execution_id=c14_execution_id, nonce=c14_nonce, failure_class=c14_failure_class, now=now,
    )
    prereq = {
        "c14_root": c14_bundle[lite_bundle.C14_ROOT_FIELD],
        "c14_verdict": c14_bundle["verdict"],
        "c14_candidate_sha": c14_bundle["candidate_sha"],
        "c14_rule_scope_sha256": c14_bundle["rule_review_scope_sha256"],
        "c14_remediation_closed": c14_bundle["remediation_status"] in ("CLOSED", "NOT_REQUIRED"),
    }
    c13_contract = contract("c13", candidate_sha=candidate_sha, application_tree=application_tree, nonce=c13_nonce, now=now)
    c13_opinion = opinion("c13", verdict=c13_verdict, candidate_sha=candidate_sha,
                          remaining_risks=["synthetic residual risk"])
    c13_bundle, c13_artifacts = build_bundle(
        "c13", candidate_sha=candidate_sha, application_tree=application_tree,
        dispatch_contract=c13_contract, opinion_obj=c13_opinion, run_id=c13_run_id,
        execution_id=c13_execution_id, nonce=c13_nonce, failure_class=c13_failure_class,
        prereq=prereq, now=now,
    )
    artifacts = dict(c14_artifacts)
    artifacts.update(c13_artifacts)
    return {
        "dispatch": {
            "candidate_sha": candidate_sha,
            "application_tree": application_tree,
            "cell_pair": "C13+C14",
            "issue_number": ISSUE_NUMBER,
            "request_id": REQUEST_ID,
            "c14_task_id": C14_TASK,
            "c13_task_id": C13_TASK,
            "c14_ledger_reference": c14_contract["ledger_reference"],
            "c13_ledger_reference": c13_contract["ledger_reference"],
        },
        "c14_contract": c14_contract,
        "c13_contract": c13_contract,
        "c14_bundle": c14_bundle if with_c14 else None,
        "c13_bundle": c13_bundle,
        "c14_artifacts": c14_artifacts,
        "c13_artifacts": c13_artifacts,
        "artifacts": artifacts,
        "implementation_execution_id": implementation_execution_id,
        "prereq": prereq,
        "now": now,
    }


def chain_kwargs(round_ = None, **overrides) -> dict:
    """Build the ``verify_round`` keyword arguments from a fixture round."""
    round_ = round_ or make_round()
    kwargs = {
        "c14_bundle": round_["c14_bundle"],
        "c13_bundle": round_["c13_bundle"],
        "c14_contract": round_["c14_contract"],
        "c13_contract": round_["c13_contract"],
        "dispatch": round_["dispatch"],
        "implementation_execution_id": round_["implementation_execution_id"],
        "artifacts": round_["artifacts"],
        "now": round_["now"],
    }
    kwargs.update(overrides)
    return kwargs


def synthetic_ledger(*, c14_task_id=C14_TASK, c13_task_id=C13_TASK) -> dict:
    """A 14-cell ledger shaped exactly like ``ci/round2/example-ledger.json``."""
    import lite_ledger_binding

    cells = []
    for index in range(1, 15):
        cell_id = f"C{index:02d}"
        task_id = f"{cell_id}-fixture-scope1"
        if cell_id == "C14":
            task_id = c14_task_id
        if cell_id == "C13":
            task_id = c13_task_id
        cells.append({
            "cell_id": cell_id,
            "executable_gap": False,
            "next_task": None,
            "domain_completion": None,
            "task": {
                "id": task_id,
                "description": f"{cell_id} synthetic fixture task",
                "scope": "synthetic fixture only",
                "test_plan": "run the isolated fixture checks and record the exit code",
                "status": "ASSIGNED",
                "completion": {"percent": 0, "definition": f"one {cell_id} fixture plus bound evidence"},
                "evidence": [],
                "execution_evidence_refs": [],
                "gates": {name: {"status": "HOLD", "evidence_refs": []} for name in lite_ledger_binding.GATE_NAMES},
            },
        })
    return {
        "schema_version": 1,
        "round_id": ROUND_ID,
        "source_anchor": lite_ledger_binding.source_anchor(),
        "events": [],
        "followups": [],
        "cells": cells,
    }


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
